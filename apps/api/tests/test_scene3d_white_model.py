"""Unit tests for the white-model ops generator and executor wiring.

The generator's contract: LLM output is a batch of OPS that must pass the
same SceneScriptToolService gate the workbench uses — never a trusted
script. Tests cover the happy path (mocked LLM emitting a fenced batch),
unparseable output, a batch the gate rejects (violations carried), the
missing-LLM config, and the executor's white-model branch (report published
on the node; missing generator fails loudly instead of silently falling
back to the classic path).
"""

from __future__ import annotations

import json

import pytest

from app.core.config import Settings
from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.white_model_generator import (
    WhiteModelGenerationError,
    WhiteModelOpsGenerator,
)

_VALID_BATCH = {
    "operations": [
        {"op": "add_environment", "type": "floor", "position": [0, 0, 0], "scale": 8.0},
        {"op": "add_environment", "type": "wall", "position": [0, 4, 1.5]},
        {"op": "add_character", "position": [0, 1, 0], "color": "#E74C3C"},
    ]
}


def _llm_settings(**overrides) -> Settings:
    payload = {
        "agent_runtime_mode": "real",
        "llm_api_key": "test-key",
        "llm_base_url": "https://llm.test",
    }
    payload.update(overrides)
    return Settings(**payload)


def _client_returning(content: str, *, status: int = 200):
    import httpx

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def post(self, *args, **kwargs):
            return httpx.Response(
                status,
                json={"choices": [{"message": {"content": content}}]},
                request=httpx.Request("POST", "https://llm.test/chat/completions"),
            )

        def close(self):
            pass

    return _Client


def test_generate_applies_ops_through_the_tool_service() -> None:
    content = "```json\n" + json.dumps(_VALID_BATCH) + "\n```"
    generator = WhiteModelOpsGenerator(
        _llm_settings(), client_factory=_client_returning(content)
    )

    script, report = generator.generate(description="一个 8 米长的地下走廊")

    # The starter script (no objects) became a built-out scene.
    assert [obj.type for obj in script.environment] == ["floor", "wall"]
    assert len(script.characters) == 1
    assert report["operation_count"] == 3
    assert len(report["applied"]) == 3


