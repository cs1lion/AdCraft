"""Real-FFmpeg acceptance test for BGM beat detection (plan 4.4).

Marked ``media``: writes a 120 BPM percussive WAV to disk, decodes it through
ffmpeg via BeatAnalyzer (the production code path used by the beats endpoint),
and asserts the estimated tempo and beat grid match the synthesized onsets.
"""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.timeline_beat_analysis import BeatAnalyzer

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg not available for media tests",
)

_SAMPLE_RATE = 22_050
_SECONDS = 12.0
_BPM = 120.0


def _write_kick_wav(path: Path) -> None:
    rng = np.random.default_rng(11)
    samples = np.zeros(int(_SECONDS * _SAMPLE_RATE), dtype=np.float32)
    period = 60.0 / _BPM
    burst_len = int(0.08 * _SAMPLE_RATE)
    decay = np.exp(-np.linspace(0.0, 7.0, burst_len))
    beat = 0
    while beat * period < _SECONDS:
        start = int(beat * period * _SAMPLE_RATE)
        end = min(samples.size, start + burst_len)
        # Low-frequency thump (80 Hz) plus noise click.
        t = np.arange(end - start) / _SAMPLE_RATE
        tone = np.sin(2 * np.pi * 80 * t) * decay[: end - start]
        click = rng.standard_normal(end - start) * decay[: end - start] * 0.5
        samples[start:end] = 0.6 * tone + 0.3 * click
        beat += 1
    samples += (0.003 * rng.standard_normal(samples.size)).astype(np.float32)

    pcm16 = np.clip(samples, -1.0, 1.0)
    pcm16 = (pcm16 * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_SAMPLE_RATE)
        wav.writeframes(pcm16.tobytes())


def test_analyzes_known_tempo_through_ffmpeg(tmp_path: Path) -> None:
    wav_path = tmp_path / "drums_120.wav"
    _write_kick_wav(wav_path)

    analysis = BeatAnalyzer(shutil.which("ffmpeg")).analyze(str(wav_path))

    assert 117.0 <= analysis.bpm <= 123.0
    assert analysis.confidence > 0.2
    # 12s at 120 BPM => 24 downbeats from t=0; boundary tolerance for the tail.
    assert 22 <= len(analysis.beats) <= 25
    assert analysis.beats[0] == pytest.approx(0.0, abs=0.06)
    intervals = np.diff(analysis.beats)
    assert np.median(intervals) == pytest.approx(0.5, abs=0.05)
    # No interval should be wildly off (missed/doubled beats would show 2x/0.5x).
    assert np.all(intervals > 0.3)
    assert np.all(intervals < 0.75)
