"""Endpoint tests: /scene-3d/language-fallback (SceneLanguageBuilder AI fallback).

The deterministic keyword map misses a sentence -> the endpoint escalates it
to the white-model LLM ops path. Contract under lock: the applied script comes
back only through the gate; coded failures (invalid script, unconfigured LLM,
gate violations) come back as success=false with an error_code — never a dead
end, never a trusted script.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.core.config as config_module
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _scene_script() -> dict:
    return {
        "scene": {
            "name": "language-fallback",
            "environment": "indoor",
            "lighting": "neutral",
            "duration": 5,
            "frame_rate": 30,
        },
        "characters": [],
        "props": [],
        "environment": [],
        "cameras": [
            {
                "id": "cam1",
                "shot_type": "wide",
                "keyframes": [{"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]}],
            }
        ],
        "shots": [{"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 149}],
        "speech_bindings": [],
    }


def _patch_settings(monkeypatch, **overrides) -> None:
    from app.core.config import Settings

    payload = {"llm_api_key": "test-key", "llm_base_url": "https://llm.test"}
    payload.update(overrides)
    monkeypatch.setattr(config_module, "get_settings", lambda: Settings(**payload))


def test_invalid_scene_script_is_a_coded_failure(client, monkeypatch) -> None:
    _patch_settings(monkeypatch)
    response = client.post(
        "/api/v1/scene-3d/language-fallback",
        json={"scene_script": {"scene": "not-a-script"}, "text": "铺一张波斯地毯"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "scene_script_invalid"


def test_unconfigured_llm_returns_coded_failure(client, monkeypatch) -> None:
    _patch_settings(monkeypatch, llm_api_key=None, llm_base_url=None)
    response = client.post(
        "/api/v1/scene-3d/language-fallback",
        json={"scene_script": _scene_script(), "text": "铺一张波斯地毯"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "white_model_llm_unconfigured"


def test_success_applies_llm_ops_through_the_real_gate(client, monkeypatch) -> None:
    from app.services.scene3d.scene_script_tool_service import SceneScriptToolService
    from app.services.scene3d.white_model_generator import WhiteModelOpsGenerator

    def fake_generate(self, *, description, base_script=None):
        # Real gate, fake LLM: the batch still has to pass all-or-nothing.
        result = SceneScriptToolService().apply_operations(
            base_script, [{"op": "add_prop", "type": "vase", "position": [1.5, 0, 0]}]
        )
        report = {
            "applied": result.applied,
            "warnings": result.warnings,
            "mcp_results": result.mcp_results,
            "operation_count": 1,
        }
        return result.scene_script, report

    monkeypatch.setattr(WhiteModelOpsGenerator, "generate", fake_generate)
    _patch_settings(monkeypatch)

    response = client.post(
        "/api/v1/scene-3d/language-fallback",
        json={"scene_script": _scene_script(), "text": "在角落放一个青瓷花瓶"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["operation_count"] == 1
    assert body["applied_scene_script"]["props"][0]["type"] == "vase"


def test_gate_rejection_carries_violations(client, monkeypatch) -> None:
    from app.services.scene3d.white_model_generator import (
        WhiteModelGenerationError,
        WhiteModelOpsGenerator,
    )

    def rejecting_generate(self, *, description, base_script=None):
        raise WhiteModelGenerationError(
            "scene_operations_invalid",
            "the batch was rejected",
            violations=[{"index": 0, "code": "object_type_unsupported"}],
        )

    monkeypatch.setattr(WhiteModelOpsGenerator, "generate", rejecting_generate)
    _patch_settings(monkeypatch)

    response = client.post(
        "/api/v1/scene-3d/language-fallback",
        json={"scene_script": _scene_script(), "text": "加一艘飞船"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "scene_operations_invalid"
    assert body["violations"][0]["code"] == "object_type_unsupported"
