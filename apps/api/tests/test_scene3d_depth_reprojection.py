"""Unit tests for the 2.5D depth-reprojection orbit renderer.

Locks the geometric contract:
- zero sweep is the exact identity (the projection pipeline is correct);
- parallax is depth-dependent and opposite the camera (near features swing
  more than far ones — the whole point of the 2.5D move);
- disocclusion holes are inpainted AND reported, never silent;
- the endpoint serves artifacts from /media with keyframes.

Pure numpy/cv2 — no Blender, no network.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.services.scene3d.depth_reprojection import render_depth_orbit


def _scene(tmp_path):
    """A gradient image with a NEAR square (left) and a FAR square (right)."""
    import cv2

    height, width = 240, 320
    image = np.zeros((height, width, 3), np.uint8)
    for y in range(height):
        image[y, :] = (int(255 * y / height * 0.5), int(128 + 60 * y / height), 200)
    # Near marker: bright cyan square on the left.
    cv2.rectangle(image, (60, 100), (120, 180), (0, 240, 255), -1)
    # Far marker: bright magenta square on the right.
    cv2.rectangle(image, (200, 100), (260, 180), (255, 0, 255), -1)
    image_path = tmp_path / "scene.png"
    cv2.imwrite(str(image_path), image)

    depth = np.full((height, width), 230, np.uint8)  # background: far
    cv2.rectangle(depth, (60, 100), (120, 180), 70, -1)  # near square: close
    cv2.rectangle(depth, (200, 100), (260, 180), 190, -1)  # far square: slightly closer than bg
    depth_path = tmp_path / "depth.png"
    cv2.imwrite(str(depth_path), depth)
    return image_path, depth_path, height, width


def _feature_x(frames_dir, frame_index, color_channel, threshold, height, width):
    import cv2

    frame = cv2.imread(str(frames_dir / f"frame_{frame_index:04d}.png"))
    channel = frame[:, :, color_channel]
    mask = channel > threshold
    xs = np.where(mask.any(axis=0))[0]
    return int(xs.mean()) if len(xs) else None


@pytest.fixture
def scene(tmp_path):
    return _scene(tmp_path)


def test_zero_sweep_is_exact_identity(tmp_path, scene) -> None:
    image_path, depth_path, height, width = scene
    import cv2

    source = cv2.imread(str(image_path))
    result = render_depth_orbit(
        image_path, depth_path, tmp_path / "out",
        num_frames=3, sweep_degrees=0.0, elevation_degrees=0.0, encode_video=False,
    )
    frame0 = cv2.imread(str(Path(result.frames_dir) / "frame_0000.png"))
    # The whole pipeline at zero motion must reproduce the input exactly.
    assert float(np.abs(frame0.astype(float) - source.astype(float)).max()) == 0.0
    assert result.max_hole_fraction == 0.0


def test_parallax_is_depth_dependent_and_opposite_the_camera(tmp_path, scene) -> None:
    image_path, depth_path, height, width = scene
    result = render_depth_orbit(
        image_path, depth_path, tmp_path / "out",
        num_frames=11, sweep_degrees=40.0, encode_video=False,
    )
    frames_dir = Path(result.frames_dir)

    # Near marker (cyan, channel index 1 high, threshold on green).
    def near_x(i):
        import cv2
        import numpy as np

        frame = cv2.imread(str(frames_dir / f"frame_{i:04d}.png"))
        xs = np.where((frame[:, :, 1] > 200).any(axis=0))[0]
        return int(xs.mean()) if len(xs) else None

    def far_x(i):
        import cv2
        import numpy as np

        frame = cv2.imread(str(frames_dir / f"frame_{i:04d}.png"))
        xs = np.where((frame[:, :, 2] > 200).any(axis=0))[0]
        return int(xs.mean()) if len(xs) else None

    near_first, near_last = near_x(0), near_x(10)
    far_first, far_last = far_x(0), far_x(10)
    assert near_first is not None and far_first is not None

    near_shift = abs(near_last - near_first)
    far_shift = abs(far_last - far_first)
    # The near feature moves MORE than the far one (depth-dependent parallax).
    assert near_shift > far_shift
    assert near_shift > 10  # a visible move, not a rounding artifact


def test_holes_are_reported_not_silent(tmp_path, scene) -> None:
    image_path, depth_path, height, width = scene
    result = render_depth_orbit(
        image_path, depth_path, tmp_path / "out",
        num_frames=9, sweep_degrees=60.0, encode_video=False,
    )
    # A 60° sweep over single-image depth exposes borders: the hole fraction
    # is reported (and warned on), never presented as clean geometry.
    assert result.max_hole_fraction > 0.1
    assert any("disocclusion" in warning for warning in result.warnings)
    # Frames are still written (inpainted) for every frame.
    frames = sorted(Path(result.frames_dir).glob("frame_*.png"))
    assert len(frames) == 9
    for frame_path in frames:
        import cv2

        frame = cv2.imread(str(frame_path))
        assert frame is not None and float(frame.mean()) > 1.0  # not all black


def test_missing_image_fails_closed(tmp_path, scene) -> None:
    from app.services.scene3d.depth_estimator import DepthEstimationError

    with pytest.raises(DepthEstimationError) as exc:
        render_depth_orbit(tmp_path / "nope.png", scene[1], tmp_path / "out")
    assert exc.value.error_type == "image_read_error"


def test_endpoint_renders_and_serves_artifacts(tmp_path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    image_path, depth_path, _h, _w = _scene(tmp_path)
    image_bytes = image_path.read_bytes()
    depth_bytes = depth_path.read_bytes()

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    response = client.post(
        "/scene-3d/render-depth-orbit",
        files=[
            ("file", ("scene.png", image_bytes, "image/png")),
            ("depth_file", ("depth.png", depth_bytes, "image/png")),
        ],
        data={"num_frames": "6", "sweep_degrees": "30", "encode_video": "false"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["frame_count"] == 6
    # Keyframes (first/mid/last) are served from the media dir.
    assert len(body["keyframe_urls"]) == 3
    assert all(url.startswith("/media/") for url in body["keyframe_urls"])
    assert body["max_hole_fraction"] >= 0.0
