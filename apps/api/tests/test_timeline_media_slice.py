"""Tests for timeline-window media slicing (the alignment delivery path).

Real-ffmpeg ``media``-marked tests: a generated source video and audio file
are sliced to a window, and the slice's probed duration must match the
requested window (frame-accurate re-encode, not keyframe cut). Degradation
paths (missing source, window beyond source, degenerate window) are locked
with warnings, never silent.
"""

from __future__ import annotations

import subprocess

import pytest

from app.services.timeline_media_slice import (
    MediaSliceError,
    probe_media_duration,
    slice_media_to_window,
)

pytestmark = pytest.mark.media

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def _ffmpeg_available() -> bool:
    try:
        return subprocess.run([FFMPEG, "-version"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(
    not _ffmpeg_available(), reason="ffmpeg not installed"
)


@pytest.fixture
def source_video(tmp_path):
    """A 6-second test video with a frame counter burned in."""

    path = tmp_path / "source.mp4"
    command = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", "testsrc2=duration=6:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
        "-shortest", path.as_posix(),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return path


@pytest.fixture
def source_audio(tmp_path):
    path = tmp_path / "source.mp3"
    command = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:a", "libmp3lame", path.as_posix(),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return path


def test_probe_media_duration_reads_real_files(source_video) -> None:
    duration = probe_media_duration(source_video, FFPROBE)
    assert duration is not None
    assert 5.5 <= duration <= 6.5


def test_slice_video_to_window_is_frame_accurate(tmp_path, source_video) -> None:
    result = slice_media_to_window(
        source_video,
        start_time=2.0,
        duration=1.5,
        output_dir=tmp_path / "out",
        workflow_id="wf-1",
        kind="video",
        ffmpeg_path=FFMPEG,
        ffprobe_path=FFPROBE,
    )
    assert result.sliced is True
    assert result.path is not None and result.path.is_file()
    assert result.warnings == []
    sliced_duration = probe_media_duration(result.path, FFPROBE)
    assert sliced_duration is not None
    # Frame-accurate re-encode: within ~2 frames of the requested 1.5s.
    assert abs(sliced_duration - 1.5) < 0.1


def test_slice_audio_to_window(tmp_path, source_audio) -> None:
    result = slice_media_to_window(
        source_audio,
        start_time=1.0,
        duration=2.0,
        output_dir=tmp_path / "out",
        workflow_id="wf-1",
        kind="audio",
        ffmpeg_path=FFMPEG,
        ffprobe_path=FFPROBE,
    )
    assert result.sliced is True
    sliced_duration = probe_media_duration(result.path, FFPROBE)
    assert sliced_duration is not None
    assert abs(sliced_duration - 2.0) < 0.15


def test_slice_clamps_window_beyond_source(tmp_path, source_video) -> None:
    result = slice_media_to_window(
        source_video,
        start_time=5.0,
        duration=3.0,  # only ~1s of source left
        output_dir=tmp_path / "out",
        workflow_id="wf-1",
        kind="video",
        ffmpeg_path=FFMPEG,
        ffprobe_path=FFPROBE,
    )
    assert result.sliced is True
    assert any("slice_window_clamped" in warning for warning in result.warnings)
    sliced_duration = probe_media_duration(result.path, FFPROBE)
    assert sliced_duration is not None
    assert sliced_duration < 1.5


def test_slice_rejects_window_starting_beyond_source(tmp_path, source_video) -> None:
    result = slice_media_to_window(
        source_video,
        start_time=99.0,
        duration=2.0,
        output_dir=tmp_path / "out",
        workflow_id="wf-1",
        kind="video",
        ffmpeg_path=FFMPEG,
        ffprobe_path=FFPROBE,
    )
    assert result.sliced is False
    assert result.path is None
    assert any("slice_window_beyond_source" in warning for warning in result.warnings)


def test_slice_reports_missing_source(tmp_path) -> None:
    result = slice_media_to_window(
        tmp_path / "nope.mp4",
        start_time=0.0,
        duration=2.0,
        output_dir=tmp_path / "out",
        workflow_id="wf-1",
        ffmpeg_path=FFMPEG,
        ffprobe_path=FFPROBE,
    )
    assert result.sliced is False
    assert any("slice_source_missing" in warning for warning in result.warnings)


def test_slice_rejects_invalid_windows(tmp_path, source_video) -> None:
    with pytest.raises(MediaSliceError):
        slice_media_to_window(
            source_video, start_time=-1.0, duration=2.0,
            output_dir=tmp_path / "out", workflow_id="wf-1",
        )
    with pytest.raises(MediaSliceError):
        slice_media_to_window(
            source_video, start_time=0.0, duration=0.0,
            output_dir=tmp_path / "out", workflow_id="wf-1",
        )
