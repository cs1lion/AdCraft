"""Outline → shots → build plan (2026-09-29 简约好用 branch).

Flow B starts from one sentence: expand it into shots (LLM, salvaged parse),
review, and build the canvas nodes (script + per-shot 设定图 + per-shot film).
"""

from __future__ import annotations

import pytest

from app.services.creation.outline_expander import (
    OutlineExpansionError,
    parse_outline_plan,
    plan_outline_build,
)

LLM_OUTPUT = """当然，这是分镜：

```json
{
  "shots": [
    {
      "summary": "清晨厨房，一盘红苹果特写",
      "visual": "清晨自然光，红苹果带露珠摆在木案板上，浅景深，暖色调",
      "duration_seconds": 5,
      "on_screen_text": "新鲜，看得见"
    },
    {
      "summary": "苹果切开，汁水慢动作",
      "visual": "微距慢动作，苹果被切开，汁水渗出，露珠滚落",
      "duration_seconds": 6,
      "on_screen_text": ""
    }
  ]
}
```

希望对你有帮助！"""


def test_parses_fenced_prose_wrapped_json() -> None:
    plan = parse_outline_plan(LLM_OUTPUT)
    assert [shot.summary for shot in plan.shots] == [
        "清晨厨房，一盘红苹果特写",
        "苹果切开，汁水慢动作",
    ]
    assert plan.shots[0].duration_seconds == 5
    assert plan.shots[0].on_screen_text == "新鲜，看得见"


def test_duration_is_clamped() -> None:
    plan = parse_outline_plan(
        '{"shots": [{"summary": "s", "visual": "v", "duration_seconds": 99}]}'
    )
    assert plan.shots[0].duration_seconds == 12
    plan = parse_outline_plan('{"shots": [{"summary": "s", "visual": "v", "duration_seconds": 1}]}')
    assert plan.shots[0].duration_seconds == 4


def test_garbage_raises_coded_error() -> None:
    with pytest.raises(OutlineExpansionError):
        parse_outline_plan("no json at all")
    with pytest.raises(OutlineExpansionError):
        parse_outline_plan('{"shots": []}')


def test_build_plan_creates_script_setting_and_film_nodes() -> None:
    plan = parse_outline_plan(LLM_OUTPUT)
    build = plan_outline_build("一条关于红苹果的清晨广告", plan)
    assert build.script_title == "创作纲领"
    assert "红苹果" in build.script_text
    assert len(build.settings_nodes) == 2
    assert len(build.film_nodes) == 2
    assert build.settings_nodes[0]["node_type"] == "image"
    assert build.settings_nodes[0]["title"] == "设定图1"
    assert build.film_nodes[0]["node_type"] == "video"
    assert build.film_nodes[0]["title"] == "成片镜头1"
    segment = build.film_nodes[1]["structured_content"]
    assert segment["duration_seconds"] == 6
    assert "汁水" in segment["storyboard_content"]
