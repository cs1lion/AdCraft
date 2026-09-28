"""Unit tests for the P3 replica-structure guard (hypit "swap 骨架恒等断言").

锁定：

- 恒等：槽位替换/配方是**允许**的变化（复刻的目的正是换它们）；
- 漂移：镜头表/段落/锚点拓扑、画幅时长、节奏切点的任何变化都进漂移清单，
  且每条漂移可行动（点名哪个维度、期望什么、实际什么）；
- 端点守卫：变体渲染计划路径上结构漂移 → 500 replica_structure_drift（携带
  variant_id 与逐条漂移）；
- 故意不挂导入路径的理由：手改文档有权改结构（测试锁定"漂移清单可被读取"，
  供将来的诊断面使用，而不是在那里抛错）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.agent_canvas_ad_media import (
    ReplicaAnchorEventV2,
    ReplicaBeatV2,
    ReplicaBlueprintContentV2,
    ReplicaShotV2,
    ReplicaSlotV2,
)
from app.services.replica.structure_guard import (
    ReplicaStructureDrift,
    StructureGuardReport,
    assert_same_structure,
    structure_diff,
)


def _blueprint() -> ReplicaBlueprintContentV2:
    return ReplicaBlueprintContentV2(
        source_video_asset_id="asset-1",
        duration_seconds=12.0,
        aspect="9:16",
        replica_goal="换商品不换结构",
        whole_piece_reading="四段式促销结构。",
        format_name="product-comparison",
        slots=[
            ReplicaSlotV2(kind="product", label="商品", source_value="原片洗面奶"),
            ReplicaSlotV2(kind="style", label="风格", source_value=""),
        ],
        beats=[
            ReplicaBeatV2(beat_id="b1", role="hook", start_seconds=0.0, end_seconds=3.0),
            ReplicaBeatV2(beat_id="b2", role="proof", start_seconds=3.0, end_seconds=9.0),
        ],
        anchor_events=[
            ReplicaAnchorEventV2(event_id="e1", kind="caption", beat_id="b1", trigger="钩子"),
            ReplicaAnchorEventV2(event_id="e2", kind="sfx", beat_id="b2", trigger="落版"),
        ],
        shots=[
            ReplicaShotV2(index=1, start_seconds=0.0, end_seconds=3.0, on_screen_text="A"),
            ReplicaShotV2(index=2, start_seconds=3.0, end_seconds=9.0, on_screen_text="B"),
        ],
        rhythm_avg_shot_seconds=4.5,
        rhythm_cut_points_seconds=[0.0, 3.0],
        rhythm_energy_curve="前快后缓",
        systems_captions="底部大字",
        systems_music="促销电子",
    )


# ---------------------------------------------------------------------------
# 恒等：槽位/配方可自由变
# ---------------------------------------------------------------------------


def test_slot_replacement_is_allowed() -> None:
    before = _blueprint()
    after = before.model_copy(
        update={
            "slots": [
                slot.model_copy(
                    update={
                        "replace_with": "洗面奶A" if slot.kind == "product" else "gentle-everyday-vlog",
                        "applied": True,
                    }
                )
                for slot in before.slots
            ]
        }
    )
    assert structure_diff(before, after) == ()
    assert_same_structure(before, after)  # 不抛


def test_content_edits_that_keep_topology_are_allowed() -> None:
    before = _blueprint()
    after = before.model_copy(
        update={
            "whole_piece_reading": "换了说法但结构相同。",
            "shots": [
                shot.model_copy(update={"on_screen_text": f"改过{i}"})
                for i, shot in enumerate(before.shots)
            ],
            "anchor_events": [
                event.model_copy(update={"trigger": event.trigger + "！", "keep": False})
                for event in before.anchor_events
            ],
            "beats": [
                beat.model_copy(update={"line": "新台词", "description": "重写描述"})
                for beat in before.beats
            ],
        }
    )
    assert structure_diff(before, after) == ()


# ---------------------------------------------------------------------------
# 漂移：拓扑/画幅时长/切点
# ---------------------------------------------------------------------------


def test_shot_topology_drift_is_actionable() -> None:
    before = _blueprint()
    after = before.model_copy(
        update={"shots": before.shots[:1]}  # 删一个镜头
    )
    drifts = structure_diff(before, after)
    assert len(drifts) == 1
    assert "shots topology" in drifts[0]
    assert "2 → 1" in drifts[0]


def test_shot_time_window_drift_detected() -> None:
    before = _blueprint()
    after = before.model_copy(
        update={
            "shots": [
                before.shots[0].model_copy(update={"end_seconds": 4.0}),
                before.shots[1],
            ]
        }
    )
    assert structure_diff(before, after)  # 时间窗也是骨架


def test_beat_and_anchor_topology_drift_detected() -> None:
    before = _blueprint()
    after = before.model_copy(
        update={
            "beats": before.beats[:1],
            "anchor_events": [
                before.anchor_events[0].model_copy(update={"kind": "broll"}),
                before.anchor_events[1],
            ],
        }
    )
    drifts = structure_diff(before, after)
    assert any("beats topology" in d for d in drifts)
    assert any("anchor topology" in d for d in drifts)


def test_carrier_drift_detected() -> None:
    before = _blueprint()
    aspect_drift = structure_diff(before, before.model_copy(update={"aspect": "16:9"}))
    duration_drift = structure_diff(
        before, before.model_copy(update={"duration_seconds": 15.0})
    )
    cut_drift = structure_diff(
        before, before.model_copy(update={"rhythm_cut_points_seconds": [0.0, 3.0, 6.0]})
    )
    assert any(d.startswith("aspect:") for d in aspect_drift)
    assert any(d.startswith("duration_seconds:") for d in duration_drift)
    assert any("cut points" in d for d in cut_drift)


def test_assert_raises_with_actionable_drifts() -> None:
    before = _blueprint()
    after = before.model_copy(update={"aspect": "16:9", "beats": before.beats[:1]})
    with pytest.raises(ReplicaStructureDrift) as excinfo:
        assert_same_structure(before, after)
    assert len(excinfo.value.drifts) == 2
    assert any(d.startswith("aspect:") for d in excinfo.value.drifts)


def test_guard_report_records_ok_and_drifts() -> None:
    ok = StructureGuardReport.check(_blueprint(), _blueprint())
    assert ok.ok is True and ok.drifts == ()
    drifted = StructureGuardReport.check(
        _blueprint(), _blueprint().model_copy(update={"aspect": "1:1"})
    )
    assert drifted.ok is False
    assert drifted.drifts


# ---------------------------------------------------------------------------
# 端点守卫：变体派生路径
# ---------------------------------------------------------------------------


@pytest.fixture
def guard_client():
    app = FastAPI()
    from app.api.v1.endpoints import replica as replica_endpoint

    app.include_router(replica_endpoint.router)
    return TestClient(app)


def _variant_plans_payload(**overrides) -> dict:
    blueprint = _blueprint().model_dump(mode="json")
    payload = {
        "blueprint": blueprint,
        "n": 2,
        "render_representatives": 2,
    }
    payload.update(overrides)
    return payload


def test_variant_render_plans_pass_the_guard(guard_client) -> None:
    """正常变体（只换 style 槽位 + 配方）通过守卫——结构不被变体改动。"""
    response = guard_client.post(
        "/replica/blueprint/variant-render-plans", json=_variant_plans_payload()
    )
    assert response.status_code == 200, response.text
    assert response.json()["variants"]


def test_variant_render_plans_guard_rejects_drift(guard_client, monkeypatch) -> None:
    """守卫可执行：派生图出现结构漂移 → 500 + code/variant_id/逐条漂移。"""
    from app.services.replica import structure_guard as guard_source
    from app.services.replica.structure_guard import StructureGuardReport

    class _DriftingReport:
        @staticmethod
        def check(before, after):
            return StructureGuardReport(ok=False, drifts=("shots topology changed: 2 → 1",))

    # 端点是函数内 import：打桩源头模块（运行时解析的那个名字）
    monkeypatch.setattr(guard_source, "StructureGuardReport", _DriftingReport)

    response = guard_client.post(
        "/replica/blueprint/variant-render-plans", json=_variant_plans_payload()
    )

    assert response.status_code == 500, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "replica_structure_drift"
    assert detail["drifts"] == ["shots topology changed: 2 → 1"]
    assert detail["variant_id"].startswith("variant_")
