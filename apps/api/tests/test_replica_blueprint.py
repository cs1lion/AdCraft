"""Unit tests for the 拉片复刻 blueprint layer (the "复刻" half).

Covers: teardown-report → blueprint conversion (deterministic, slot/anchor
derivation), slot updates, anchor keep/remove, the deterministic replica
script rendering, and the instantiation plan (CanvasNodeCreateRequestV2
shape). Pure functions only — no IO, no LLM, no HTTP.

Design rationale: docs/plans/hypit-replica-research.md §2/§6 (slots,
anchor events, instantiate-to-canvas).
"""

from __future__ import annotations

import pytest

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.services.replica import blueprint as bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _teardown_report() -> dict:
    return {
        "whole_piece_reading": "前3秒用错误示范制造焦虑，中段产品证明，结尾CTA。",
        "format_name": "product-comparison",
        "shots": [
            {"index": 1, "start_seconds": 0.0, "end_seconds": 2.1, "shot_size": "closeup",
             "camera_motion": "static", "subject_action": "唇部特写",
             "on_screen_text": "别再这样洗脸", "transition_to_next": "cut", "note": "同机位，换成用户商品"},
            {"index": 2, "start_seconds": 2.1, "end_seconds": 7.5, "shot_size": "medium",
             "camera_motion": "pushing_in", "subject_action": "七天涂抹对比",
             "on_screen_text": "", "transition_to_next": "dissolve", "note": ""},
            {"index": 3, "start_seconds": 7.5, "end_seconds": 12.0, "shot_size": "medium",
             "camera_motion": "static", "subject_action": "产品定格",
             "on_screen_text": "第7天", "transition_to_next": "cut", "note": ""},
        ],
        "beats": [
            {"role": "hook", "description": "错误示范抓注意力", "start_seconds": 0.0, "end_seconds": 3.0},
            {"role": "proof", "description": "连续7天对比", "start_seconds": 3.0, "end_seconds": 9.0},
            {"role": "cta", "description": "引导下单", "start_seconds": 9.0, "end_seconds": 12.0},
        ],
        "rhythm": {"avg_shot_seconds": 4.0, "cut_points_seconds": [0.0, 2.1, 7.5], "energy_curve": "前快后缓"},
        "systems": {"captions": "底部关键词高亮", "music": "轻快电子",
                    "graphics": ["价格贴: 产品提到时弹入"], "sfx": ["切换 whoosh"]},
        "constraints": ["镜头边界为推断值"],
    }


@pytest.fixture
def blueprint() -> ReplicaBlueprintContentV2:
    return bp.blueprint_from_teardown(
        _teardown_report(),
        source_asset_id="asset-1",
        duration_seconds=12.0,
        aspect="9:16",
        replica_goal="换商品，保留人物与台词结构",
    )


# ---------------------------------------------------------------------------
# teardown → blueprint
# ---------------------------------------------------------------------------


def test_blueprint_from_teardown_is_deterministic(blueprint) -> None:
    again = bp.blueprint_from_teardown(
        _teardown_report(),
        source_asset_id="asset-1",
        duration_seconds=12.0,
        aspect="9:16",
        replica_goal="换商品，保留人物与台词结构",
    )
    assert again == blueprint


def test_blueprint_metadata(blueprint) -> None:
    assert blueprint.blueprint_version == "replica-blueprint-v1"
    assert blueprint.source_video_asset_id == "asset-1"
    assert blueprint.duration_seconds == 12.0
    assert blueprint.aspect == "9:16"
    assert "换商品" in blueprint.replica_goal
    assert blueprint.format_name == "product-comparison"


def test_blueprint_default_slots_and_goal_focus(blueprint) -> None:
    kinds = [s.kind for s in blueprint.slots]
    assert kinds == ["character", "product", "script", "style", "voice"]
    # goal "换商品" focuses the product slot with a hint
    product = next(s for s in blueprint.slots if s.kind == "product")
    assert "换商品" in product.source_value
    # script slot carries the standing note
    script = next(s for s in blueprint.slots if s.kind == "script")
    assert "保留原片台词结构" in script.source_value


def test_blueprint_anchors_are_first_class_and_derived(blueprint) -> None:
    # one caption anchor per beat + shot-derived anchors (on_screen_text / recreate_hint)
    event_ids = {a.event_id for a in blueprint.anchor_events}
    assert {"b1_caption", "b2_caption", "b3_caption"} <= event_ids
    # shot 1 has on-screen text "别再这样洗脸" → caption anchor in beat 1
    assert "b1_shot1_cap" in event_ids
    # shot 1 has a recreate hint → broll anchor
    assert "b1_shot1_broll" in event_ids
    # beat ids reference persisted events
    beat1 = blueprint.beats[0]
    assert beat1.anchor_event_ids
    for event_id in beat1.anchor_event_ids:
        assert event_id in event_ids


