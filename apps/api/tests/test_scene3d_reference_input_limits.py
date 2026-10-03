"""Reference guards must fail before extraction, persistence, or paid calls."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.api.v1.endpoints import scene_3d as endpoint
from app.services.scene3d import reference_upload as upload
from app.services.scene3d import reference_video_analyzer as analyzer

pytestmark = pytest.mark.integration


def metadata(**changes):
    return replace(upload.VideoMetadata(10.0, 640, 480, 30.0, 300, "h264", 5), **changes)


@pytest.mark.parametrize("count", [0, -1, 13, 1000, 1.5, True])
def test_direct_count_guards_precede_io(tmp_path, monkeypatch, count):
    """Mutating a valid count to zero/over-limit must prevent all work."""
    probe = Mock(side_effect=AssertionError("probe must not run"))
    monkeypatch.setattr(upload, "extract_metadata", probe)
    output = tmp_path / "output"
    with pytest.raises(upload.UploadError, match="Frame count"):
        upload.save_reference_video(b"video", "a.mp4", upload_dir=output, num_keyframes=count)
    with pytest.raises(upload.UploadError, match="Frame count"):
        upload.extract_keyframes_from_video(tmp_path / "a.mp4", output, count)
    with pytest.raises(analyzer.AnalysisError, match="Frame count"):
        analyzer.analyze_reference_video(tmp_path / "a.mp4", num_frames=count)
    assert not output.exists()
    probe.assert_not_called()


@pytest.mark.parametrize("count", [1, 12])
def test_count_boundaries_are_accepted(count):
    upload.validate_frame_count(count)


@pytest.mark.parametrize("unknown", ["N/A", None, "", "0"])
def test_unknown_nb_frames_estimates_from_finite_metadata(tmp_path, monkeypatch, unknown):
    video = tmp_path / "valid.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(upload, "_run_ffprobe", lambda _: {
        "streams": [{"codec_type": "video", "r_frame_rate": "30000/1001",
                     "nb_frames": unknown, "width": 640, "height": 480}],
        "format": {"duration": "10"},
    })
    result = upload.extract_metadata(video)
    upload.validate_metadata(result)
    assert result.frame_count == 299


@pytest.mark.parametrize("changes", [
    {"duration_seconds": 60.01}, {"duration_seconds": 0.49},
    {"duration_seconds": float("nan")}, {"duration_seconds": float("inf")},
    {"frame_rate": float("nan")}, {"frame_rate": float("inf")}, {"frame_rate": 0},
    {"width": -1}, {"width": 4097}, {"height": float("nan")},
    {"frame_count": -1},
])
def test_analyzer_metadata_guard_precedes_frames_and_llm(tmp_path, monkeypatch, changes):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(analyzer, "extract_metadata", lambda _: metadata(**changes))
    extract = Mock(side_effect=AssertionError("no extraction"))
    client = Mock(side_effect=AssertionError("no paid client"))
    monkeypatch.setattr(analyzer, "extract_keyframes_from_video", extract)
    monkeypatch.setattr(analyzer, "_build_llm_client", client)
    output = tmp_path / "frames"
    with pytest.raises(analyzer.AnalysisError, match="metadata"):
        analyzer.analyze_reference_video(video, output_dir=output)
    assert not output.exists()
    extract.assert_not_called()
    client.assert_not_called()


@pytest.mark.parametrize("duration", [0.5, 60.0])
def test_shared_duration_boundaries(duration):
    upload.validate_metadata(metadata(duration_seconds=duration))


@pytest.mark.parametrize("stage", ["extraction", "empty", "configuration", "frame", "synthesis", "success"])
@pytest.mark.parametrize("caller_owned", [False, True])
def test_owned_frames_cleaned_on_every_path(tmp_path, monkeypatch, stage, caller_owned):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(analyzer, "extract_metadata", lambda _: metadata())
    seen = []
    client = Mock()

    def extract(video_path, output_dir, num_keyframes):
        seen.append(output_dir)
        frame = output_dir / "keyframe_00.png"
        frame.write_bytes(b"fake-png")
        if stage == "extraction":
            raise RuntimeError("extraction")
        return [] if stage == "empty" else [str(frame)]

    def build_client():
        if stage == "configuration":
            raise analyzer.AnalysisError("configuration")
        return client, "fake-url", "fake-key", "fake-model"

    def analyze_frame(**kwargs):
        assert kwargs["image_path"].exists()
        if stage == "frame":
            raise analyzer.AnalysisError("frame")
        return SimpleNamespace()

    def synthesize(**kwargs):
        if stage == "synthesis":
            raise analyzer.AnalysisError("synthesis")
        return object(), {"fake": "script"}

    monkeypatch.setattr(analyzer, "extract_keyframes_from_video", extract)
    monkeypatch.setattr(analyzer, "_build_llm_client", build_client)
    monkeypatch.setattr(analyzer, "_analyze_frame", analyze_frame)
    monkeypatch.setattr(analyzer, "_synthesize_scene_script", synthesize)
    monkeypatch.setattr(analyzer, "_build_summary", lambda *args: object())
    output = tmp_path / "caller-frames" if caller_owned else None
    if stage == "success":
        result = analyzer.analyze_reference_video(video, num_frames=1, output_dir=output)
        assert result.num_frames_analyzed == 1
    else:
        with pytest.raises(analyzer.AnalysisError):
            analyzer.analyze_reference_video(video, num_frames=1, output_dir=output)
    assert len(seen) == 1
    assert seen[0].exists() is caller_owned
    if caller_owned:
        assert (seen[0] / "keyframe_00.png").exists()
    if stage in {"frame", "synthesis", "success"}:
        client.close.assert_called_once()


@pytest.fixture
def api_client(monkeypatch):
    # Isolated ASGI router: no application lifespan, DB, runtime, or provider setup.
    save = Mock(side_effect=AssertionError("save must not run"))
    analyze = Mock(side_effect=AssertionError("analysis must not run"))
    temporary = Mock(side_effect=AssertionError("temp file must not run"))
    monkeypatch.setattr(endpoint, "save_reference_video", save)
    monkeypatch.setattr(analyzer, "analyze_reference_video", analyze)
    monkeypatch.setattr(endpoint.tempfile, "NamedTemporaryFile", temporary)
    app = FastAPI()
    app.include_router(endpoint.router)
    with TestClient(app) as client:
        yield client
    save.assert_not_called()
    analyze.assert_not_called()
    temporary.assert_not_called()


@pytest.mark.parametrize("route,param", [
    ("analyze-reference", "num_frames"), ("upload-reference", "num_keyframes"),
])
@pytest.mark.parametrize("count", [0, -1, 13, 1000, "nope"])
def test_asgi_invalid_query_count_is_422_before_service(api_client, route, param, count):
    response = api_client.post(f"/scene-3d/{route}?{param}={count}",
                               files={"file": ("valid.mp4", b"video", "video/mp4")})
    assert response.status_code == 422


@pytest.mark.parametrize("route", ["analyze-reference", "upload-reference"])
def test_asgi_oversize_is_413_before_temp_or_service(api_client, monkeypatch, route):
    monkeypatch.setattr(endpoint, "MAX_FILE_SIZE_MB", 1)
    response = api_client.post(f"/scene-3d/{route}", files={
        "file": ("valid.mp4", b"x" * (1024 * 1024 + 1), "video/mp4"),
    })
    assert response.status_code == 413


@pytest.mark.parametrize("route", ["analyze-reference", "upload-reference"])
@pytest.mark.parametrize("name,mime,data", [
    ("invalid.exe", "video/mp4", b"video"),
    ("valid.mp4", "text/plain", b"video"), ("valid.mp4", "video/mp4", b""),
])
def test_asgi_invalid_upload_is_400_before_work(api_client, route, name, mime, data):
    response = api_client.post(f"/scene-3d/{route}", files={"file": (name, data, mime)})
    assert response.status_code == 400


def test_unknown_upload_size_reads_bounded_chunks_and_stops_at_first_excess(monkeypatch):
    monkeypatch.setattr(endpoint, "MAX_FILE_SIZE_MB", 1)
    upload_file = UploadFile(BytesIO(b"x" * (1024 * 1024 + 100)), filename="valid.mp4",
                             headers=Headers({"content-type": "video/mp4"}))
    original_read = upload_file.read
    reads = []

    async def bounded_read(size=-1):
        assert size > 0  # Locks out an accidental unbounded file.read().
        reads.append(size)
        return await original_read(size)

    upload_file.read = bounded_read
    with pytest.raises(HTTPException) as caught:
        asyncio.run(endpoint._read_reference_upload(upload_file))
    assert caught.value.status_code == 413
    assert reads == [1024 * 1024, 1]
    assert upload_file.file.tell() == 1024 * 1024 + 1


def test_bounded_reader_accepts_exact_limit(monkeypatch):
    monkeypatch.setattr(endpoint, "MAX_FILE_SIZE_MB", 1)
    data = b"x" * (1024 * 1024)
    file = UploadFile(BytesIO(data), filename="valid.mp4",
                      headers=Headers({"content-type": "video/mp4"}))
    assert asyncio.run(endpoint._read_reference_upload(file)) == data
