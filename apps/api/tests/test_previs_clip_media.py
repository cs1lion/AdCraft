"""Previs clip media cuts against real ffmpeg (ADR 0017).

Trim and keyframe extraction shell out to ffmpeg, so these are media-marked
tests with real encoded input — placeholder bytes cannot lock the two
behaviors that matter: a trim that lands on the requested shot boundary
(inside the clip, not snapped to a source keyframe), and keyframes sampled
at even offsets across the clip's own duration.
"""

from __future__ import annotations

import subprocess

import pytest

from app.services.scene3d.previs_clip_media import extract_keyframes, trim_previs_clip

pytestmark = pytest.mark.media


def _clip(path, *, seconds: float = 3.0) -> str:
    """A real H.264 MP4 (counting test pattern) — the input a trim actually sees."""

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"testsrc=duration={seconds}:size=320x240:rate=30",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            path,
        ],
        capture_output=True,
        timeout=120,
        check=True,
    )
    return str(path)


def _probe_duration(path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return float(result.stdout.strip())


class TestTrimPrevisClip:
    def test_trim_cuts_the_requested_range(self, tmp_path) -> None:
        source = _clip(tmp_path / "scene.mp4")
        out = tmp_path / "shot.mp4"
        result = trim_previs_clip(source, out, start_seconds=0.5, end_seconds=2.0)
        assert result.success, result.error
        # Re-encode keeps the cut near the boundary; a stream copy would snap
        # to the source keyframe (the 0s GOP head) and return the whole scene.
        duration = _probe_duration(str(out))
        assert 1.2 <= duration <= 1.8

    def test_non_positive_duration_is_refused(self, tmp_path) -> None:
        source = _clip(tmp_path / "scene.mp4")
        result = trim_previs_clip(
            source, tmp_path / "out.mp4", start_seconds=2.0, end_seconds=2.0
        )
        assert not result.success
        assert "Non-positive" in (result.error or "")

    def test_missing_source_is_a_failure_not_a_raise(self, tmp_path) -> None:
        result = trim_previs_clip(
            tmp_path / "missing.mp4", tmp_path / "out.mp4", start_seconds=0.0, end_seconds=1.0
        )
        assert not result.success


class TestExtractKeyframes:
    def test_five_keyframes_at_even_offsets(self, tmp_path) -> None:
        clip = _clip(tmp_path / "clip.mp4", seconds=2.5)
        keyframes = extract_keyframes(clip, duration_seconds=2.5, count=5)
        assert len(keyframes) == 5
        offsets = [keyframe.offset_seconds for keyframe in keyframes]
        assert offsets[0] == 0.0
        assert all(
            later > earlier for earlier, later in zip(offsets, offsets[1:])
        ), f"offsets not increasing: {offsets}"
        assert all(len(keyframe.png_bytes) > 0 for keyframe in keyframes)

    def test_zero_duration_yields_no_keyframes(self, tmp_path) -> None:
        assert extract_keyframes(tmp_path / "clip.mp4", duration_seconds=0.0) == []