def test_blueprint_shots_keep_teardown_fields(blueprint) -> None:
    assert len(blueprint.shots) == 3
    assert blueprint.shots[0].on_screen_text == "别再这样洗脸"
    assert blueprint.shots[0].recreate_hint == "同机位，换成用户商品"
    assert blueprint.shots[1].recreate_hint == ""


# ---------------------------------------------------------------------------
# Slot updates
# ---------------------------------------------------------------------------


def test_apply_slot_updates_marks_applied(blueprint) -> None:
    updated = bp.apply_slot_updates(blueprint, {"product": "洗面奶A", "character": ""})
    product = next(s for s in updated.slots if s.kind == "product")
    character = next(s for s in updated.slots if s.kind == "character")
    assert product.replace_with == "洗面奶A"
    assert product.applied is True
    assert character.applied is False
    # 原对象不被修改（model_copy 语义）
    assert next(s for s in blueprint.slots if s.kind == "product").applied is False


def test_apply_slot_updates_empty_is_noop(blueprint) -> None:
    assert bp.apply_slot_updates(blueprint, {}) is blueprint


# ---------------------------------------------------------------------------
# Anchor keep/remove
# ---------------------------------------------------------------------------


def test_toggle_anchor_event_removes_and_restores(blueprint) -> None:
    removed = bp.toggle_anchor_event(blueprint, "b1_caption", keep=False)
    beat1 = removed.beats[0]
    assert "b1_caption" not in beat1.anchor_event_ids
    assert next(e for e in removed.anchor_events if e.event_id == "b1_caption").keep is False
    # 未命中事件时原样返回
    assert bp.toggle_anchor_event(removed, "nope", keep=False) is removed

    restored = bp.toggle_anchor_event(removed, "b1_caption", keep=True)
    assert "b1_caption" in restored.beats[0].anchor_event_ids
    assert next(e for e in restored.anchor_events if e.event_id == "b1_caption").keep is True


# ---------------------------------------------------------------------------
# Replica script rendering
# ---------------------------------------------------------------------------


def test_render_replica_script_contains_all_sections(blueprint) -> None:
    script = bp.render_replica_script(blueprint)
    assert "# 复刻脚本" in script
    assert "复刻目标：换商品" in script
    assert "## 整片解读" in script
    assert "## 槽位替换" in script
    assert "## 分场（锚点事件随段落走）" in script
    assert "[0.0–3.0s] hook" in script
    assert "@{b1_shot1_cap}" in script
    assert "@{b1_shot1_broll}" in script
    assert "## 节奏与系统" in script
    assert "字幕：底部关键词高亮" in script
    assert "## 复刻提示" in script


def test_render_replica_script_reflects_slot_updates(blueprint) -> None:
    updated = bp.apply_slot_updates(blueprint, {"product": "洗面奶A"})
    script = bp.render_replica_script(updated)
    assert "【商品】原片「复刻目标：换商品，保留人物与台词结构」→ 替换为「洗面奶A」" in script


def test_render_replica_script_reflects_anchor_removal(blueprint) -> None:
    removed = bp.toggle_anchor_event(blueprint, "b1_caption", keep=False)
    script = bp.render_replica_script(removed)
    assert "@{b1_caption}" not in script
    # 其他锚点仍在
    assert "@{b1_shot1_cap}" in script


# ---------------------------------------------------------------------------
# Instantiation plan
# ---------------------------------------------------------------------------


def test_plan_script_instantiation_shape(blueprint) -> None:
    plan = bp.plan_script_instantiation(
        blueprint,
        replica_node_id="node_replica",
        position={"x": 100.0, "y": 200.0},
    )
    request = plan.node_request
    assert request["node_type"] == "script"
    assert request["creative_role"] == "script"
    assert request["role_contract_version"] == "ad-media-role-v2"
    assert request["title"] == "复刻脚本 · product-comparison"
    assert request["position"] == {"x": 100.0, "y": 200.0}
    assert request["authoring_origin"] == "agent_guided"
    # 内容与提示一致（script 节点读 structured_content.content）
    assert request["structured_content"]["content"] == plan.script_text
    assert request["structured_content"]["replica_source_node_id"] == "node_replica"
    # 绑定请求：replica → script 的 text_context
    assert plan.binding["source"] == {"kind": "node_output", "source_node_id": "node_replica"}
    assert plan.binding["input_role"] == "text_context"

    # 可通过 CanvasNodeCreateRequestV2 校验（pydantic 契约）
    from app.schemas.agent_canvas import CanvasNodeCreateRequestV2

    validated = CanvasNodeCreateRequestV2(**request)
    assert validated.node_type == "script"


