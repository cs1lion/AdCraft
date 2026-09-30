"""复刻改写测试（同风格、新元素——不是新旧拼贴）。

锁三件事：① 改写后的每镜提示词只带新版描述，不抄原片品牌/产品文本，
也不附槽位指令行（那是在提示模型"还有个原片元素"）；② 改写 JSON 的
救捞解析（含栅栏、数量不符报错）；③ 槽位指纹稳定（重试提示词不漂移）。
"""

from __future__ import annotations

import pytest

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.services.replica.film import plan_film_shots
from app.services.replica.shot_rewrite import (
    ShotRewriteError,
    parse_shot_rewrite,
    shot_rewrite_fingerprint,
)


def _blueprint() -> ReplicaBlueprintContentV2:
    payload = {
        "blueprint_version": "replica-blueprint-v1",
        "format_name": "product-showcase",
        "duration_seconds": 30.1,
        "shots": [
            {
                "index": 1,
                "start_seconds": 0.0,
                "end_seconds": 5.0,
                "shot_size": "wide",
                "camera_motion": "static",
                "subject_action": "Flat lay display of full Vita Coco product line",
                "on_screen_text": "VITA COCO Coconut Water original",
                "transition_to_next": "cut",
            },
            {
                "index": 2,
                "start_seconds": 5.0,
                "end_seconds": 9.0,
                "shot_size": "medium",
                "camera_motion": "static",
                "subject_action": "Smoothie pour, top-down",
                "on_screen_text": "",
                "transition_to_next": "cut",
            },
        ],
        "beats": [],
        "anchor_events": [],
        "slots": [
            {
                "kind": "product",
                "label": "商品",
                "source_value": "VITA COCO 椰子水",
                "replace_with": "一颗新鲜红苹果，果柄上戴着一朵淡黄色小雏菊",
                "applied": True,
            },
        ],
    }
    return ReplicaBlueprintContentV2.model_validate(payload)


REWRITTEN = [
    "平铺俯拍，一颗带雏菊的红苹果居中，水滴特写，暖色定格动画质感。",
    "顶部俯拍，苹果切面整齐排列，汁液反光，同色调同节奏。",
]


def test_rewritten_briefs_replace_original_text() -> None:
    plans = plan_film_shots(_blueprint(), rewritten_visuals=REWRITTEN)
    assert len(plans) == 2
    for plan, brief in zip(plans, REWRITTEN):
        content = plan.generation_prompt
        assert brief in content
        assert "VITA COCO" not in content
        assert "Vita Coco" not in content
        assert "槽位替换" not in content  # 不再暗示"存在原片元素"


def test_rewritten_briefs_keep_composition_and_transition() -> None:
    plans = plan_film_shots(_blueprint(), rewritten_visuals=REWRITTEN)
    assert "wide/static" in plans[0].generation_prompt
    assert "转场：cut" in plans[0].generation_prompt
    assert "构图与机位保持一致" in plans[0].generation_prompt


def test_wrong_count_rewrites_fall_back_to_original_behaviour() -> None:
    plans = plan_film_shots(_blueprint(), rewritten_visuals=[REWRITTEN[0]])
    assert "VITA COCO" in plans[0].generation_prompt  # 退回原行为
    assert "槽位替换" in plans[0].generation_prompt


def test_parse_shot_rewrite_accepts_plain_and_fenced_json() -> None:
    assert parse_shot_rewrite('{"shots":["a","b"]}', 2) == ["a", "b"]
    assert parse_shot_rewrite('```json\n{"shots": ["a", "b"]}\n```', 2) == ["a", "b"]


def test_parse_shot_rewrite_rejects_wrong_count() -> None:
    with pytest.raises(ShotRewriteError):
        parse_shot_rewrite('{"shots":["only-one"]}', 2)
    with pytest.raises(ShotRewriteError):
        parse_shot_rewrite("totally not json", 2)


def test_fingerprint_is_stable_and_slot_sensitive() -> None:
    pairs = [("product", "红苹果"), ("style", "定格动画")]
    assert shot_rewrite_fingerprint(pairs) == shot_rewrite_fingerprint(list(pairs))
    assert shot_rewrite_fingerprint(pairs) != shot_rewrite_fingerprint(
        [("product", "红苹果"), ("style", "赛博朋克")]
    )


def test_rewritten_segment_carries_negative_constraints() -> None:
    plans = plan_film_shots(_blueprint(), rewritten_visuals=REWRITTEN)
    negative = plans[0].segment.get("negative_constraints") or ""
    assert "VITA COCO" in negative or "椰子水" in negative
    assert "不得出现" in negative
