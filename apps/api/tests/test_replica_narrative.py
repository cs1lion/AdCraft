"""Unit tests for the G4 narrative token layer (hypit P1 主项).

锁定三层：

- normalize/tokenize：授权拼写与切分规则（CJK 字符级、拉丁词级）；
- Narrative/ anchors/ selection：6 种 anchor 的边界语义、selection =
  anchor 对间 token 区间、**与帧时间解耦**（改任何秒数字段 selection 逐
  字节不变——这是 G4 的标志性性质）；
- 定位与投影：normalized 文本定位（含 occurrence 选第几次出现）、秒数是
  词流的投影（没有词流 = 没有测量，返回 None 而不是编造）。

另见 test_replica_blueprint.py 的接线测试（锚点记 token 区间、重投影、
文档往返丢弃派生 id）。
"""

from __future__ import annotations

import pytest

from app.schemas.agent_canvas_ad_media import (
    ReplicaBeatV2,
    ReplicaBlueprintContentV2,
)
from app.services.replica import narrative as nar


# ---------------------------------------------------------------------------
# normalize / tokenize
# ---------------------------------------------------------------------------


def test_normalize_strips_punctuation_case_and_width() -> None:
    assert nar.normalize_text("别再这样洗脸了，真的。") == "别再这样洗脸了真的"
    assert nar.normalize_text("Hello, World!") == "helloworld"
    # NFKC：全角字母数字 → 半角后再比
    assert nar.normalize_text("ＨＥＬＬＯ") == "hello"
    assert nar.normalize_text("  \t\n ") == ""


def test_tokenize_cjk_is_character_level_and_latin_is_word_level() -> None:
    assert nar.tokenize("别再这样洗脸了，真的。") == (
        "别", "再", "这", "样", "洗", "脸", "了", "真", "的",
    )
    assert nar.tokenize("Hello, World!") == ("Hello", "World")
    assert nar.tokenize("第7天 DAY 7") == ("第", "7", "天", "DAY", "7")
    assert nar.tokenize("") == ()
    assert nar.tokenize("。。。") == ()


# ---------------------------------------------------------------------------
# Narrative 与 6 种 anchor
# ---------------------------------------------------------------------------


def _blueprint(**beat_overrides) -> ReplicaBlueprintContentV2:
    payload = {
        "beats": [
            ReplicaBeatV2(
                beat_id="b1",
                role="hook",
                start_seconds=0.0,
                end_seconds=3.0,
                line="别再这样洗脸了",
            ),
            ReplicaBeatV2(
                beat_id="b2",
                role="proof",
                start_seconds=3.0,
                end_seconds=9.0,
                line="连洗七天",
            ),
        ],
    }
    payload.update(beat_overrides)
    return ReplicaBlueprintContentV2(**payload)


def test_narrative_from_blueprint_tokens_come_from_line_only() -> None:
    """token 只来自授权文本（line）——词流是对齐源不是 token 源。

    这是 G4 实现中抓到的真缺陷的锁定：曾用"词流优先"做 token 源，导致
    解析时（words 未填）与重投影时（words 已填）是两套 token id 空间，
    binding 必然丢失。
    """
    beat = ReplicaBeatV2(
        beat_id="b1",
        start_seconds=0.0,
        end_seconds=3.0,
        line="别再这样洗脸了",
        words=[
            {"text": "别再", "start_seconds": 0.2, "end_seconds": 0.5},
            {"text": "这样", "start_seconds": 0.5, "end_seconds": 0.9},
        ],
    )
    narrative = nar.narrative_from_blueprint(
        ReplicaBlueprintContentV2(beats=[beat])
    )
    assert [token.text for token in narrative.segment_tokens("b1")] == [
        "别", "再", "这", "样", "洗", "脸", "了",
    ]
    # 空 line 的段落（纯字幕片）没有 token——锚点走文本+秒数的兼容路径
    empty = ReplicaBlueprintContentV2(
        beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=3.0)]
    )
    assert nar.narrative_from_blueprint(empty).tokens == ()


def test_all_six_anchor_kinds_resolve_to_token_boundaries() -> None:
    narrative = nar.narrative_from_blueprint(_blueprint())

    # program 起止：整个授权序
    assert nar.anchor_token_boundary(narrative, nar.PROGRAM_START) == 0
    assert nar.anchor_token_boundary(narrative, nar.PROGRAM_END) == len(narrative.tokens)
    # segment 起止
    assert nar.anchor_token_boundary(narrative, nar.segment_start_anchor("b1")) == 0
    assert nar.anchor_token_boundary(narrative, nar.segment_end_anchor("b1")) == 7
    assert nar.anchor_token_boundary(narrative, nar.segment_start_anchor("b2")) == 7
    # token 起止（闭区间 → end 边界 +1）
    assert nar.anchor_token_boundary(narrative, nar.token_start_anchor("b1#2")) == 2
    assert nar.anchor_token_boundary(narrative, nar.token_end_anchor("b1#5")) == 6
    # kind 元数据
    assert nar.anchor_kind(nar.PROGRAM_START) == "program-start"
    assert nar.anchor_kind(nar.segment_end_anchor("b1")) == "segment-end"
    assert nar.anchor_kind(nar.token_start_anchor("b1#2")) == "token-start"
    assert nar.anchor_kind(nar.token_end_anchor("b1#2")) == "token-end"


def test_unknown_anchor_raises() -> None:
    narrative = nar.narrative_from_blueprint(_blueprint())
    with pytest.raises(KeyError):
        nar.anchor_token_boundary(narrative, "token:nope#9:start")
    with pytest.raises(KeyError):
        nar.anchor_token_boundary(narrative, "segment:nope:start")
    with pytest.raises(KeyError):
        nar.anchor_kind("bogus")