def test_plan_script_instantiation_offsets_below_replica(blueprint) -> None:
    plan = bp.plan_script_instantiation(
        blueprint, replica_node_id="n", position={"x": 0.0, "y": 0.0}
    )
    assert plan.node_request["position"]["y"] == 0.0  # 偏移由端点层施加，计划保持传入值


# ---------------------------------------------------------------------------
# 词级锚定解析（whisperX 词流 → 锚点事件绑定具体词）
# ---------------------------------------------------------------------------

_WORDS = [
    {"text": "别再", "start_seconds": 0.2, "end_seconds": 0.5},
    {"text": "这样", "start_seconds": 0.5, "end_seconds": 0.9},
    {"text": "洗脸", "start_seconds": 0.9, "end_seconds": 1.4},
    {"text": "了", "start_seconds": 1.4, "end_seconds": 1.6},
]


def _report_with_transcript() -> dict:
    return {
        **_teardown_report(),
        "beats": [
            {"role": "hook", "description": "错误示范抓注意力", "line": "别再这样洗脸了",
             "start_seconds": 0.0, "end_seconds": 3.0},
            {"role": "proof", "description": "七天对比", "line": "连洗七天",
             "start_seconds": 3.0, "end_seconds": 9.0},
        ],
        "transcript": {
            "source": "whisperx",
            "language": "zh",
            "reason": "",
            "words": _WORDS,
        },
    }


def test_blueprint_from_teardown_binds_word_anchors() -> None:
    """字幕锚点兜底绑定整句台词；报告带词流时蓝图拿到词级锚定。"""
    blueprint = bp.blueprint_from_teardown(
        _report_with_transcript(), source_asset_id="a", duration_seconds=12.0
    )
    caption = next(e for e in blueprint.anchor_events if e.event_id == "b1_caption")
    assert caption.word == "别再这样洗脸了"
    assert caption.word_start_seconds == 0.2
    assert caption.word_end_seconds == 1.6
    # beats 携带台词原文
    assert blueprint.beats[0].line == "别再这样洗脸了"


def test_resolve_word_anchors_trigger_match() -> None:
    """触发文本命中窗口词流 → 绑定覆盖词的时间跨度。"""
    from app.schemas.agent_canvas_ad_media import (
        ReplicaAnchorEventV2,
        ReplicaBeatV2,
        ReplicaBlueprintContentV2,
    )

    blueprint = ReplicaBlueprintContentV2(
        beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=3.0)],
        anchor_events=[
            ReplicaAnchorEventV2(event_id="e1", kind="sfx", beat_id="b1", trigger="这样洗脸"),
        ],
    )
    resolved = bp.resolve_word_anchors(blueprint, _WORDS)
    event = resolved.anchor_events[0]
    assert event.word == "这样洗脸"
    assert (event.word_start_seconds, event.word_end_seconds) == (0.5, 1.4)
    # 纯函数：原对象不被修改
    assert blueprint.anchor_events[0].word == ""


def test_resolve_word_anchors_requires_window() -> None:
    """锚不出段落：段落窗外的词不参与匹配。"""
    from app.schemas.agent_canvas_ad_media import (
        ReplicaAnchorEventV2,
        ReplicaBeatV2,
        ReplicaBlueprintContentV2,
    )

    blueprint = ReplicaBlueprintContentV2(
        beats=[ReplicaBeatV2(beat_id="b1", start_seconds=5.0, end_seconds=9.0)],
        anchor_events=[
            ReplicaAnchorEventV2(event_id="e1", kind="sfx", beat_id="b1", trigger="这样洗脸"),
        ],
    )
    resolved = bp.resolve_word_anchors(blueprint, _WORDS)
    assert resolved.anchor_events[0].word == ""


def test_resolve_word_anchors_without_words_is_identity(blueprint) -> None:
    """无词流（转录不可用）→ 原样返回，锚点保持段落级。"""
    assert bp.resolve_word_anchors(blueprint, []) is blueprint


