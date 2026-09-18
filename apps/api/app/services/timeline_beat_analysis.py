"""Lightweight beat/BPM analysis for timeline BGM clips (Phase 4.4).

No third-party DSP dependency: ffmpeg decodes any registered audio asset to
mono float PCM, then numpy derives an onset-strength envelope and estimates
tempo by normalized autocorrelation. Beat positions are peak-picked around
the estimated period with an adaptive local-energy threshold.

The output is intentionally approximate (±2 BPM on percussive material); it
drives visual beat markers and snapping, not sample-accurate scheduling.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

import numpy as np

_SAMPLE_RATE = 22_050
_FRAME_LENGTH = 1_024
_HOP_LENGTH = 256
_MIN_BPM = 60.0
_MAX_BPM = 180.0
# Reject absurdly short inputs (a handful of frames yields nonsense lags).
_MIN_ANALYSIS_SECONDS = 2.0
# Peak search window around each predicted beat, as a fraction of the period.
_PEAK_SEARCH_FRACTION = 0.18
_LOCAL_WINDOW_SECONDS = 0.5


class BeatAnalysisError(RuntimeError):
    """Raised when audio cannot be decoded or is too short to analyse."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class BeatAnalysis:
    bpm: float
    beats: tuple[float, ...]
    confidence: float


