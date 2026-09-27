"""Unit tests for the image analyzer (image -> SceneScript blockout).

Covers panorama detection/slicing (pure cv2/numpy), input validation, the
mocked-LLM analysis + synthesis flow, fail-closed schema validation, and the
HTTP endpoint. No network: the multimodal LLM is monkeypatched.

See docs/plans/3d-workbench-and-pipeline-completion.md §3 (Q2).
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.scene3d import image_analyzer
from app.services.scene3d.image_analyzer import (
    AnalysisError,
    analyze_images,
    crop_equirect_faces,
    detect_panorama,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_panorama(path: Path, width: int = 1024, height: int = 512) -> Path:
    """Synthetic equirectangular panorama: gradient sky, floor band, a bright
    'door' front-center below the horizon, and a 'lamp' upper-left behind."""
    img = np.zeros((height, width, 3), np.uint8)
    for y in range(height):
        t = y / height
        img[y, :] = (int(120 * t), int(80 * (1 - t)), int(200 * t))
    img[height // 2 :, :, 1] = 90
    cv2.circle(img, (width // 2, int(height * 2 / 3)), 40, (0, 200, 255), -1)
    lamp_x = int((-2.4 / (2 * 3.14159265) + 0.5) * width) % width
    lamp_y = int((0.5 - 0.6 / 3.14159265) * height)
    cv2.circle(img, (lamp_x, lamp_y), 30, (255, 255, 255), -1)
    cv2.imwrite(str(path), img)
    return path


def _write_image(path: Path, width: int = 512, height: int = 512) -> Path:
    cv2.imwrite(str(path), np.full((height, width, 3), 60, np.uint8))
    return path


def _frame_analysis_json() -> str:
    return json.dumps(
        {
            "scene_type": "indoor",
            "environment_description": "concrete corridor with flickering lights",
            "lighting": "cool",
            "camera_angle": "eye-level",
            "shot_size": "wide",
            "camera_motion_hint": "static",
            "characters": [],
            "props": ["crate", "barrel"],
            "notable_elements": "steel door at the far end",
        }
    )


def _scene_script_dict(duration: float = 6.0) -> dict:
    return {
        "scene": {
            "name": "underground lab",
            "environment": "indoor",
            "lighting": "cool",
            "duration": duration,
            "frame_rate": 30,
        },
        "characters": [],
        "props": [
            {"id": "crate1", "type": "box", "position": [1.0, 2.0, 0.0], "scale": 1.0}
        ],
        "environment": [
            {"id": "wall1", "type": "wall", "position": [0.0, 5.0, 1.5], "scale": 1.0}
        ],
        "cameras": [
            {
                "id": "cam1",
                "shot_type": "wide",
                "keyframes": [
                    {"frame": 0, "position": [4.0, -6.0, 1.6], "look_at": [0.0, 0.0, 1.2]}
                ],
            }
        ],
        "shots": [
            {
                "id": "shot1",
                "camera": "cam1",
                "start_frame": 0,
                "end_frame": 999,  # deliberately wrong: the analyzer must pin it
                "description": "establishing wide",
            }
        ],
        "speech_bindings": [],
    }


class _FakeClient:
    def close(self) -> None:  # pragma: no cover - trivial
        pass


@pytest.fixture
def mocked_llm(monkeypatch):
    """Monkeypatch the LLM boundary: frame analysis + SceneScript synthesis.

    Returns a setter to override the synthesis payload for failure tests.
    """
    calls: list[dict] = []
    synthesis_payload = {"json": _scene_script_dict()}

    def fake_call(*, client, base_url, api_key, model, system_prompt, user_text, image_path, max_tokens):
        calls.append(
            {
                "has_image": image_path is not None,
                "system": system_prompt,
                "user": user_text,
            }
        )
        if image_path is not None:
            return _frame_analysis_json()
        return json.dumps(synthesis_payload["json"])

    monkeypatch.setattr(image_analyzer, "_call_multimodal_llm", fake_call)
    monkeypatch.setattr(
        image_analyzer,
        "_build_llm_client",
        lambda: (_FakeClient(), "http://llm.test", "key", "test-model"),
    )
    return calls, synthesis_payload


# ---------------------------------------------------------------------------
# Panorama detection
# ---------------------------------------------------------------------------


def test_detect_panorama_equirect(tmp_path) -> None:
    info = detect_panorama(_write_panorama(tmp_path / "pano.png"))
    assert info.is_panorama is True
    assert (info.width, info.height) == (1024, 512)


def test_detect_panorama_rejects_non_panorama_shapes(tmp_path) -> None:
    assert detect_panorama(_write_image(tmp_path / "square.png")).is_panorama is False
    # 2:1 but too narrow to slice usefully
    small = tmp_path / "small.png"
    cv2.imwrite(str(small), np.zeros((256, 512, 3), np.uint8))
    assert detect_panorama(small).is_panorama is False


# ---------------------------------------------------------------------------
# Cubemap slicing (mutation-locked orientation)
# ---------------------------------------------------------------------------


def test_crop_equirect_faces_produces_six_oriented_faces(tmp_path) -> None:
    pano = _write_panorama(tmp_path / "pano.png")
    faces = crop_equirect_faces(pano, tmp_path / "faces", face_size=256)

    assert sorted(faces) == ["nx", "ny", "nz", "px", "py", "pz"]
    for path in faces.values():
        image = cv2.imread(path)
        assert image is not None
        assert image.shape[:2] == (256, 256)

    # The 'door' sits front-center below the horizon: it must land near the
    # horizontal center of the +Z face and in its BOTTOM half. A flipped
    # vertical mapping fails this assertion (mutation check).
    front = cv2.cvtColor(cv2.imread(faces["pz"]), cv2.COLOR_BGR2GRAY)
    y, x = np.unravel_index(int(np.argmax(front)), front.shape)
    assert abs(x - 128) < 25
    assert y > 140

    # The 'lamp' sits above the horizon in the -X hemisphere: it must appear
    # in the -X face, in the upper half.
    left = cv2.cvtColor(cv2.imread(faces["nx"]), cv2.COLOR_BGR2GRAY)
    y2, x2 = np.unravel_index(int(np.argmax(left)), left.shape)
    assert y2 < 128


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_validate_rejects_empty_list() -> None:
    with pytest.raises(AnalysisError) as exc:
        analyze_images([])
    assert exc.value.error_type == "input"


def test_validate_rejects_too_many_images(tmp_path) -> None:
    paths = [_write_image(tmp_path / f"i{i}.png") for i in range(7)]
    with pytest.raises(AnalysisError) as exc:
        analyze_images(paths)
    assert exc.value.error_type == "input"


def test_validate_rejects_bad_format_and_missing_files(tmp_path) -> None:
    bad_ext = tmp_path / "note.txt"
    bad_ext.write_text("x")
    with pytest.raises(AnalysisError) as exc:
        analyze_images([bad_ext])
    assert exc.value.error_type == "invalid_format"

    with pytest.raises(AnalysisError) as exc:
        analyze_images([tmp_path / "missing.png"])
    assert exc.value.error_type == "input"

    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    with pytest.raises(AnalysisError) as exc:
        analyze_images([empty])
    assert exc.value.error_type == "invalid_size"


def test_validate_rejects_out_of_range_duration(tmp_path) -> None:
    with pytest.raises(AnalysisError) as exc:
        analyze_images([_write_image(tmp_path / "a.png")], duration_seconds=0)
    assert exc.value.error_type == "input"


# ---------------------------------------------------------------------------
# Analysis flow (mocked LLM)
# ---------------------------------------------------------------------------


def test_analyze_images_single_image_produces_scene_script(tmp_path, mocked_llm) -> None:
    calls, _payload = mocked_llm
    result = analyze_images([_write_image(tmp_path / "scene.png")])

    # SceneScript validated against the Pydantic schema.
    assert result.scene_script.scene.name == "underground lab"
    assert len(result.scene_script.props) == 1
    assert len(result.scene_script.environment) == 1
    assert len(result.scene_script.cameras) == 1

    # Requested duration and shot frame range are pinned even though the LLM
    # drifted (shot end_frame was 999 in the fixture).
    assert result.scene_script.scene.duration == 6.0
    assert result.scene_script.total_frames == 180
    assert result.scene_script.shots[0].end_frame == 179

    # One image-analysis call + one synthesis call; no panorama handling.
    assert len(calls) == 2
    assert calls[0]["has_image"] is True
    assert calls[1]["has_image"] is False
    assert result.panorama_image_indices == []
    assert result.warnings == []
    assert result.image_analyses[0].scene_type == "indoor"
    assert result.summary.characters_summary == "No characters detected"


def test_analyze_images_duration_override(tmp_path, mocked_llm) -> None:
    result = analyze_images(
        [_write_image(tmp_path / "scene.png")],
        duration_seconds=4.5,
        scene_name="lab-b2",
    )
    assert result.scene_script.scene.duration == 4.5
    assert result.scene_script.total_frames == 135
    # The scene name hint is forwarded to the synthesizer.
    assert "lab-b2" in mocked_llm[0][1]["user"]


def test_analyze_images_panorama_slices_to_cubemap(tmp_path, mocked_llm) -> None:
    calls, _payload = mocked_llm
    result = analyze_images([_write_panorama(tmp_path / "pano.png")])

    assert result.panorama_image_indices == [0]
    assert len(result.analyzed_image_paths) == 6  # 4 horizontal + top + bottom
    assert any("panorama_sliced_to_cubemap" in w for w in result.warnings)
    # Six image analyses + one synthesis.
    assert len(calls) == 7


def test_analyze_images_panorama_hint_degrades_with_warning(tmp_path, mocked_llm) -> None:
    result = analyze_images(
        [_write_image(tmp_path / "square.png")],
        panorama=True,
    )
    assert result.panorama_image_indices == []
    assert len(result.analyzed_image_paths) == 1
    assert any("panorama_hint_ignored" in w for w in result.warnings)


def test_analyze_images_normalizes_scale_arrays(tmp_path, mocked_llm) -> None:
    # LLMs habitually emit scale as [1,1,1]; the shared normalizer must fix it.
    script = _scene_script_dict()
    script["props"][0]["scale"] = [1, 1, 1]
    script["environment"][0]["scale"] = 1.5
    mocked_llm[1]["json"] = script
    result = analyze_images([_write_image(tmp_path / "scene.png")])
    assert result.scene_script.props[0].scale == 1.0
    assert result.scene_script.environment[0].scale == 1.5


def test_analyze_images_schema_failure_fails_closed(tmp_path, mocked_llm) -> None:
    # A synthesis payload with an unknown prop type must raise, never return
    # a half-valid scene.
    script = _scene_script_dict()
    script["props"][0]["type"] = "spaceship"
    mocked_llm[1]["json"] = script
    with pytest.raises(AnalysisError) as exc:
        analyze_images([_write_image(tmp_path / "scene.png")])
    assert exc.value.error_type == "schema_validation"


def test_analyze_images_propagates_llm_error(tmp_path, monkeypatch) -> None:
    def boom(**_kwargs):
        raise AnalysisError("LLM HTTP 500", error_type="llm_error")

    monkeypatch.setattr(image_analyzer, "_call_multimodal_llm", boom)
    monkeypatch.setattr(
        image_analyzer,
        "_build_llm_client",
        lambda: (_FakeClient(), "http://llm.test", "key", "test-model"),
    )
    with pytest.raises(AnalysisError) as exc:
        analyze_images([_write_image(tmp_path / "scene.png")])
    assert exc.value.error_type == "llm_error"


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def http_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    return TestClient(app)


def _png_bytes(width: int = 512, height: int = 512) -> bytes:
    ok, encoded = cv2.imencode(".png", np.full((height, width, 3), 60, np.uint8))
    assert ok
    return encoded.tobytes()


@pytest.mark.integration
def test_endpoint_analyze_image_returns_scene_script(http_client, mocked_llm) -> None:
    response = http_client.post(
        "/scene-3d/analyze-image",
        files=[("files", ("scene.png", _png_bytes(), "image/png"))],
        data={"user_description": "地下研究所走廊"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["scene_script"]["scene"]["name"] == "underground lab"
    assert body["image_count"] == 1
    assert body["analyzed_image_count"] == 1
    assert len(body["image_analyses"]) == 1


@pytest.mark.integration
def test_endpoint_analyze_image_panorama_reports_faces(http_client, mocked_llm) -> None:
    ok, encoded = cv2.imencode(".png", _read_panorama_array())
    assert ok
    response = http_client.post(
        "/scene-3d/analyze-image",
        files=[("files", ("pano.png", encoded.tobytes(), "image/png"))],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["panorama_image_indices"] == [0]
    assert body["analyzed_image_count"] == 6
    assert any("panorama_sliced_to_cubemap" in w for w in body["warnings"])


@pytest.mark.integration
def test_endpoint_analyze_image_rejects_empty_upload(http_client) -> None:
    response = http_client.post(
        "/scene-3d/analyze-image",
        files=[("files", ("empty.png", b"", "image/png"))],
    )
    assert response.status_code == 400


@pytest.mark.integration
def test_endpoint_analyze_image_rejects_missing_files(http_client) -> None:
    response = http_client.post("/scene-3d/analyze-image")
    assert response.status_code == 422


@pytest.mark.integration
def test_endpoint_analyze_image_surfaces_analysis_error(http_client, monkeypatch) -> None:
    def boom(**_kwargs):
        raise AnalysisError("LLM not configured", error_type="configuration")

    monkeypatch.setattr(image_analyzer, "_call_multimodal_llm", boom)
    monkeypatch.setattr(
        image_analyzer,
        "_build_llm_client",
        lambda: (_FakeClient(), "http://llm.test", "key", "test-model"),
    )
    response = http_client.post(
        "/scene-3d/analyze-image",
        files=[("files", ("scene.png", _png_bytes(), "image/png"))],
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error_type"] == "configuration"


def _read_panorama_array() -> np.ndarray:
    height, width = 512, 1024
    img = np.zeros((height, width, 3), np.uint8)
    for y in range(height):
        t = y / height
        img[y, :] = (int(120 * t), int(80 * (1 - t)), int(200 * t))
    img[height // 2 :, :, 1] = 90
    cv2.circle(img, (width // 2, int(height * 2 / 3)), 40, (0, 200, 255), -1)
    return img