def test_selection_is_a_token_range_between_two_anchors() -> None:
    narrative = nar.narrative_from_blueprint(_blueprint())

    selected = nar.narrative_selection_tokens(
        narrative,
        nar.token_start_anchor("b1#2"),
        nar.token_end_anchor("b1#5"),
    )

    assert [token.token_id for token in selected] == ["b1#2", "b1#3", "b1#4", "b1#5"]
    assert nar.selection_text(selected) == "这样洗脸"
    # segment 级 selection：整段
    whole_segment = nar.narrative_selection_tokens(
        narrative,
        nar.segment_start_anchor("b2"),
        nar.segment_end_anchor("b2"),
    )
    assert nar.selection_text(whole_segment) == "连洗七天"


def test_selection_rejects_invalid_anchor_order() -> None:
    narrative = nar.narrative_from_blueprint(_blueprint())
    with pytest.raises(ValueError):
        nar.narrative_selection_tokens(
            narrative,
            nar.token_end_anchor("b1#5"),
            nar.token_start_anchor("b1#2"),
        )


def test_selection_is_independent_of_frame_timing() -> None:
    """标志性性质：把蓝图上所有秒数字段改脏，selection 逐字节不变。

    时间只是投影——这正是 hypit "independent of material placement and
    frame timing" 的落地证明。
    """
    blueprint = _blueprint()
    narrative = nar.narrative_from_blueprint(blueprint)

    def selection_ids(target) -> list[str]:
        return [
            token.token_id
            for token in nar.narrative_selection_tokens(
                target,
                nar.token_start_anchor("b2#1"),
                nar.token_end_anchor("b2#3"),
            )
        ]

    before = selection_ids(narrative)
    mangled = blueprint.model_copy(
        update={
            "beats": [
                beat.model_copy(
                    update={
                        "start_seconds": beat.start_seconds + 500.0,
                        "end_seconds": beat.end_seconds + 900.0,
                    }
                )
                for beat in blueprint.beats
            ]
        }
    )
    after = selection_ids(nar.narrative_from_blueprint(mangled))

    assert before == after == ["b2#1", "b2#2", "b2#3"]


# ---------------------------------------------------------------------------
# 定位与投影
# ---------------------------------------------------------------------------


def test_token_range_for_text_matches_normalized() -> None:
    narrative = nar.narrative_from_blueprint(
        _blueprint(beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=3.0, line="别再这样洗脸了，真的。")])
    )

    # 带标点的查询命中同一个区间（normalized 匹配）
    assert nar.token_range_for_text(narrative, "b1", "这样洗脸") == ("b1#2", "b1#5")
    assert nar.token_range_for_text(narrative, "b1", "这样，洗脸！") == ("b1#2", "b1#5")
    assert nar.token_range_for_text(narrative, "b1", "不存在的词") is None


def test_token_range_for_text_occurrence_selects_second_hit() -> None:
    """重复子串不再永远锁死第一次——锚点可指向第二次出现。"""
    narrative = nar.narrative_from_blueprint(
        _blueprint(
            beats=[
                ReplicaBeatV2(
                    beat_id="b1", start_seconds=0.0, end_seconds=3.0, line="洗脸洗脸"
                )
            ]
        )
    )
    assert nar.token_range_for_text(narrative, "b1", "洗脸", occurrence=0) == ("b1#0", "b1#1")
    assert nar.token_range_for_text(narrative, "b1", "洗脸", occurrence=1) == ("b1#2", "b1#3")
    assert nar.token_range_for_text(narrative, "b1", "洗脸", occurrence=2) is None


def test_project_seconds_projects_token_range_onto_word_stream() -> None:
    beat = ReplicaBeatV2(
        beat_id="b1",
        start_seconds=0.0,
        end_seconds=3.0,
        line="别再这样洗脸了",
        words=[
            {"text": "别再", "start_seconds": 0.2, "end_seconds": 0.5},
            {"text": "这样", "start_seconds": 0.5, "end_seconds": 0.9},
            {"text": "洗脸", "start_seconds": 0.9, "end_seconds": 1.4},
            {"text": "了", "start_seconds": 1.4, "end_seconds": 1.6},
        ],
    )
    narrative = nar.narrative_from_blueprint(ReplicaBlueprintContentV2(beats=[beat]))
    selected = nar.narrative_selection_tokens(
        narrative, nar.token_start_anchor("b1#2"), nar.token_end_anchor("b1#5")
    )
    assert nar.project_seconds(beat, selected) == (0.5, 1.4)


def test_project_seconds_returns_none_without_measurement() -> None:
    """没有词流/文本不在词流里 → None（没有测量，不插值不编造）。"""
    narrative = nar.narrative_from_blueprint(_blueprint())
    selected = nar.narrative_selection_tokens(
        narrative, nar.token_start_anchor("b1#0"), nar.token_end_anchor("b1#2")
    )
    no_words = ReplicaBlueprintContentV2(beats=_blueprint().beats).beats[0]
    assert nar.project_seconds(no_words, selected) is None

    other_words = ReplicaBeatV2(
        beat_id="b1",
        start_seconds=0.0,
        end_seconds=3.0,
        line="别再这样洗脸了",
        words=[{"text": "完全不同的内容", "start_seconds": 1.0, "end_seconds": 2.0}],
    )
    assert nar.project_seconds(other_words, selected) is None


def test_narrative_summary_reports_scale() -> None:
    summary = nar.narrative_summary(nar.narrative_from_blueprint(_blueprint()))
    assert summary == {
        "narrative_id": "replica",
        "segments": 2,
        "tokens": 11,
        "tokens_per_segment": {"b1": 7, "b2": 4},
    }