class BeatAnalyzer:
    def __init__(self, ffmpeg_path: str | None = "ffmpeg") -> None:
        self._ffmpeg_path = ffmpeg_path or "ffmpeg"

    def analyze(self, audio_path: str) -> BeatAnalysis:
        samples = self._decode_mono(audio_path)
        return analyze_samples(samples, sample_rate=_SAMPLE_RATE)

    def _decode_mono(self, audio_path: str) -> np.ndarray:
        command = [
            self._ffmpeg_path,
            "-v",
            "error",
            "-i",
            audio_path,
            "-ac",
            "1",
            "-ar",
            str(_SAMPLE_RATE),
            "-f",
            "f32le",
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BeatAnalysisError(
                "beat_analysis_unavailable",
                "ffmpeg could not decode the audio asset.",
            ) from exc
        if completed.returncode != 0 or not completed.stdout:
            raise BeatAnalysisError(
                "beat_analysis_unavailable",
                "ffmpeg could not decode the audio asset.",
            )
        samples = np.frombuffer(completed.stdout, dtype=np.float32)
        if samples.size < _SAMPLE_RATE * _MIN_ANALYSIS_SECONDS:
            raise BeatAnalysisError(
                "beat_analysis_too_short",
                "Audio must be at least 2 seconds for beat analysis.",
            )
        return samples


def onset_envelope(samples: np.ndarray, frame_length: int, hop_length: int) -> np.ndarray:
    """RMS energy per hop followed by positive log-energy differences."""

    if samples.size < frame_length:
        return np.zeros(0, dtype=np.float64)
    # Strided views avoid allocating a framed copy.
    frame_count = 1 + (samples.size - frame_length) // hop_length
    framed = np.lib.stride_tricks.as_strided(
        samples,
        shape=(frame_count, frame_length),
        strides=(samples.strides[0] * hop_length, samples.strides[0]),
        writeable=False,
    )
    rms = np.sqrt(np.mean(framed.astype(np.float64) ** 2, axis=1))
    log_energy = np.log1p(1e4 * rms)
    # Prepend silence so an onset sitting on the very first frame is detected.
    flux = np.diff(log_energy, prepend=0.0)
    return np.maximum(flux, 0.0)


def estimate_bpm(flux: np.ndarray, frames_per_second: float) -> tuple[float, int, float]:
    """Return (bpm, lag_in_frames, confidence) from onset-flux autocorrelation."""

    centered = flux - flux.mean()
    if not np.any(centered):
        return 0.0, 0, 0.0
    n = centered.size
    spectrum = np.fft.rfft(centered, n=2 * n)
    autocorr = np.fft.irfft(spectrum * np.conj(spectrum), n=2 * n)[:n]
    # Unbiased normalization so distant lags stay comparable.
    normalization = np.arange(n, 0, -1)
    autocorr = autocorr / normalization
    zero_lag = autocorr[0]
    if zero_lag <= 0:
        return 0.0, 0, 0.0
    autocorr = autocorr / zero_lag

    lag_min = max(1, int(round(frames_per_second * 60.0 / _MAX_BPM)))
    lag_max = min(n - 2, int(round(frames_per_second * 60.0 / _MIN_BPM)))
    if lag_max <= lag_min:
        return 0.0, 0, 0.0
    lag = int(np.argmax(autocorr[lag_min : lag_max + 1]) + lag_min)
    salience = float(autocorr[lag])

    # Octave resolution: a periodic impulse train correlates equally at the
    # true period and its multiples, and hop quantization makes the 2x lag
    # align more tightly than the true (possibly fractional-frame) period.
    # Interpolate the autocorrelation at the half-period lag and prefer the
    # faster tempo (musically conventional in 60–180 BPM) when it is nearly
    # as salient. Loop to unwrap a 4x capture as well.
    for _ in range(2):
        half_target = lag / 2.0
        if half_target < lag_min:
            break
        lo = int(np.floor(half_target))
        fraction = half_target - lo
        if lo + 1 >= autocorr.size:
            break
        half_salience = (
            float(autocorr[lo]) * (1.0 - fraction)
            + float(autocorr[lo + 1]) * fraction
        )
        if half_salience < 0.8 * salience:
            break
        lag = int(round(half_target))
        salience = half_salience

    bpm = frames_per_second * 60.0 / lag
    background = autocorr[lag_min : lag_max + 1]
    background_mean = float(np.mean(background))
    background_std = float(np.std(background))
    confidence = 0.0 if background_std <= 1e-9 else min(
        1.0, max(0.0, (salience - background_mean) / (3.0 * background_std))
    )
    return float(bpm), lag, float(confidence)


def pick_beats(flux: np.ndarray, period_frames: float) -> tuple[int, ...]:
    """Peak-pick beat frames on a grid, nudging each to the strongest nearby onset."""

    if flux.size == 0 or period_frames <= 0:
        return ()
    radius = max(1, int(round(period_frames * _PEAK_SEARCH_FRACTION)))
    window = max(1, int(round(period_frames * _LOCAL_WINDOW_SECONDS)))
    threshold = float(flux.mean() + 0.5 * flux.std())

    beats: list[int] = []
    first_search_end = min(flux.size, max(1, int(round(period_frames))))
    first = int(np.argmax(flux[:first_search_end]))
    if flux[first] >= threshold:
        beats.append(first)
    else:
        beats.append(0)

    while True:
        expected = beats[-1] + period_frames
        if expected - radius >= flux.size:
            break
        lo = max(0, int(round(expected)) - radius)
        hi = min(flux.size, int(round(expected)) + radius + 1)
        candidate = lo + int(np.argmax(flux[lo:hi]))
        window_lo = max(0, candidate - window)
        local_mean = float(np.mean(flux[window_lo : min(flux.size, candidate + window + 1)]))
        # Keep the grid position when the neighbourhood shows no clear onset;
        # only snap when the candidate rises above its local floor.
        if flux[candidate] >= local_mean and flux[candidate] >= threshold * 0.6:
            beats.append(candidate)
        else:
            beats.append(int(round(expected)))
    # Deduplicate (a nudged beat can coincide with its predecessor).
    deduped: list[int] = []
    for frame in beats:
        if not deduped or frame - deduped[-1] >= max(1, int(period_frames * 0.5)):
            deduped.append(frame)
    return tuple(deduped)


def analyze_samples(samples: np.ndarray, *, sample_rate: int) -> BeatAnalysis:
    flux = onset_envelope(
        samples, frame_length=_FRAME_LENGTH, hop_length=_HOP_LENGTH
    )
    frames_per_second = sample_rate / _HOP_LENGTH
    bpm, lag, confidence = estimate_bpm(flux, frames_per_second)
    if lag <= 0:
        raise BeatAnalysisError(
            "beat_analysis_indeterminate",
            "Could not detect a steady beat in the audio.",
        )
    beat_frames = pick_beats(flux, float(lag))
    beats = tuple(
        round(frame * _HOP_LENGTH / sample_rate, 3) for frame in beat_frames
    )
    return BeatAnalysis(bpm=round(bpm, 1), beats=beats, confidence=round(confidence, 3))
