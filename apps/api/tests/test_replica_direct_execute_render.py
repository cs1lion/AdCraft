"""Unit tests for direct-execute R1 subtitle-track render plan (ADR 0010).

Covers: feasible blueprint → WorkflowV2Timeline with subtitle cues + optional
bgm/sfx audio clips (zero-model-cost canonical timeline), non-feasible
blueprint → rejected list + empty timeline, cue merging, word-anchor
precedence over beat-level timing, and the needs_placeholder_video honesty
flag (renderer requires at least one enabled video clip). Pure functions,
no IO, no LLM, no HTTP.
"""

from __future__ import annotations

import pytest

from app.schemas.agent_canvas_ad_media import (
    ReplicaAnchorEventV2,
    ReplicaBeatV2,
    ReplicaBlueprintContentV2,
    ReplicaShotV2,
    ReplicaSlotV2,
)
from app.schemas.workflow_v2 import WorkflowV2Timeline
from app.services.replica.direct_execute import DirectExecutePlan, plan_direct_execute
from app.services.replica.direct_execute_render import (
    BGM_TRACK_ID,
    SFX_TRACK_ID,
    SUBTITLE_TRACK_ID,
    plan_direct_execute_render,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _blueprint(
    *,
    shots: list[ReplicaShotV2] | None = None,
    beats: list[ReplicaBeatV2] | None = None,
    anchor_events: list[ReplicaAnchorEventV2] | None = None,
    slots: list[ReplicaSlotV2] | None = None,
    systems_music: str = "",
    systems_sfx: list[str] | None = None,
    systems_captions: str = "",
) -> ReplicaBlueprintContentV2:
    return ReplicaBlueprintContentV2(
        source_video_asset_id="asset-1",
        duration_seconds=12.0,
        aspect="9:16",
        slots=slots
        if slots is not None
        else [ReplicaSlotV2(kind="product", label="商品", source_value="原片商品")],
        shots=shots or [],
        beats=beats or [],
        anchor_events=anchor_events or [],
        systems_captions=systems_captions,
        systems_music=systems_music,
        systems_sfx=systems_sfx or [],
    )


def _feasible_plan() -> DirectExecutePlan:
    """纯字幕片（零生成步骤）的可行性门结果。"""
    return DirectExecutePlan(
        feasible=True,
        blockers=(),
        zero_model_steps=(
            {"step": "captions", "detail": "字幕 → drawtext"},
            {"step": "editing", "detail": "剪辑合成"},
        ),
        generation_steps=(),
    )


def _non_feasible_plan() -> DirectExecutePlan:
    return DirectExecutePlan(
        feasible=False,
        blockers=(),
        zero_model_steps=({"step": "editing", "detail": "剪辑合成"},),
        generation_steps=(
            {"step": "shot_1", "detail": "镜头画面需生成"},
            {"step": "voice", "detail": "台词语音合成"},
        ),
    )


def _subtitle_clips(plan) -> list:
    return [c for c in plan.timeline.clips if c.track_id == SUBTITLE_TRACK_ID]


def _audio_clips(plan) -> list:
    return [
        c for c in plan.timeline.clips if c.track_id in (BGM_TRACK_ID, SFX_TRACK_ID)
    ]


# ---------------------------------------------------------------------------
# Feasible blueprint → render plan
# ---------------------------------------------------------------------------


def test_feasible_pure_text_shots_yield_subtitle_cues() -> None:
    """纯屏上文字镜头（无动作）→ subtitle cue，总时长取内容镜头末端。"""
    blueprint = _blueprint(
        shots=[
            ReplicaShotV2(
                index=1,
                start_seconds=0.0,
                end_seconds=3.0,
                on_screen_text="别再这样洗脸",
                subject_action="",
                transition_to_next="cut",
            ),
            # 第二个纯空白镜头（无文字无动作）不应拉长时间线
            ReplicaShotV2(
                index=2, start_seconds=3.0, end_seconds=7.5, subject_action=""
            ),
        ],
    )
    plan = plan_direct_execute_render(blueprint, _feasible_plan())
    assert plan.feasible is True
    assert isinstance(plan.timeline, WorkflowV2Timeline)
    # 空白镜头不计入内容末端
    assert plan.timeline.duration_seconds == 3.0
    subs = _subtitle_clips(plan)
    assert len(subs) == 1
    assert subs[0].text == "别再这样洗脸"
    assert subs[0].start_time == 0.0
    assert subs[0].duration == 3.0
    # 纯字幕片没有画面源 → 如实标注需占位 video clip
    assert plan.needs_placeholder_video is True
    assert plan.subtitle_cue_count == 1


def test_feasible_beat_line_falls_back_to_beat_time_window() -> None:
    """段落有台词但词锚未解析 → 用段落时间窗兜底（不造时间）。"""
    blueprint = _blueprint(
        beats=[
            ReplicaBeatV2(
                beat_id="b1",
                role="hook",
                line="别再这样洗脸了",
                start_seconds=0.0,
                end_seconds=3.0,
            ),
        ]
    )
    plan = plan_direct_execute_render(blueprint, _feasible_plan())
    assert plan.feasible is True
    subs = _subtitle_clips(plan)
    assert len(subs) == 1
    assert subs[0].text == "别再这样洗脸了"
    assert subs[0].start_time == 0.0
    assert subs[0].duration == 3.0


def test_word_anchor_precedence_over_beat_time_window() -> None:
    """词锚已解析 → cue 窗口取词窗（比段落时间窗更紧）。"""
    blueprint = _blueprint(
        beats=[
            ReplicaBeatV2(
                beat_id="b1",
                role="hook",
                line="别再这样洗脸了 你的毛孔会越来越大",
                start_seconds=0.0,
                end_seconds=6.0,
                anchor_event_ids=["b1_cap"],
            ),
        ],
        anchor_events=[
            ReplicaAnchorEventV2(
                event_id="b1_cap",
                trigger="别再这样洗脸",
                beat_id="b1",
                kind="caption",
                word="别再这样洗脸",
                word_start_seconds=0.2,
                word_end_seconds=1.5,
            ),
        ]
    )
    plan = plan_direct_execute_render(blueprint, _feasible_plan())
    assert len(_subtitle_clips(plan)) == 1
    cue = _subtitle_clips(plan)[0]
    assert cue.start_time == 0.2
    assert cue.duration == 1.3  # 1.5 - 0.2
    assert cue.text == "别再这样洗脸了 你的毛孔会越来越大"


def test_bgm_and_sfx_clips_present_when_declared() -> None:
    blueprint = _blueprint(
        beats=[
            ReplicaBeatV2(
                beat_id="b1", role="body", line="hello",
                start_seconds=0.0, end_seconds=4.0,
            )
        ],
        systems_music="轻快电子",
        systems_sfx=["切换 whoosh", "产品弹入 pop"],
    )
    plan = plan_direct_execute_render(blueprint, _feasible_plan())
    audios = {c.track_id: c for c in _audio_clips(plan)}
    assert BGM_TRACK_ID in audios
    assert audios[BGM_TRACK_ID].text == "轻快电子"
    assert "library-intent" in audios[BGM_TRACK_ID].metadata["label"]
    assert SFX_TRACK_ID in audios
    assert "whoosh" in audios[SFX_TRACK_ID].text


def test_no_bgm_sfx_when_undclared() -> None:
    blueprint = _blueprint(
        beats=[
            ReplicaBeatV2(
                beat_id="b1", role="body", line="hello",
                start_seconds=0.0, end_seconds=4.0,
            )
        ]
    )
    plan = plan_direct_execute_render(blueprint, _feasible_plan())
    assert _audio_clips(plan) == []
    # audio 轨也不该出现
    track_ids = [t.track_id for t in plan.timeline.tracks]
    assert BGM_TRACK_ID not in track_ids
    assert SFX_TRACK_ID not in track_ids


# ---------------------------------------------------------------------------
# Non-feasible blueprint → rejected, empty timeline
# ---------------------------------------------------------------------------


def test_non_feasible_returns_rejected_empty_timeline() -> None:
    blueprint = _blueprint(
        shots=[
            ReplicaShotV2(
                index=1, start_seconds=0.0, end_seconds=3.0,
                subject_action="错误示范动作",
            ),
        ],
        beats=[
            ReplicaBeatV2(
                beat_id="b1", role="hook", line="",
                start_seconds=0.0, end_seconds=3.0,
            ),
        ],
    )
    plan = plan_direct_execute_render(blueprint, _non_feasible_plan())
    assert plan.feasible is False
    assert plan.timeline.clips == []
    assert plan.needs_placeholder_video is False
    # rejected 含 dict step 描述
    assert any("shot_1" in str(item) for item in plan.rejected)
    assert any("voice" in str(item) for item in plan.rejected)


# ---------------------------------------------------------------------------
# Cue merging: adjacent cues separated by < MIN_CUE_GAP merge
# ---------------------------------------------------------------------------


def test_short_gap_cues_merge_into_one() -> None:
    """两条相邻 cue 间隔 < 0.4s → 合并为一条（字幕不闪跳）。"""
    blueprint = _blueprint(
        beats=[
            ReplicaBeatV2(
                beat_id="b1", role="hook", line="第一句",
                start_seconds=0.0, end_seconds=2.0,
            ),
            ReplicaBeatV2(
                beat_id="b2", role="body", line="第二句",
                start_seconds=2.1, end_seconds=4.0,  # 间隔 0.1s < 0.4s
            ),
        ]
    )
    plan = plan_direct_execute_render(blueprint, _feasible_plan())
    subs = _subtitle_clips(plan)
    assert len(subs) == 1
    assert subs[0].text == "第一句\n第二句"
    assert subs[0].start_time == 0.0
    assert subs[0].duration == 4.0


def test_wide_gap_cues_stay_separate() -> None:
    """两条 cue 间隔 ≥ 0.4s → 各自独立。"""
    blueprint = _blueprint(
        beats=[
            ReplicaBeatV2(
                beat_id="b1", role="hook", line="第一句",
                start_seconds=0.0, end_seconds=2.0,
            ),
            ReplicaBeatV2(
                beat_id="b2", role="body", line="第二句",
                start_seconds=3.0, end_seconds=5.0,  # 间隔 1.0s ≥ 0.4s
            ),
        ]
    )
    plan = plan_direct_execute_render(blueprint, _feasible_plan())
    subs = _subtitle_clips(plan)
    assert len(subs) == 2
    assert subs[0].text == "第一句"
    assert subs[1].text == "第二句"


# ---------------------------------------------------------------------------
# 画幅映射
# ---------------------------------------------------------------------------


def test_aspect_916_maps_to_v2_aspect_and_resolution() -> None:
    blueprint = _blueprint(
        beats=[
            ReplicaBeatV2(
                beat_id="b1", role="body", line="hi",
                start_seconds=0.0, end_seconds=2.0,
            )
        ]
    )
    plan = plan_direct_execute_render(blueprint, _feasible_plan())
    assert plan.timeline.aspect_ratio == "9:16"
    assert plan.timeline.resolution == {"width": 720, "height": 1280}


# ---------------------------------------------------------------------------
# Integration: plan_direct_execute + plan_direct_execute_render round-trip
# ---------------------------------------------------------------------------


def test_gate_and_render_agree_on_pure_text_blueprint() -> None:
    """可行性门判 feasible + 渲染计划出 cues（端到端纯函数闭环）。"""
    blueprint = _blueprint(
        shots=[
            ReplicaShotV2(
                index=1, start_seconds=0.0, end_seconds=5.0,
                on_screen_text="第7天", subject_action="",
            ),
        ],
        beats=[
            ReplicaBeatV2(
                beat_id="b1", role="body", line="",
                start_seconds=0.0, end_seconds=5.0,
            ),
        ],
        systems_music="轻快电子",
    )
    gate = plan_direct_execute(blueprint)
    assert gate.feasible is True, (
        f"gate 判 non-feasible: blockers={gate.blockers} "
        f"generation={gate.generation_steps}"
    )
    plan = plan_direct_execute_render(blueprint, gate)
    assert plan.feasible is True
    subs = _subtitle_clips(plan)
    assert len(subs) == 1
    assert subs[0].text == "第7天"
    assert _audio_clips(plan)  # BGM 轨意图在
    assert plan.needs_placeholder_video is True


def test_blueprint_with_generation_slot_is_non_feasible() -> None:
    """槽位替换已应用 → 需生成 → 不可零模型费直出。"""
    blueprint = _blueprint(
        slots=[
            ReplicaSlotV2(
                kind="product", label="商品",
                source_value="原片商品", replace_with="asset:prod_001",
                applied=True,
            ),
        ],
        shots=[
            ReplicaShotV2(
                index=1, start_seconds=0.0, end_seconds=5.0,
                on_screen_text="第7天", subject_action="",
            ),
        ],
        beats=[
            ReplicaBeatV2(
                beat_id="b1", role="body", line="",
                start_seconds=0.0, end_seconds=5.0,
            ),
        ],
    )
    gate = plan_direct_execute(blueprint)
    assert gate.feasible is False
    plan = plan_direct_execute_render(blueprint, gate)
    assert plan.feasible is False
    assert plan.timeline.clips == []
