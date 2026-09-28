"""Endpoint-level tests: /scene-3d/dialogue-lipsync with apply_gestures=True."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _scene_script() -> dict:
    return {
        "scene": {
            "name": "gesture-endpoint",
            "environment": "indoor",
            "lighting": "neutral",
            "duration": 5,
            "frame_rate": 30,
        },
        "characters": [
            {
                "id": "char1",
                "type": "lowpoly_human",
                "appearance": {"color": "#8B4513", "height": 1.7, "scale": 1.0},
                "keyframes": [
                    {"frame": 0, "position": [0.0, 1.0, 0.0], "rotation_y": 0.0, "action": "stand"},
                ],
            }
        ],
        "props": [],
        "environment": [],
        "cameras": [],
        "shots": [],
        "speech_bindings": [],
    }


def test_dialogue_lipsync_apply_gestures_returns_gesture_facts(client) -> None:
    response = client.post(
        "/api/v1/scene-3d/dialogue-lipsync",
        json={
            "scene_script": _scene_script(),
            "dialogue_lines": [
                {"character_id": "char1", "text": "不，我不同意", "emotion": "angry", "start_time": 0.5}
            ],
            "apply_gestures": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    summary = body["summary"]
    assert summary["gesture_applied"] is True
    assert summary["gesture_keyframe_count"] > 0
    # The merged script carries gesture keyframes.
    chars = body["scene_script"]["characters"]
    assert any(kf["action"] == "gesture" for kf in chars[0]["keyframes"])


def test_dialogue_lipsync_without_gestures_is_default(client) -> None:
    response = client.post(
        "/api/v1/scene-3d/dialogue-lipsync",
        json={
            "scene_script": _scene_script(),
            "dialogue_lines": [
                {"character_id": "char1", "text": "不，我不同意", "emotion": "angry", "start_time": 0.5}
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["gesture_applied"] is False
    chars = body["scene_script"]["characters"]
    assert all(kf["action"] != "gesture" for kf in chars[0]["keyframes"])
