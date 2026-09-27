"""Unit tests for the direct-execute feasibility gate (零模型费可行性门).

Covers: the deterministic classification rules (pure on-screen-text shots are
zero-model; action shots, voice lines and applied subject slots require
generation), structural blockers, the always-present editing step, and the
endpoint contract.

Design rationale: docs/plans/hypit-replica-research.md P3（direct-execute
快车道）+ §3.5 编译边界（不建第二执行链，渲染器属剪辑域）。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.services.replica.direct_execute import plan_direct_execute


def _blueprint(**overrides: Any) -> ReplicaBlueprintContentV2:
    payload: dict[str, Any] = {
        "shots": [
            {
                "index": 1,
                "start_seconds": 0.0,
                "end_seconds": 2.0,
                "on_screen_text": "第7天",
                "subject_action": "",
            },
            {
                "index": 2,
                "start_seconds": 2.0,
                "end_seconds": 4.0,
                "subject_action": "产品特写",
            },
        ],
        "beats": [
            {"beat_id": "b1", "role": "hook", "line": "别再这样洗脸了",
             "start_seconds": 0.0, "end_seconds": 3.0},
        ],
        "systems_captions": "底部关键词高亮",
        "systems_music": "轻快电子",
        "systems_sfx": ["whoosh"],
    }
    payload.update(overrides)
    return ReplicaBlueprintContentV2(**payload)


def test_mixed_blueprint_is_not_feasible_with_clear_costs() -> None:
    plan = plan_direct_execute(_blueprint())
    assert plan.feasible is False
    # 镜头 1 纯屏上文字 → 零模型费；镜头 2 有动作 → 需生成
    assert any(s["step"] == "shot_1" for s in plan.zero_model_steps)
    assert any(s["step"] == "shot_2" for s in plan.generation_steps)
    # 台词 → TTS 属生成成本
    assert any(s["step"] == "voice" for s in plan.generation_steps)
    # 字幕/音效/音乐/剪辑 → 零模型费
    steps = {s["step"] for s in plan.zero_model_steps}
    assert {"captions", "sfx", "music", "editing"} <= steps


def test_pure_caption_piece_is_feasible() -> None:
    """纯字幕/MG 片：镜头全部是屏上文字、无台词无主体替换 → 零模型费直出。"""
    blueprint = _blueprint(
        shots=[
            {
                "index": 1,
                "start_seconds": 0.0,
                "end_seconds": 2.0,
                "on_screen_text": "第7天",
                "subject_action": "",
            },
        ],
        beats=[
            {"beat_id": "b1", "role": "hook", "line": "",
             "start_seconds": 0.0, "end_seconds": 3.0},
        ],
    )
    plan = plan_direct_execute(blueprint)
    assert plan.feasible is True
    assert plan.generation_steps == ()
    assert not plan.blockers


def test_applied_subject_slot_requires_generation() -> None:
    blueprint = _blueprint(
        slots=[
            {
                "kind": "product",
                "label": "商品",
                "source_value": "原片",
                "replace_with": "洗面奶A",
                "applied": True,
            }
        ],
    )
    plan = plan_direct_execute(blueprint)
    assert any(s["step"] == "slot_product" for s in plan.generation_steps)
    assert plan.feasible is False


def test_empty_blueprint_has_blockers() -> None:
    plan = plan_direct_execute(ReplicaBlueprintContentV2())
    assert plan.feasible is False
    assert any("无镜头表" in b for b in plan.blockers)
    assert any("无结构段落" in b for b in plan.blockers)


def test_plan_is_deterministic() -> None:
    first = plan_direct_execute(_blueprint())
    second = plan_direct_execute(_blueprint())
    assert first.to_dict() == second.to_dict()


# ---------------------------------------------------------------------------
# 端点契约
# ---------------------------------------------------------------------------


@pytest.fixture
def direct_client():
    from app.api.v1.endpoints import replica as replica_endpoint

    app = FastAPI()
    app.include_router(replica_endpoint.router)
    return TestClient(app)


def test_direct_execute_endpoint(direct_client) -> None:
    response = direct_client.post(
        "/replica/blueprint/direct-execute-plan",
        json={"blueprint": _blueprint().model_dump(mode="json")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["feasible"] is False
    assert body["zero_model_steps"] and body["generation_steps"]


def test_direct_execute_endpoint_rejects_bad_blueprint(direct_client) -> None:
    response = direct_client.post(
        "/replica/blueprint/direct-execute-plan",
        json={"blueprint": {"slots": "oops"}},
    )
    assert response.status_code == 422, response.text
