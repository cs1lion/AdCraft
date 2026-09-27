"""Unit tests for the ``.adreplica`` document layer (serialize + parse-back).

Covers: blueprint → .adreplica deterministic serialization, parse-back with
normalize 兜底, round-trip (engineering-standards §3: parse → serialize →
parse), XML escaping, structural rejection (unknown kinds / duplicate ids /
malformed XML), and the hypit "swap = edit a few lines" hand-edit recompile.

Design rationale: docs/plans/hypit-replica-research.md §3.5 + hypit 一手样例
（examples/interview/reference.svml，docs/guide/studio-temporal-windows.md
的 ``during=`` 结构锚定语义）。
"""

from __future__ import annotations

import pytest

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.services.replica import adreplica as adr
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
             "on_screen_text": "别再这样洗脸", "transition_to_next": "cut",
             "note": "同机位，换成用户商品"},
            {"index": 2, "start_seconds": 2.1, "end_seconds": 7.5, "shot_size": "medium",
             "camera_motion": "pushing_in", "subject_action": "七天涂抹对比",
             "on_screen_text": "", "transition_to_next": "dissolve", "note": ""},
        ],
        "beats": [
            {"role": "hook", "description": "错误示范抓注意力", "start_seconds": 0.0,
             "end_seconds": 3.0},
            {"role": "proof", "description": "连续7天对比", "start_seconds": 3.0,
             "end_seconds": 9.0},
        ],
        "rhythm": {"avg_shot_seconds": 4.0, "cut_points_seconds": [0.0, 2.1, 7.5],
                   "energy_curve": "前快后缓"},
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
# 序列化：语法形态
# ---------------------------------------------------------------------------


def test_serialize_is_deterministic(blueprint) -> None:
    assert adr.adreplica_from_blueprint(blueprint) == adr.adreplica_from_blueprint(blueprint)


def test_serialize_grammar_shape(blueprint) -> None:
    text = adr.adreplica_from_blueprint(blueprint)
    # 根元素：版本 + 文档种类 + 画幅/时长（§3.5 草案）
    assert '<advideo version="1" kind="replica-blueprint" aspect="9:16" duration="12">' in text
    # meta：来源/格式/目标/整片解读
    assert '<meta source="asset-1" format="product-comparison">' in text
    assert "<goal>换商品，保留人物与台词结构</goal>" in text
    assert "<reading>前3秒用错误示范制造焦虑" in text
    # cast：kind 槽位（非 hypit 的 provider 焊死元素）
    assert '<slot kind="product" label="商品"' in text
    # script：段落 + 角色 + 时窗引用（非秒数绝对值）
    assert '<beat id="b1" role="hook" dur="0-3">错误示范抓注意力</beat>' in text
    # timeline：镜头挂 during（hypit 结构锚定语义），start/dur 双记
    assert '<shot id="s1" size="closeup" motion="static" start="0" dur="2.1" cut="cut"' in text
    assert 'text="别再这样洗脸"' in text
    assert 'recreate="同机位，换成用户商品" during="b1">唇部特写</shot>' in text
    # events：元素名即事件类型，during 指向段落
    assert '<caption id="b1_caption" during="b1"' in text
    assert '<broll id="b1_shot1_broll" during="b1"' in text
    # rhythm / systems / constraints
    assert '<rhythm avg-shot="4" curve="前快后缓" cuts="0,2.1,7.5" />' in text
    assert '<systems captions="底部关键词高亮" music="轻快电子">' in text
    assert "<graphics>价格贴: 产品提到时弹入</graphics>" in text
    assert "<constraint>镜头边界为推断值</constraint>" in text


def test_serialize_v1_has_no_word_anchors_or_provider_elements(blueprint) -> None:
    """v1 边界：无词级锚语法位占用、无 provider 焊死元素（对标不照抄）。"""
    text = adr.adreplica_from_blueprint(blueprint)
    assert "<gpt:" not in text
    assert "<seedance:" not in text
    assert "<import" not in text