def test_resolve_word_anchors_is_deterministic(blueprint) -> None:
    words = list(_WORDS)
    first = bp.resolve_word_anchors(blueprint, words)
    second = bp.resolve_word_anchors(blueprint, list(words))
    assert first.model_dump() == second.model_dump()


def test_blueprint_without_transcript_keeps_beat_level_anchors(blueprint) -> None:
    """旧报告（无 transcript 字段）完全向后兼容：锚点保持段落级。"""
    for anchor in blueprint.anchor_events:
        assert anchor.word == ""
        assert anchor.word_start_seconds == 0.0


# ---------------------------------------------------------------------------
# 实例化端点契约（fakes：绑定自动创建 + 实例化指针写回）
# ---------------------------------------------------------------------------


def _instantiate_fakes(monkeypatch):
    """Instantiate 端点的重依赖 fakes：节点服务 / 仓储 / 蓝图节点。"""
    from datetime import datetime, timezone

    from app.schemas.agent_canvas import CanvasNodeV2

    created_nodes: list = []
    bindings: list = []
    patched_contents: list = []
    revision = {"value": 5}

    class _FakeNode:
        node_id = "node_script_new"

    class _FakeRepo:
        def get_workflow(self, workflow_id):
            from app.schemas.agent_canvas import AgentCanvasWorkflowV2

            return AgentCanvasWorkflowV2(
                workflow_id=workflow_id,
                project_id="proj-1",
                revision=revision["value"],
            )

        def get_node(self, workflow_id, node_id):
            now = datetime.now(timezone.utc).isoformat()
            return CanvasNodeV2(
                node_id=node_id,
                workflow_id=workflow_id,
                node_type="replica",
                creative_role="replica_blueprint",
                title="复刻蓝图",
                status="draft",
                structured_content={
                    **_blueprint_fixture_dict(),
                    "instantiated_script_node_id": None,
                },
                parameters={},
                metadata={},
                position={"x": 0.0, "y": 0.0},
                revision=1,
                error=None,
                authoring_origin="agent_guided",
                created_at=now,
                updated_at=now,
            )

        def add_binding(self, binding, *, expected_revision):
            assert expected_revision == revision["value"]
            bindings.append(binding)
            revision["value"] += 1

    class _FakeNodeService:
        def create(self, workflow_id, request, *, expected_revision):
            assert expected_revision == revision["value"]
            created_nodes.append(request)
            revision["value"] += 1
            return _FakeNode()

        def patch(self, workflow_id, node_id, request, *, expected_revision):
            patched_contents.append(request.structured_content)
            revision["value"] += 1
            return object()

    from app.api.v1.endpoints import replica as replica_endpoint

    monkeypatch.setattr(
        replica_endpoint,
        "_canvas_node_service",
        lambda: (_FakeNodeService(), _FakeRepo()),
    )
    return {
        "created": created_nodes,
        "bindings": bindings,
        "patched": patched_contents,
    }


def _blueprint_fixture_dict() -> dict:
    blueprint = bp.blueprint_from_teardown(
        _teardown_report(),
        source_asset_id="asset-1",
        duration_seconds=12.0,
        aspect="9:16",
        replica_goal="换商品",
    )
    return blueprint.model_dump(mode="json")


@pytest.fixture
def instantiate_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import replica as replica_endpoint

    fakes = _instantiate_fakes(monkeypatch)
    app = FastAPI()
    app.include_router(replica_endpoint.router)
    return TestClient(app), fakes


