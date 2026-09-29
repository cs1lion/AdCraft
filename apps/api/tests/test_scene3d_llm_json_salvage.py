"""Salvage for common LLM structured-output breakage (2026-09-29 live).

The scene-script path died on two flakes: a trailing comma in otherwise
valid JSON, and a reasoning model burning its whole budget on reasoning and
returning an empty message.  Both are salvaged locally now: repair the JSON
text and re-validate before spending anything, and turn an empty message
into a named deterministic draft instead of a dead end.
"""

from __future__ import annotations

import copy
import json

import pytest

from app.services.scene3d.llm_json_salvage import prune_extra_fields, salvage_json_text
from app.services.scene3d.parser import parse_llm_output
from app.services.scene3d.scene_script_generator import LLMSceneScriptGenerator

VALID_SCENE_SCRIPT = {
    "scene": {
        "name": "salvage-scene",
        "environment": "indoor",
        "lighting": "warm",
        "duration": 4.0,
        "frame_rate": 30,
    },
    "characters": [],
    "props": [],
    "environment": [],
    "cameras": [
        {
            "id": "cam1",
            "shot_type": "wide",
            "keyframes": [{"frame": 0, "position": [0, -3, 1.6], "look_at": [0, 0, 0.4]}],
        }
    ],
    "shots": [{"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 60}],
}


def _wrap(payload: dict) -> str:
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


class TestSalvageJsonText:
    def test_repairs_trailing_commas(self) -> None:
        assert json.loads(salvage_json_text('{"a": 1, "b": [1, 2, ], }') or "null") == {
            "a": 1,
            "b": [1, 2],
        }

    def test_extracts_from_prose_and_fences(self) -> None:
        assert json.loads(salvage_json_text('Sure:\n```json\n{"a": 1}\n```') or "null") == {"a": 1}
        assert json.loads(salvage_json_text('The answer is {"a": 1} — done') or "null") == {"a": 1}

    def test_returns_none_for_unfixable(self) -> None:
        assert salvage_json_text('{"scene": {"name": "broken",') is None
        assert salvage_json_text("") is None
        assert salvage_json_text("[1, 2]") is None


class TestPruneExtraFields:
    def test_prunes_top_level_and_nested(self) -> None:
        data = {"keep": 1, "drop": 2, "nested": {"keep": 3, "drop": 4}}
        pruned = prune_extra_fields(
            data,
            [
                {"type": "extra_forbidden", "loc": ("drop",)},
                {"type": "extra_forbidden", "loc": ("nested", "drop")},
                {"type": "extra_forbidden", "loc": ("ghost",)},
            ],
        )
        assert pruned == {"keep": 1, "nested": {"keep": 3}}

    def test_returns_none_when_nothing_prunable(self) -> None:
        assert prune_extra_fields({"a": 1}, [{"type": "string_type", "loc": ("a",)}]) is None


class TestParseLlmOutputSalvage:
    def test_trailing_comma_script_now_parses(self) -> None:
        """The live failure: one trailing comma used to kill the generation."""

        payload = copy.deepcopy(VALID_SCENE_SCRIPT)
        raw = _wrap(payload)
        broken = raw.replace('"shots": [', '"shots": [') + ""  # keep structure
        # 手工注入尾逗号：在最后一个 } 前
        broken = broken.rstrip()[:-3] + ",\n```"
        result = parse_llm_output(broken)
        assert result.success, result.error
        assert result.scene_script is not None
        assert result.scene_script.scene.name == "salvage-scene"

    def test_extra_context_fields_are_pruned(self) -> None:
        payload = copy.deepcopy(VALID_SCENE_SCRIPT)
        payload["session_exists"] = True  # model echoing prompt context back
        result = parse_llm_output(_wrap(payload))
        assert result.success, result.error
        assert result.scene_script is not None


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class _EmptyMessageClient:
    """A reasoning model that burned its budget: 200 OK, empty content."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def post(self, *args, **kwargs):
        return _FakeResponse({"choices": [{"message": {"role": "assistant", "content": ""}}]})

    def close(self) -> None:
        pass


class _FakeSettings:
    llm_scene_model = "step-3.7-flash"
    llm_front_desk_model = "step-3.7-flash"
    llm_api_key = "test-key"
    llm_base_url = "https://example.invalid/v1"


def test_empty_message_falls_back_to_named_draft() -> None:
    generator = LLMSceneScriptGenerator(settings=_FakeSettings(), client_factory=_EmptyMessageClient)
    script = generator.generate(description="一个安静的室内房间，一张木桌和两把椅子")
    # 死不了的降级：拿到的是可编辑的粗略草案，且名字说穿了发生了什么
    assert script.scene.name.startswith("【草稿】")
    assert script.shots, "draft must carry a shot so the workbench can open"