# ---------------------------------------------------------------------------
# 往返（engineering-standards §3：parse → serialize → parse）
# ---------------------------------------------------------------------------


def test_roundtrip_semantic_equality(blueprint) -> None:
    parsed = adr.blueprint_from_adreplica(adr.adreplica_from_blueprint(blueprint))
    # instantiated_script_node_id 是画布运行时状态，不属于文档真相源
    assert parsed.model_dump(exclude={"instantiated_script_node_id"}) == (
        blueprint.model_dump(exclude={"instantiated_script_node_id"})
    )
    assert parsed.instantiated_script_node_id is None


def test_roundtrip_text_idempotent(blueprint) -> None:
    text = adr.adreplica_from_blueprint(blueprint)
    assert adr.adreplica_from_blueprint(adr.blueprint_from_adreplica(text)) == text


def test_roundtrip_after_slot_update_and_anchor_removal(blueprint) -> None:
    updated = bp.apply_slot_updates(blueprint, {"product": "洗面奶A"})
    updated = bp.toggle_anchor_event(updated, "b1_caption", keep=False)

    parsed = adr.blueprint_from_adreplica(adr.adreplica_from_blueprint(updated))
    product = next(s for s in parsed.slots if s.kind == "product")
    assert product.replace_with == "洗面奶A"
    assert product.applied is True
    # keep=false 的事件：保留在 anchor_events（可恢复），但不挂在段落上
    removed = next(e for e in parsed.anchor_events if e.event_id == "b1_caption")
    assert removed.keep is False
    assert "b1_caption" not in parsed.beats[0].anchor_event_ids
    # 其余锚点联动保持
    assert "b1_shot1_cap" in parsed.beats[0].anchor_event_ids


def test_roundtrip_empty_blueprint() -> None:
    empty = ReplicaBlueprintContentV2()
    text = adr.adreplica_from_blueprint(empty)
    parsed = adr.blueprint_from_adreplica(text)
    assert parsed.model_dump(exclude={"instantiated_script_node_id"}) == (
        empty.model_dump(exclude={"instantiated_script_node_id"})
    )


def test_roundtrip_escapes_xml_and_keeps_anchor_like_text() -> None:
    report = _teardown_report()
    report["beats"][0]["description"] = '用<b>错误示范</b> & "引号"抓注意力 @{wrong-demo}'
    report["shots"][0]["subject_action"] = "特写 <面部> & '泡沫'"
    blueprint = bp.blueprint_from_teardown(report)
    parsed = adr.blueprint_from_adreplica(adr.adreplica_from_blueprint(blueprint))
    assert parsed.beats[0].description == report["beats"][0]["description"]
    assert parsed.shots[0].subject_action == report["shots"][0]["subject_action"]


# ---------------------------------------------------------------------------
# 解析拒绝：结构性错误显式报错（静默降级禁止）
# ---------------------------------------------------------------------------


def test_parse_rejects_malformed_xml() -> None:
    with pytest.raises(adr.AdReplicaParseError, match="Malformed XML"):
        adr.blueprint_from_adreplica("<advideo><script></advideo>")


def test_parse_rejects_wrong_root() -> None:
    with pytest.raises(adr.AdReplicaParseError, match="Unexpected root"):
        adr.blueprint_from_adreplica("<svml></svml>")


def test_parse_rejects_unsupported_version() -> None:
    with pytest.raises(adr.AdReplicaParseError, match="Unsupported .adreplica version"):
        adr.blueprint_from_adreplica('<advideo version="2"></advideo>')


def test_parse_rejects_wrong_document_kind() -> None:
    with pytest.raises(adr.AdReplicaParseError, match="Unexpected document kind"):
        adr.blueprint_from_adreplica('<advideo version="1" kind="full-production"></advideo>')