def test_generate_on_a_base_script_references_existing_ids() -> None:
    batch = {
        "operations": [
            {"op": "add_environment", "type": "door", "position": [0, 3.9, 0]},
            {"op": "move_object", "kind": "environment", "id": "env_1", "position": [0, 2, 0]},
        ]
    }
    generator = WhiteModelOpsGenerator(
        _llm_settings(), client_factory=_client_returning(json.dumps(batch))
    )

    base = SceneScriptRoot.model_validate(
        {
            "scene": {"name": "b", "environment": "indoor", "lighting": "cool", "duration": 6, "frame_rate": 30},
            "characters": [], "props": [], "environment": [],
            "cameras": [{"id": "cam1", "shot_type": "wide", "keyframes": [{"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]}]}],
            "shots": [{"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 179}],
            "speech_bindings": [],
        }
    )
    script, _report = generator.generate(description="在尽头加一道门并前移", base_script=base)
    assert script.environment[0].position == [0, 2, 0]


def test_unparseable_output_fails_closed() -> None:
    generator = WhiteModelOpsGenerator(
        _llm_settings(), client_factory=_client_returning("not json at all")
    )
    with pytest.raises(WhiteModelGenerationError) as exc:
        generator.generate(description="scene")
    assert exc.value.code == "white_model_operations_unparseable"


def test_trailing_comma_output_is_salvaged() -> None:
    # 2026-09-29 live failure mode (one character from valid): the local
    # salvage pass repairs it instead of failing the whole generation.
    content = '{"operations": [{"op": "add_prop", "type": "cup", "position": [0, 0, 0]},]}'
    generator = WhiteModelOpsGenerator(
        _llm_settings(), client_factory=_client_returning(content)
    )
    script, _report = generator.generate(description="桌上放一个杯子")
    assert [prop.type for prop in script.props] == ["cup"]


def test_gate_rejection_carries_violations() -> None:
    # A batch naming a non-existent enum type: the tool service rejects it.
    batch = {"operations": [{"op": "add_prop", "type": "spaceship", "position": [0, 0, 0]}]}
    generator = WhiteModelOpsGenerator(
        _llm_settings(), client_factory=_client_returning(json.dumps(batch))
    )
    with pytest.raises(WhiteModelGenerationError) as exc:
        generator.generate(description="scene")
    assert exc.value.code == "scene_operations_invalid"
    assert exc.value.violations[0]["code"] == "object_type_unsupported"


def test_missing_llm_config_fails_closed() -> None:
    generator = WhiteModelOpsGenerator(_llm_settings(llm_api_key=None))
    with pytest.raises(WhiteModelGenerationError) as exc:
        generator.generate(description="scene")
    assert exc.value.code == "white_model_llm_unconfigured"


def test_prompt_type_lists_match_the_schema() -> None:
    # The prompt's type lists are built from the schema enums (single source):
    # the prompt must teach exactly the types the apply-operations gate
    # accepts — no more (gate rejections), no fewer (silent capability loss).
    from typing import get_args

    from app.schemas.scene_script import EnvironmentType, PropType
    from app.services.scene3d.white_model_generator import _WHITE_MODEL_SYSTEM_PROMPT

    def types_after_hash(line: str) -> set[str]:
        return set(line.split("# ")[1].split("|"))

    environment_line = next(
        line for line in _WHITE_MODEL_SYSTEM_PROMPT.splitlines() if "add_environment" in line
    )
    prop_line = next(
        line for line in _WHITE_MODEL_SYSTEM_PROMPT.splitlines() if '"add_prop"' in line
    )
    assert types_after_hash(environment_line) == set(get_args(EnvironmentType))
    assert types_after_hash(prop_line) == set(get_args(PropType))
    assert "__PROP_TYPES__" not in _WHITE_MODEL_SYSTEM_PROMPT
    assert "__ENVIRONMENT_TYPES__" not in _WHITE_MODEL_SYSTEM_PROMPT


def test_empty_description_fails_closed() -> None:
    generator = WhiteModelOpsGenerator(
        _llm_settings(), client_factory=_client_returning("{}")
    )
    with pytest.raises(WhiteModelGenerationError) as exc:
        generator.generate(description="   ")
    assert exc.value.code == "white_model_description_required"


# ---------------------------------------------------------------------------
# Executor wiring
# ---------------------------------------------------------------------------


class _FakeWhiteModelGenerator:
    def __init__(self, script: SceneScriptRoot) -> None:
        self._script = script
        self.calls: list[dict] = []

    def generate(self, *, description: str, base_script=None):
        self.calls.append({"description": description, "base_script": base_script})
        return self._script, {"applied": [{"index": 0, "op": "add_environment"}], "operation_count": 1}


class _RaisingWhiteModelGenerator:
    def generate(self, *, description: str, base_script=None):
        raise WhiteModelGenerationError("white_model_llm_failed", "LLM said no")


def _white_model_node() -> object:
    """A scene-3d node requesting white-model mode (no stored script)."""

    from app.schemas.agent_canvas import CanvasNodeV2

    node = CanvasNodeV2.model_validate(
        {
            "node_id": "node-wm",
            "workflow_id": "wf-1",
            "node_type": "scene-3d",
            "creative_role": "scene_3d_previs",
            "role_contract_version": "ad-media-role-v1",
            "title": "white model node",
            "status": "draft",
            "summary_prompt": None,
            "generation_prompt": "地下研究所走廊",
            "structured_content": {"white_model": True},
            "parameters": {},
            "prompt_context_snapshot_id": None,
            "output_asset_id": None,
            "position": {"x": 0, "y": 0},
            "revision": 1,
            "error": None,
            "created_at": "2026-09-26T00:00:00Z",
            "updated_at": "2026-09-26T00:00:00Z",
        }
    )
    return node


def _executor(**overrides):
    from pathlib import Path

    from app.services.agent_canvas_node_execution import Scene3DNodeExecutor

    params = {
        "capability_probe": lambda: type("Cap", (), {"state": "ready", "version": "5.0", "executable": "blender", "error": None})(),
        "renderer": lambda script, frames_dir, timeout_seconds=1800, include_control_passes=False, keyframes_only=True: type(
            "R", (), {"success": True, "frame_count": 5, "error": None, "blender_version": "5.0", "degraded_assets": (), "rendered_frames": "keyframes"}
        )(),
        # The encoder must leave a real file: the executor reads the bytes back
        # after the fake encode succeeds (same contract as the real one).
        "encoder": lambda input_dir, output_path, fps=30: (
            Path(output_path).write_bytes(b"\x00\x00\x00\x18ftypmp42fake"),
            type("E", (), {"success": True, "error": None})(),
        )[1],
    }
    params.update(overrides)
    return Scene3DNodeExecutor(Settings(agent_runtime_mode="fake"), **params)


def test_executor_white_model_branch_publishes_report() -> None:
    script = SceneScriptRoot.model_validate(
        {
            "scene": {"name": "wm", "environment": "indoor", "lighting": "cool", "duration": 6, "frame_rate": 30},
            "characters": [],
            "props": [],
            "environment": [{"id": "env_1", "type": "wall", "position": [0, 4, 0], "scale": 1.0}],
            "cameras": [{"id": "cam1", "shot_type": "wide", "keyframes": [{"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]}]}],
            "shots": [{"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 179}],
            "speech_bindings": [],
        }
    )
    fake = _FakeWhiteModelGenerator(script)
    executor = _executor(white_model_generator=fake)

    from app.services.agent_canvas_node_execution import NodeExecutionContext

    context = NodeExecutionContext(execution_id="exec-1", node=_white_model_node(), inputs=())
    outcome = executor(context)

    assert fake.calls and fake.calls[0]["description"] == "地下研究所走廊"
    assert outcome.structured_content["white_model_report"]["operation_count"] == 1
    assert outcome.structured_content["scene_script"]["environment"][0]["id"] == "env_1"


def test_executor_white_model_without_generator_fails_loudly() -> None:
    from app.services.agent_canvas_node_execution import NodeExecutionContext
    from app.persistence.errors import V2PersistenceError

    executor = _executor()  # no white_model_generator injected
    context = NodeExecutionContext(execution_id="exec-1", node=_white_model_node(), inputs=())
    with pytest.raises(V2PersistenceError) as exc:
        executor(context)
    assert exc.value.code == "white_model_generator_missing"


def test_executor_white_model_generator_error_is_coded() -> None:
    from app.services.agent_canvas_node_execution import NodeExecutionContext
    from app.persistence.errors import V2PersistenceError

    executor = _executor(white_model_generator=_RaisingWhiteModelGenerator())
    context = NodeExecutionContext(execution_id="exec-1", node=_white_model_node(), inputs=())
    with pytest.raises(V2PersistenceError) as exc:
        executor(context)
    assert exc.value.code == "white_model_llm_failed"
