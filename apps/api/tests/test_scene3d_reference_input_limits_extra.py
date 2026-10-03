"""Shared policy rejects malformed probe data and direct oversized input."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.services.scene3d import reference_upload as upload
from app.services.scene3d import reference_video_analyzer as analyzer

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("duration,rate", [("nan", "30/1"), ("inf", "30/1"),
                                          ("10", "0/0"), ("10", "inf/1")])
def test_unknown_count_with_nonfinite_probe_metadata_is_rejected(tmp_path, monkeypatch,
                                                                 duration, rate):
    video = tmp_path / "valid.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(upload, "_run_ffprobe", lambda _: {
        "streams": [{"codec_type": "video", "r_frame_rate": rate,
                     "nb_frames": "N/A", "width": 640, "height": 480}],
        "format": {"duration": duration},
    })
    metadata = upload.extract_metadata(video)
    with pytest.raises(upload.UploadError):
        upload.validate_metadata(metadata)


@pytest.mark.parametrize("name,data", [("invalid.exe", b"video"), ("valid.mp4", b""),
                                       ("valid.mp4", b"x" * (1024 * 1024 + 1))],
                         ids=["invalid-format", "empty", "oversized"])
def test_direct_analyzer_upload_policy_precedes_probe(tmp_path, monkeypatch, name, data):
    monkeypatch.setattr(upload, "MAX_FILE_SIZE_MB", 1)
    video = tmp_path / name
    video.write_bytes(data)
    probe = Mock(side_effect=AssertionError("no probe"))
    monkeypatch.setattr(analyzer, "extract_metadata", probe)
    with pytest.raises(analyzer.AnalysisError, match="input"):
        analyzer.analyze_reference_video(video)
    probe.assert_not_called()


def test_direct_extractor_rejects_metadata_before_output_or_ffmpeg(tmp_path, monkeypatch):
    video = tmp_path / "valid.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(upload, "extract_metadata", lambda _: upload.VideoMetadata(
        60.01, 640, 480, 30.0, 1800, "h264", 5,
    ))
    ffmpeg = Mock(side_effect=AssertionError("no ffmpeg"))
    monkeypatch.setattr(upload.subprocess, "run", ffmpeg)
    output = tmp_path / "frames"
    with pytest.raises(upload.UploadError, match="too long"):
        upload.extract_keyframes_from_video(video, output)
    assert not output.exists()
    ffmpeg.assert_not_called()