def test_parse_rejects_empty_document() -> None:
    with pytest.raises(adr.AdReplicaParseError, match="Empty"):
        adr.blueprint_from_adreplica("   ")


def test_parse_rejects_unknown_slot_kind() -> None:
    """变异锁定：hypit 词汇表（host/product 硬编码槽）不被接收——对标不照抄。"""
    text = (
        '<advideo version="1" kind="replica-blueprint">'
        '<cast><slot kind="host" label="Host"/></cast>'
        "</advideo>"
    )
    with pytest.raises(adr.AdReplicaParseError, match="Unknown slot kind"):
        adr.blueprint_from_adreplica(text)


def test_parse_rejects_unknown_event_element() -> None:
    text = (
        '<advideo version="1" kind="replica-blueprint">'
        '<events><gpt_image id="x" during="b1"/></events>'
        "</advideo>"
    )
    with pytest.raises(adr.AdReplicaParseError, match="Unknown event element"):
        adr.blueprint_from_adreplica(text)


def test_parse_rejects_duplicate_and_missing_ids() -> None:
    dup_beat = (
        '<advideo version="1" kind="replica-blueprint">'
        '<script><beat id="b1"/><beat id="b1"/></script>'
        "</advideo>"
    )
    with pytest.raises(adr.AdReplicaParseError, match="Duplicate beat id"):
        adr.blueprint_from_adreplica(dup_beat)

    no_id = (
        '<advideo version="1" kind="replica-blueprint">'
        '<script><beat role="hook"/></script>'
        "</advideo>"
    )
    with pytest.raises(adr.AdReplicaParseError, match="missing required id"):
        adr.blueprint_from_adreplica(no_id)


# ---------------------------------------------------------------------------
# normalize 兜底：数字/缺省容忍（SceneScript 经验）
# ---------------------------------------------------------------------------


def test_parse_normalizes_bad_numbers_and_defaults() -> None:
    text = (
        '<advideo version="1" kind="replica-blueprint">'
        '<script><beat id="b1" role="hook" dur="abc">文本</beat></script>'
        "<timeline><shot id=\"s1\" dur=\"xyz\"/></timeline>"
        '<events><broll id="e1" during="b1"/></events>'
        '<rhythm cuts="1,x,2.5"/>'
        "</advideo>"
    )
    parsed = adr.blueprint_from_adreplica(text)
    beat = parsed.beats[0]
    assert (beat.start_seconds, beat.end_seconds) == (0.0, 0.0)
    shot = parsed.shots[0]
    assert shot.index == 1
    assert (shot.start_seconds, shot.end_seconds) == (0.0, 0.0)
    assert shot.shot_size == "medium"  # 缺省兜底
    assert shot.transition_to_next == "cut"
    assert parsed.rhythm_cut_points_seconds == [1.0, 2.5]  # 非法片段丢弃
    # 无 meta 块时走默认值
    assert parsed.format_name == "short-video"
    assert parsed.source_video_asset_id == ""


# ---------------------------------------------------------------------------
# 手改文档 → 重编译（hypit "swap = 改几行" 的数据层证明）
# ---------------------------------------------------------------------------


def _line_with(text: str, needle: str) -> str:
    return next(line for line in text.splitlines() if needle in line)


def test_slot_applied_is_derived_from_replace_with(blueprint) -> None:
    """变异锁定：applied 不落盘，手改 replace-with 即视为已应用。"""
    text = adr.adreplica_from_blueprint(blueprint)
    filled = text.replace(
        'kind="product" label="商品" source="复刻目标：换商品，保留人物与台词结构"'
        ' replace-with=""',
        'kind="product" label="商品" source="复刻目标：换商品，保留人物与台词结构"'
        ' replace-with="洗面奶A"',
    )
    assert filled != text
    product = next(
        s for s in adr.blueprint_from_adreplica(filled).slots if s.kind == "product"
    )
    assert product.replace_with == "洗面奶A"
    assert product.applied is True
    # 原文档空替换 = 未应用
    original = next(
        s for s in adr.blueprint_from_adreplica(text).slots if s.kind == "product"
    )
    assert original.applied is False


