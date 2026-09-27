"""Unit tests for single-image depth extraction (white model).

The MiDaS model and per-frame estimator are faked (torch is heavy): the tests
lock the service's file IO, downscaling, result shape, and the endpoint's
contract (dependency report, multipart handling, media-dir serving).
"""

from __future__ import annotations

import pytest

from app.services.scene3d.depth_estimator import (
    DepthEstimationError,
    estimate_depth_from_image,
)


@pytest.fixture
def fake_depth_stack(monkeypatch):
    """Fake MiDaS model/transform/estimator so no torch is needed."""

    import app.services.scene3d.depth_estimator as de

    monkeypatch.setattr(de, "load_midas_model", lambda model_type: (object(), object()))
    monkeypatch.setattr(
        de,
        "estimate_depth_frame",
        lambda frame, model, transform, device, colormap: frame[:, :, :1].repeat(3, axis=2),
    )
    return de


def _write_image(path, width: int = 400, height: int = 300):
    import cv2
    import numpy as np

    image = np.full((height, width, 3), 90, dtype="uint8")
    cv2.imwrite(str(path), image)
    return path


def test_estimate_depth_from_image_writes_png(tmp_path, fake_depth_stack) -> None:
    image = _write_image(tmp_path / "pano.png", 800, 400)

    result = estimate_depth_from_image(image, output_dir=tmp_path / "out")

    assert result.frame_count == 1
    assert (tmp_path / "out" / f"{result.asset_id}.png").exists()
    assert result.output_width == 800  # under the cap: no downscale
    assert result.output_height == 400


def test_estimate_depth_from_image_downscales_panoramas(tmp_path, fake_depth_stack) -> None:
    image = _write_image(tmp_path / "big.png", 4096, 2048)

    result = estimate_depth_from_image(image, output_dir=tmp_path / "out", max_dimension=1280)

    assert result.output_width == 1280  # long side capped for inference
    assert result.output_height == 640


def test_estimate_depth_from_image_missing_file(tmp_path, fake_depth_stack) -> None:
    with pytest.raises(DepthEstimationError) as exc:
        estimate_depth_from_image(tmp_path / "nope.png")
    assert exc.value.error_type == "file_not_found"


def test_estimate_depth_image_endpoint_serves_from_media_dir(tmp_path, monkeypatch) -> None:
    import cv2
    import numpy as np
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint
    import app.services.scene3d.depth_estimator as de

    monkeypatch.setattr(de, "load_midas_model", lambda model_type: (object(), object()))
    monkeypatch.setattr(
        de,
        "estimate_depth_frame",
        lambda frame, model, transform, device, colormap: frame[:, :, :1].repeat(3, axis=2),
    )
    monkeypatch.setattr(
        de,
        "check_dependencies",
        lambda: {"torch": True, "opencv": True, "numpy": True, "timm": True, "ffmpeg": True},
    )

    ok, encoded = cv2.imencode(".png", np.full((200, 400, 3), 60, dtype="uint8"))
    assert ok

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    response = client.post(
        "/scene-3d/extract-depth-image",
        files={"file": ("pano.png", encoded.tobytes(), "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["depth_url"].startswith("/media/assets/provider-output/depth/")
    assert body["width"] == 400


def test_estimate_depth_image_endpoint_reports_missing_dependencies(tmp_path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint
    import app.services.scene3d.depth_estimator as de

    monkeypatch.setattr(
        de,
        "check_dependencies",
        lambda: {"torch": False, "opencv": True, "numpy": True, "timm": False, "ffmpeg": True},
    )

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    response = client.post(
        "/scene-3d/extract-depth-image",
        files={"file": ("pano.png", b"fake", "image/png")},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error_type"] == "missing_dependency"
    assert detail["dependencies"]["torch"] is False
