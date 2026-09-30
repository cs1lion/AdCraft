"""One-call replica film planning (2026-09-29, 简约好用 branch).

The author presses one button; the blueprint becomes one video node per shot.
These tests lock the shot→segment mapping: slot directives ride along, the
duration is clamped to what video models accept, and every shot keeps its
teardown composition.
"""

from __future__ import annotations

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.services.replica.film import (
    FILM_NODE_TITLE_PREFIX,
    MAX_SHOT_SECONDS,
    MIN_SHOT_SECONDS,
    plan_film_shots,
)


def _blueprint(**overrides) -> ReplicaBlueprintContentV2:
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
                "subject_action": "Four cartons in a diagonal line",
                "on_screen_text": "VITA COCO Coconut Water",
                "transition_to_next": "cut",
            },
            {
                "index": 2,
                "start_seconds": 5.0,
                "end_seconds": 2.0,
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
                "replace_with": "一颗新鲜红苹果",
                "applied": True,
            },
            {
                "kind": "voice",
                "label": "声音",
                "source_value": "",
                "replace_with": "",
                "applied": False,
            },
        ],
    }
    payload.update(overrides)
    return ReplicaBlueprintContentV2.model_validate(payload)


def test_every_shot_becomes_one_plan_with_a_titled_segment() -> None:
    plans = plan_film_shots(_blueprint())
    assert [plan.title for plan in plans] == [f"{FILM_NODE_TITLE_PREFIX}1", f"{FILM_NODE_TITLE_PREFIX}2"]
    assert plans[0].segment["segment_summary"].startswith("复刻镜头1")
    assert "Four cartons" in plans[0].segment["storyboard_content"]
    assert "VITA COCO" in plans[0].segment["storyboard_content"]


def test_applied_slot_directives_ride_along_per_shot() -> None:
    plans = plan_film_shots(_blueprint())
    for plan in plans:
        assert "槽位替换" in plan.generation_prompt
        assert "一颗新鲜红苹果" in plan.generation_prompt
    # unapplied slots stay out of the directives
    assert "声音" not in plans[0].generation_prompt.split("槽位替换")[-1]


def test_shot_duration_is_clamped_to_the_model_window() -> None:
    plans = plan_film_shots(_blueprint())
    assert plans[0].segment["duration_seconds"] == 5.0
    assert plans[1].segment["duration_seconds"] == MIN_SHOT_SECONDS
    long_blueprint = _blueprint()
    long_blueprint.shots[0].end_seconds = 60.0
    assert plan_film_shots(long_blueprint)[0].segment["duration_seconds"] == MAX_SHOT_SECONDS


def test_empty_blueprint_yields_no_shots() -> None:
    assert plan_film_shots(_blueprint(shots=[])) == []


def test_segment_payload_validates_as_video_segment_content() -> None:
    from app.schemas.agent_canvas_ad_media import VideoSegmentContentV2

    for plan in plan_film_shots(_blueprint()):
        segment = VideoSegmentContentV2.model_validate(plan.segment)
        assert segment.background_music is False
        assert segment.duration_seconds >= MIN_SHOT_SECONDS


def test_applied_slot_lands_in_shot_prompt():
    """槽位 applied 后，每镜提示词必须带替换指令（否则出片不换元素）。"""
    from app.services.replica.blueprint import apply_slot_updates

    blueprint = _blueprint()
    kind = blueprint.slots[1].kind  # 商品
    updated = apply_slot_updates(blueprint, {kind: "一颗新鲜红苹果，果柄上戴着一朵淡黄色小雏菊"})
    for plan in plan_film_shots(updated):
        assert "槽位替换" in plan.generation_prompt
        assert "一颗新鲜红苹果" in plan.generation_prompt