def test_retiming_beat_keeps_anchor_attachment(blueprint) -> None:
    """hypit 核心卖点：改段落时窗，锚点跟随结构而非秒数。

    during=b1 是对段落的**引用**——改 beat 时窗不需要动任何锚点行，
    镜头/事件归属自动跟随（hypit: "structural span, no timeline drag"）。
    """
    text = adr.adreplica_from_blueprint(blueprint)
    retimed = text.replace('<beat id="b1" role="hook" dur="0-3">', '<beat id="b1" role="hook" dur="0-5">')
    assert retimed != text
    parsed = adr.blueprint_from_adreplica(retimed)
    assert parsed.beats[0].end_seconds == 5.0
    # 锚点事件一行未改，仍挂在 b1 上
    assert "b1_caption" in parsed.beats[0].anchor_event_ids
    assert "b1_shot1_cap" in parsed.beats[0].anchor_event_ids
    # 镜头归属同样跟随（镜头行也未改）
    again = adr.adreplica_from_blueprint(parsed)
    assert 'during="b1"' in _line_with(again, 'id="s1"')


# ---------------------------------------------------------------------------
# 行内词锚（@{id}词@{/id}：hypit mixed content 的 P2 落地）
# ---------------------------------------------------------------------------


def _word_anchored_blueprint(blueprint):
    """给 fixture 蓝图挂台词原文 + 解析好的词锚定。"""

    from app.schemas.agent_canvas_ad_media import (
        ReplicaBeatV2,
        ReplicaBlueprintContentV2,
    )
    line = "别再这样洗脸了"
    beats = [
        ReplicaBeatV2(
            beat_id=blueprint.beats[0].beat_id,
            role=blueprint.beats[0].role,
            description=blueprint.beats[0].description,
            line=line,
            start_seconds=blueprint.beats[0].start_seconds,
            end_seconds=blueprint.beats[0].end_seconds,
            anchor_event_ids=list(blueprint.beats[0].anchor_event_ids),
        ),
        *blueprint.beats[1:],
    ]
    events = [
        e.model_copy(update={"word": line}) if e.event_id == "b1_caption" else e
        for e in blueprint.anchor_events
    ]
    return ReplicaBlueprintContentV2(
        **{**blueprint.model_dump(exclude={"beats", "anchor_events"}),
           "beats": beats, "anchor_events": events}
    )


def test_inline_word_anchor_roundtrip(blueprint) -> None:
    """词锚 → <line> 行内标记 → 回读还原词绑定；时间为派生值不落盘。"""
    anchored = _word_anchored_blueprint(blueprint)
    text = adr.adreplica_from_blueprint(anchored)
    assert "<line>@{b1_caption}别再这样洗脸了@{/b1_caption}</line>" in text

    parsed = adr.blueprint_from_adreplica(text)
    caption = next(e for e in parsed.anchor_events if e.event_id == "b1_caption")
    assert caption.word == "别再这样洗脸了"
    # 时间跨度是词流的派生数据，不进文档（回读后待重新解析）
    assert (caption.word_start_seconds, caption.word_end_seconds) == (0.0, 0.0)
    # 行内标记剥离后台词原文无损
    assert parsed.beats[0].line == "别再这样洗脸了"
    # 再序列化幂等（标记重新生成，文本一致）
    assert adr.adreplica_from_blueprint(parsed) == text