def test_instantiate_creates_binding_and_writes_back_pointer(instantiate_client) -> None:
    client, fakes = instantiate_client
    response = client.post(
        "/replica/instantiate",
        json={"workflow_id": "wf-1", "replica_node_id": "node_replica"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["script_node_id"] == "node_script_new"
    assert body["binding_id"].startswith("binding_")

    # 绑定：replica → script，text_context
    assert len(fakes["bindings"]) == 1
    binding = fakes["bindings"][0]
    assert binding.source.source_node_id == "node_replica"
    assert binding.target_node_id == "node_script_new"
    assert binding.input_role == "text_context"

    # 指针写回：instantiated_script_node_id 进蓝图节点内容
    assert len(fakes["patched"]) == 1
    assert fakes["patched"][0]["instantiated_script_node_id"] == "node_script_new"
    # 槽位/锚点等蓝图主体保持完整
    assert fakes["patched"][0]["blueprint_version"] == "replica-blueprint-v1"


def test_instantiate_applies_slot_updates(instantiate_client) -> None:
    client, fakes = instantiate_client
    response = client.post(
        "/replica/instantiate",
        json={
            "workflow_id": "wf-1",
            "replica_node_id": "node_replica",
            "slot_updates": {"product": "洗面奶A"},
        },
    )
    assert response.status_code == 200, response.text
    # 槽位替换进脚本与写回内容
    product = next(
        s for s in fakes["patched"][0]["slots"] if s["kind"] == "product"
    )
    assert product["replace_with"] == "洗面奶A"
    assert product["applied"] is True


# ---------------------------------------------------------------------------
# 词级 karaoke 数据层：段落词窗（G3 后半，2026-09-28）
# ---------------------------------------------------------------------------


def test_beat_words_populated_from_transcript_window() -> None:
    """段落词窗 = 同一词流按段落时间窗归集（与锚点解析同源同规则）。"""
    from app.schemas.agent_canvas_ad_media import (
        ReplicaBeatV2,
        ReplicaBlueprintContentV2,
    )

    blueprint = ReplicaBlueprintContentV2(
        beats=[
            ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=1.5),
            ReplicaBeatV2(beat_id="b2", start_seconds=1.5, end_seconds=3.0),
        ],
    )

    resolved = bp.resolve_word_anchors(blueprint, _WORDS)

    # 词中点归窗：了(1.4-1.6) 中点 1.5 → 归 b2
    assert [(w.text, w.start_seconds, w.end_seconds) for w in resolved.beats[0].words] == [
        ("别再", 0.2, 0.5),
        ("这样", 0.5, 0.9),
        ("洗脸", 0.9, 1.4),
    ]
    assert [(w.text, w.start_seconds, w.end_seconds) for w in resolved.beats[1].words] == [
        ("了", 1.4, 1.6),
    ]
    # 纯函数：原对象不变
    assert blueprint.beats[0].words == []


def test_beat_words_without_transcript_stay_empty() -> None:
    """无转录词流 → words 为空（行级字幕，向后兼容；不造假时间）。"""
    from app.schemas.agent_canvas_ad_media import (
        ReplicaBeatV2,
        ReplicaBlueprintContentV2,
    )

    blueprint = ReplicaBlueprintContentV2(
        beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=3.0)],
    )

    assert bp.resolve_word_anchors(blueprint, []) is blueprint
    assert blueprint.beats[0].words == []


def test_beat_words_and_anchor_resolution_coexist() -> None:
    """词窗填充与锚点解析互不干扰（同一次调用，两个出口）。"""
    from app.schemas.agent_canvas_ad_media import (
        ReplicaAnchorEventV2,
        ReplicaBeatV2,
        ReplicaBlueprintContentV2,
    )

    blueprint = ReplicaBlueprintContentV2(
        beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=3.0)],
        anchor_events=[
            ReplicaAnchorEventV2(event_id="e1", kind="sfx", beat_id="b1", trigger="这样洗脸"),
        ],
    )

    resolved = bp.resolve_word_anchors(blueprint, _WORDS)

    assert resolved.anchor_events[0].word == "这样洗脸"
    assert len(resolved.beats[0].words) == 4


def test_teardown_report_with_transcript_carries_beat_words() -> None:
    """有转录的报告 → 蓝图带词窗；无转录 → 空（默认路径零影响）。"""
    with_words = bp.blueprint_from_teardown(
        _report_with_transcript(),
        source_asset_id="asset-1",
        duration_seconds=12.0,
    )
    assert any(beat.words for beat in with_words.beats)

    without_words = bp.blueprint_from_teardown(
        _teardown_report(),
        source_asset_id="asset-1",
        duration_seconds=12.0,
    )
    assert all(beat.words == [] for beat in without_words.beats)


def test_adreplica_roundtrip_drops_derived_word_timings() -> None:
    """文档只存绑定不存派生时间：导出→导入后 words 为空（如实降级，不造假）。

    词窗时间是转录派生数据（与锚点词窗同纪律），进 .adreplica 会让手改文档
    时"时间看起来是真的"——宁可导入后退化为行级。
    """
    from app.services.replica import adreplica as adr

    blueprint = bp.blueprint_from_teardown(
        _report_with_transcript(),
        source_asset_id="asset-1",
        duration_seconds=12.0,
    )
    assert any(beat.words for beat in blueprint.beats)

    reimported = adr.blueprint_from_adreplica(adr.adreplica_from_blueprint(blueprint))

    assert all(beat.words == [] for beat in reimported.beats)
    # 台词文本（绑定）不丢
    assert any(beat.line.strip() for beat in reimported.beats)
