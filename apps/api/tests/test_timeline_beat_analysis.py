"""Unit tests for the numpy beat/BPM analysis helpers (plan 4.4).

End-to-end ffmpeg decoding is covered by the ``media`` test; these exercise
the DSP math directly with synthetic signals.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.timeline_beat_analysis import (
    BeatAnalysisError,
    analyze_samples,
    estimate_bpm,
    onset_envelope,
    pick_beats,
)

_SAMPLE_RATE = 22_050


def _kick_track(bpm: float, seconds: float, *, burst_seconds: float = 0.06) -> np.ndarray:
    """Synthesize decaying noise bursts on a fixed grid (kick-like onsets)."""
    rng = np.random.default_rng(7)
    samples = np.zeros(int(seconds * _SAMPLE_RATE), dtype=np.float32)
    period = 60.0 / bpm
    burst_len = int(burst_seconds * _SAMPLE_RATE)
    decay = np.exp(-np.linspace(0.0, 6.0, burst_len))
    beat = 0
    while beat * period < seconds:
        start = int(beat * period * _SAMPLE_RATE)
        end = min(samples.size, start + burst_len)
        samples[start:end] = (rng.standard_normal(end - start) * decay[: end - start]).astype(
            np.float32
        )
        beat += 1
    # A quiet continuous bed keeps the signal non-trivial without masking onsets.
    samples += (0.002 * rng.standard_normal(samples.size)).astype(np.float32)
    return samples


class TestAnalyzeSamples:
    def test_recovers_bpm_and_beat_grid_for_percussive_track(self) -> None:
        samples = _kick_track(120.0, 10.0)
        analysis = analyze_samples(samples, sample_rate=_SAMPLE_RATE)

        assert 117.0 <= analysis.bpm <= 123.0
        assert analysis.confidence > 0.2
        # 10s at 120 BPM -> 20 beats (grid positions 0..9.5s), allow tolerance
        # for boundary/peak-picking differences.
        assert 18 <= len(analysis.beats) <= 21
        assert analysis.beats[0] == pytest.approx(0.0, abs=0.05)
        intervals = np.diff(analysis.beats)
        assert np.median(intervals) == pytest.approx(0.5, abs=0.04)

    def test_tracks_a_slower_tempo(self) -> None:
        samples = _kick_track(84.0, 12.0)
        analysis = analyze_samples(samples, sample_rate=_SAMPLE_RATE)
        assert 81.0 <= analysis.bpm <= 87.0
        assert np.median(np.diff(analysis.beats)) == pytest.approx(
            60.0 / 84.0, abs=0.05
        )

    def test_silence_is_indeterminate(self) -> None:
        silence = np.zeros(4 * _SAMPLE_RATE, dtype=np.float32)
        with pytest.raises(BeatAnalysisError) as excinfo:
            analyze_samples(silence, sample_rate=_SAMPLE_RATE)
        assert excinfo.value.code == "beat_analysis_indeterminate"

    def test_beats_are_monotonic_and_within_source_duration(self) -> None:
        samples = _kick_track(100.0, 8.0)
        analysis = analyze_samples(samples, sample_rate=_SAMPLE_RATE)
        assert list(analysis.beats) == sorted(analysis.beats)
        assert all(0.0 <= beat <= 8.0 for beat in analysis.beats)


class TestOnsetEnvelope:
    def test_zero_for_silence_and_non_negative(self) -> None:
        flux = onset_envelope(
            np.zeros(_SAMPLE_RATE, dtype=np.float32), frame_length=1024, hop_length=512
        )
        assert flux.size > 0
        assert np.all(flux == 0.0)

    def test_empty_for_too_short_input(self) -> None:
        flux = onset_envelope(np.zeros(10, dtype=np.float32), 1024, 512)
        assert flux.size == 0


class TestEstimateBpm:
    def test_zero_for_flat_envelope(self) -> None:
        bpm, lag, confidence = estimate_bpm(np.zeros(100), 43.0)
        assert (bpm, lag, confidence) == (0.0, 0, 0.0)


class TestPickBeats:
    def test_walks_the_period_to_the_end(self) -> None:
        frames_per_second = _SAMPLE_RATE / 512
        period = frames_per_second * 0.5
        frames = pick_beats(
            onset_envelope(
                _kick_track(120.0, 6.0), frame_length=1024, hop_length=512
            ),
            period,
        )
        assert frames[0] == 0
        gaps = np.diff(frames)
        assert np.median(gaps) == pytest.approx(period, abs=1.5)