def test_word_attr_fallback_when_word_not_in_line(blueprint) -> None:
    """词不在台词里（数据漂移/手工构造）→ 兜底写进 word 属性，往返无损。"""
    anchored = _word_anchored_blueprint(blueprint)
    anchored = anchored.model_copy(
        update={
            "anchor_events": [
                e.model_copy(update={"word": "口头禅"}) if e.event_id == "b1_caption" else e
                for e in anchored.anchor_events
            ]
        }
    )
    text = adr.adreplica_from_blueprint(anchored)
    assert 'word="口头禅"' in text
    parsed = adr.blueprint_from_adreplica(text)
    caption = next(e for e in parsed.anchor_events if e.event_id == "b1_caption")
    assert caption.word == "口头禅"


def test_inline_anchor_unknown_event_rejected() -> None:
    """行内锚引用未声明的事件 id → 显式报错（文档完整性）。

    直接构造原始文档：序列化器会把模型数据里的未声明标记规范掉，
    这里锁的是解析端对**文档里**幽灵锚的完整性检查。
    """
    text = (
        '<advideo version="1" kind="replica-blueprint">'
        "<script><beat id=\"b1\"><line>词@{ghost}引用@{/ghost}</line></beat></script>"
        "</advideo>"
    )
    with pytest.raises(adr.AdReplicaParseError, match="unknown event"):
        adr.blueprint_from_adreplica(text)


def test_hand_edit_inline_anchor_recompiles(blueprint) -> None:
    """hypit 式手改：台词不动，只挪锚点词的覆盖范围——改一行 = 换词绑定。"""
    anchored = _word_anchored_blueprint(blueprint)
    text = adr.adreplica_from_blueprint(anchored)
    edited = text.replace(
        "@{b1_caption}别再这样洗脸了@{/b1_caption}",
        "别再@{b1_caption}这样洗脸@{/b1_caption}了",
    )
    parsed = adr.blueprint_from_adreplica(edited)
    caption = next(e for e in parsed.anchor_events if e.event_id == "b1_caption")
    assert caption.word == "这样洗脸"
    assert parsed.beats[0].line == "别再这样洗脸了"


def test_beat_without_line_has_no_line_element(blueprint) -> None:
    """无台词的段落不产生 <line> 语法位（词汇表最小化）。"""
    text = adr.adreplica_from_blueprint(blueprint)
    assert "<line>" not in text
    parsed = adr.blueprint_from_adreplica(text)
    assert all(beat.line == "" for beat in parsed.beats)


def test_hand_edit_add_and_remove_event_recompiles(blueprint) -> None:
    text = adr.adreplica_from_blueprint(blueprint)

    # 删一行 = 移除锚点事件（联动自动失效）
    without = "\n".join(
        line for line in text.splitlines() if 'id="b1_caption"' not in line
    ) + "\n"
    parsed = adr.blueprint_from_adreplica(without)
    assert all(e.event_id != "b1_caption" for e in parsed.anchor_events)
    assert "b1_caption" not in parsed.beats[0].anchor_event_ids

    # 加一行 = 新增锚点事件（during 指向段落即自动挂上）
    added = without.replace(
        "</events>",
        '    <sfx id="e_whoosh" during="b2" trigger="落版">落版 whoosh</sfx>\n  </events>',
    )
    recompiled = adr.blueprint_from_adreplica(added)
    new_event = next(e for e in recompiled.anchor_events if e.event_id == "e_whoosh")
    assert new_event.kind == "sfx"
    assert new_event.beat_id == "b2"
    assert new_event.hint == "落版 whoosh"
    assert "e_whoosh" in recompiled.beats[1].anchor_event_ids

    # 重编译结果可再序列化（往返闭合）
    again = adr.adreplica_from_blueprint(recompiled)
    assert 'id="e_whoosh"' in again


# ---------------------------------------------------------------------------
# 文件名建议
# ---------------------------------------------------------------------------


def test_filename_slug(blueprint) -> None:
    assert adr.adreplica_filename(blueprint) == "product-comparison.adreplica"
    weird = blueprint.model_copy(update={"format_name": "产品 对比!"})
    assert adr.adreplica_filename(weird) == "-.adreplica" or "-" in adr.adreplica_filename(weird)
    empty = blueprint.model_copy(update={"format_name": ""})
    assert adr.adreplica_filename(empty) == "replica-blueprint.adreplica"


# ---------------------------------------------------------------------------
# HTTP 端点（最小 app + 单 router，参考 test_replica_teardown 模式）
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import replica as replica_endpoint

    app = FastAPI()
    app.include_router(replica_endpoint.router)
    return TestClient(app)


def test_export_endpoint_returns_document(client, blueprint) -> None:
    response = client.post(
        "/replica/blueprint/export",
        json={"blueprint": blueprint.model_dump(mode="json")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["filename"] == "product-comparison.adreplica"
    assert "<advideo version=\"1\" kind=\"replica-blueprint\"" in body["adreplica"]
    assert '<beat id="b1" role="hook"' in body["adreplica"]


def test_export_endpoint_rejects_invalid_blueprint(client) -> None:
    response = client.post(
        "/replica/blueprint/export",
        json={"blueprint": {"blueprint_version": "replica-blueprint-v1", "slots": "oops"}},
    )
    assert response.status_code == 422, response.text
    assert "Invalid replica blueprint content" in response.text


def test_import_endpoint_recompiles_document(client, blueprint) -> None:
    text = adr.adreplica_from_blueprint(blueprint)
    response = client.post("/replica/blueprint/import", json={"adreplica": text})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    # 回读的蓝图是"重新编译"所得：画布运行时指针复位为 None（文档真相源
    # 不含实例化状态），其余字段与导出前完全一致
    assert body["blueprint"] == blueprint.model_dump(mode="json")
    assert body["blueprint"]["instantiated_script_node_id"] is None
    # 响应与 /blueprint 同形：replica_script 可直接进 script 节点
    assert "# 复刻脚本" in body["replica_script"]


def test_import_endpoint_rejects_structural_errors(client) -> None:
    response = client.post(
        "/replica/blueprint/import",
        json={"adreplica": "<advideo version=\"1\"><cast><slot kind=\"host\"/></cast></advideo>"},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["error_type"] == "adreplica_parse"
    assert "Unknown slot kind" in detail["error"]


def test_full_chain_report_to_document_and_back(client) -> None:
    """报告 → 蓝图 → 导出 → 手改文本 → 导入：整链闭环可用。"""
    built = client.post(
        "/replica/blueprint",
        json={
            "report": _teardown_report(),
            "source_video_asset_id": "asset-1",
            "duration_seconds": 12.0,
            "aspect": "9:16",
            "replica_goal": "换商品",
        },
    )
    assert built.status_code == 200, built.text
    original = built.json()["blueprint"]

    exported = client.post(
        "/replica/blueprint/export", json={"blueprint": original}
    )
    text = exported.json()["adreplica"]

    # hypit 式手改：换槽位替换值 + 加一个 sfx 锚点事件
    edited = text.replace(
        '<slot kind="product" label="商品" source="复刻目标：换商品" replace-with=""',
        '<slot kind="product" label="商品" source="复刻目标：换商品" replace-with="洗面奶A"',
    ).replace(
        "</events>",
        '    <sfx id="e_manual" during="b2" trigger="落版">whoosh</sfx>\n  </events>',
    )
    assert edited != text  # 手改确实生效

    imported = client.post("/replica/blueprint/import", json={"adreplica": edited})
    assert imported.status_code == 200, imported.text
    recompiled = imported.json()["blueprint"]
    product = next(s for s in recompiled["slots"] if s["kind"] == "product")
    assert product["replace_with"] == "洗面奶A"
    assert product["applied"] is True
    assert "e_manual" in recompiled["beats"][1]["anchor_event_ids"]
    # 未手改的字段与原蓝图一致（往返无损）
    assert recompiled["beats"][0]["description"] == original["beats"][0]["description"]
    assert recompiled["shots"] == original["shots"]
