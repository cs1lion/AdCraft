"""Unit tests for direct-execute R1 subtitle-track render plan (ADR 0010).

Covers: feasible blueprint → WorkflowV2Timeline with subtitle cues + optional
bgm/sfx audio clips (zero-model-cost canonical timeline), non-feasible
blueprint → rejected list + empty timeline, cue merging, word-anchor
precedence over beat-level timing, and the needs_placeholder_video honesty
flag (renderer requires at least one enabled video clip). Pure functions,
no IO, no LLM, no HTTP.
"""

from __future__ import annotations

from app.schemas.agent_canvas_ad_media import (
    ReplicaAnchorEventV2,
    ReplicaBeatV2,
    ReplicaBlueprintContentV2,
    ReplicaShotV2,
    ReplicaSlotV2,
)
from app.schemas.workflow_v2 import WorkflowV2Timeline
from app.services.replica.direct_execute import DirectExecutePlan, plan_direct_execute
from app.services.replica import direct_execute_render as de
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


# ---------------------------------------------------------------------------
# B v1：库素材待解析意图透出 + 人工解析回填
# ---------------------------------------------------------------------------


def test_render_plan_exposes_unresolved_library_intents() -> None:
    blueprint = _blueprint(beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=3.0)],
                           shots=[ReplicaShotV2(index=1, start_seconds=0.0, end_seconds=3.0,
                                                on_screen_text="HALF PRICE SALE")],
                           systems_music="促销电子", systems_sfx=["whoosh"])
    gate = plan_direct_execute(blueprint)
    plan = de.plan_direct_execute_render(blueprint, gate)
    unresolved = plan.unresolved
    kinds = {u["clip_id"].split("_")[0] for u in unresolved}
    assert kinds == {"bgm", "sfx"}  # 两个意图 clip 都待解析
    for entry in unresolved:
        assert entry["duration_seconds"] > 0
        assert entry["library_hint"]
        assert entry["intent"]


def test_resolve_library_clip_fills_and_enables() -> None:
    blueprint = _blueprint(beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=3.0)],
                           shots=[ReplicaShotV2(index=1, start_seconds=0.0, end_seconds=3.0,
                                                on_screen_text="HALF PRICE SALE")],
                           systems_music="促销电子", systems_sfx=["whoosh"])
    gate = plan_direct_execute(blueprint)
    plan = de.plan_direct_execute_render(blueprint, gate)
    timeline = plan.timeline

    resolved = de.resolve_library_clip(
        timeline,
        clip_id="bgm_system",
        asset_id="asset_bgm_1",
        version_id="ver_bgm_1",
    )
    clip = next(c for c in resolved.clips if c.clip_id == "bgm_system")
    assert clip.enabled is True
    assert clip.source_asset_id == "asset_bgm_1"
    assert clip.source_version_id == "ver_bgm_1"
    assert clip.metadata["library_resolved"] is True
    # 纯函数：原时间线不变
    original = next(c for c in timeline.clips if c.clip_id == "bgm_system")
    assert original.enabled is False
    # 解析后的意图不再出现在待解析清单
    assert all(u["clip_id"] != "bgm_system" for u in de.unresolved_intents_of(resolved))


def test_resolve_library_clip_rejects_non_sentinel() -> None:
    """已启用/非哨兵 clip 不接受回填（防误覆盖）。"""
    blueprint = _blueprint(beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=3.0)],
                           shots=[ReplicaShotV2(index=1, start_seconds=0.0, end_seconds=3.0,
                                                on_screen_text="HALF PRICE SALE")],
                           systems_music="促销电子", systems_sfx=["whoosh"])
    gate = plan_direct_execute(blueprint)
    plan = de.plan_direct_execute_render(blueprint, gate)
    timeline = plan.timeline
    subtitle = next(c for c in timeline.clips if c.clip_type == "subtitle")
    unchanged = de.resolve_library_clip(
        timeline, clip_id=subtitle.clip_id, asset_id="a", version_id="v"
    )
    assert unchanged is timeline  # 原样返回


def test_resolve_unknown_clip_is_identity() -> None:
    blueprint = _blueprint(beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=3.0)],
                           shots=[ReplicaShotV2(index=1, start_seconds=0.0, end_seconds=3.0,
                                                on_screen_text="HALF PRICE SALE")],
                           systems_music="促销电子", systems_sfx=["whoosh"])
    gate = plan_direct_execute(blueprint)
    plan = de.plan_direct_execute_render(blueprint, gate)
    assert (
        de.resolve_library_clip(
            plan.timeline, clip_id="nope", asset_id="a", version_id="v"
        )
        is plan.timeline
    )


def test_library_intent_clips_carry_audio_roles() -> None:
    """BGM/SFX 意图 clip 必须带 role 标记（剪辑域音频图按 role 识别 BGM）。

    G7 媒介测试静态核查抓到的真 bug：bgm_only 模式下不带 role="bgm" 的
    音频 clip 会被 build_audio_filter_graph 跳过——"启用 BGM"只在文本上
    成立，成片里哑掉。锁住标记，防回归。
    """
    blueprint = _blueprint(beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=3.0)],
                           shots=[ReplicaShotV2(index=1, start_seconds=0.0, end_seconds=3.0,
                                                on_screen_text="HALF PRICE SALE")],
                           systems_music="促销电子", systems_sfx=["whoosh"])
    gate = plan_direct_execute(blueprint)
    plan = de.plan_direct_execute_render(blueprint, gate)

    by_id = {c.clip_id: c for c in plan.timeline.clips}
    assert by_id["bgm_system"].metadata["role"] == "bgm"
    assert by_id["sfx_system"].metadata["role"] == "sfx"
    # role 在 resolve 回填后仍然在（回填只换资产身份与启用态）
    resolved = de.resolve_library_clip(
        plan.timeline, clip_id="bgm_system", asset_id="a1", version_id="v1"
    )
    bgm = next(c for c in resolved.clips if c.clip_id == "bgm_system")
    assert bgm.metadata["role"] == "bgm"
    assert bgm.enabled is True


def test_resolved_bgm_enters_editing_domain_audio_graph() -> None:
    """resolve 后的 BGM 必须进入剪辑域音频图（bgm_only 混合，none 静音）。

    G7 媒介测试静态核查抓到的真 bug 的廉价守护：不需要 ffmpeg——直接对
    build_audio_filter_graph 断言 role 标记的语义效果。混音标签为空 = 成片
    没有音轨，"启用 BGM" 就只是文本上的谎言。
    """
    from app.services.v2_final_composition_filters import build_audio_filter_graph
    from app.services.v2_final_composition_renderer import V2ResolvedTimelineClip

    blueprint = _blueprint(beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=3.0)],
                           shots=[ReplicaShotV2(index=1, start_seconds=0.0, end_seconds=3.0,
                                                on_screen_text="HALF PRICE SALE")],
                           systems_music="促销电子", systems_sfx=["whoosh"])
    gate = plan_direct_execute(blueprint)
    plan = de.plan_direct_execute_render(blueprint, gate)
    timeline = de.resolve_library_clip(
        plan.timeline, clip_id="bgm_system", asset_id="asset_bgm_1", version_id="ver_bgm_1"
    )

    resolved_clips = [
        V2ResolvedTimelineClip(
            input_index=index,
            clip=clip,
            track_order=0,
            source_has_audio=clip.clip_type == "audio",
            source_duration_seconds=clip.duration,
        )
        for index, clip in enumerate(timeline.clips)
        if clip.enabled
    ]

    mixed = build_audio_filter_graph(
        resolved_clips, timeline_duration_seconds=timeline.duration_seconds, audio_mode="bgm_only"
    )
    assert mixed.audio_label is not None
    assert "amix" in mixed.filter_complex

    silent = build_audio_filter_graph(
        resolved_clips, timeline_duration_seconds=timeline.duration_seconds, audio_mode="none"
    )
    assert silent.audio_label is None


# ---------------------------------------------------------------------------
# G3: 语义/可见时间分离 + handoff（hypit caption-fine scheduleFineCaption 移植）
# ---------------------------------------------------------------------------


def _cue(
    clip_id: str,
    start: float,
    duration: float,
    *,
    lead: float = 0.0,
    tail: float = 0.0,
    handoff: str = "overlap",
) -> de.WorkflowV2TimelineClip:
    from app.schemas.workflow_v2 import WorkflowV2TimelineSubtitleStyle

    return de.WorkflowV2TimelineClip(
        clip_id=clip_id,
        track_id=de.SUBTITLE_TRACK_ID,
        clip_type="subtitle",
        start_time=start,
        duration=duration,
        text=clip_id,
        subtitle_style=WorkflowV2TimelineSubtitleStyle(
            lead_seconds=lead, tail_seconds=tail, handoff=handoff  # type: ignore[arg-type]
        ),
        metadata={"label": clip_id},
    )


def _visible(cue: de.WorkflowV2TimelineClip) -> tuple[float, float]:
    return (
        float(cue.metadata["visible_start_seconds"]),
        float(cue.metadata["visible_end_seconds"]),
    )


def test_schedule_defaults_keep_legacy_behavior_byte_for_byte() -> None:
    """无 lead/tail（旧时间线/旧样式）→ 可见窗 = 语义窗，等价于不调度。"""
    cues = [_cue("a", 0.0, 2.0), _cue("b", 2.5, 2.0)]

    scheduled = de.schedule_caption_cues(cues, total=10.0)

    for cue in scheduled:
        assert _visible(cue) == (cue.start_time, round(cue.start_time + cue.duration, 6))


def test_schedule_widens_visible_window_without_touching_semantic_window() -> None:
    """lead/tail 只加宽可见窗；语义窗（start_time/duration）一字不动。"""
    cues = [_cue("a", 1.0, 2.0, lead=0.1, tail=0.2)]

    [scheduled] = de.schedule_caption_cues(cues, total=10.0)

    assert (scheduled.start_time, scheduled.duration) == (1.0, 2.0)
    assert _visible(scheduled) == (0.9, 3.2)


def test_schedule_clamps_visible_window_to_timeline_bounds() -> None:
    """可见窗钳到 [0, total]：不造负时间、不越内容末端。"""
    cues = [
        _cue("a", 0.0, 1.0, lead=0.5, tail=0.5),
        _cue("b", 9.5, 1.0, lead=0.5, tail=0.5),
    ]

    scheduled = de.schedule_caption_cues(cues, total=10.0)

    assert _visible(scheduled[0]) == (0.0, 1.5)
    assert _visible(scheduled[1]) == (9.0, 10.0)


def test_schedule_handoff_cut_trims_previous_tail_and_pushes_next_head() -> None:
    """handoff=cut：两条都说完（语义窗不变），可见窗在语义起点处交接。"""
    # 前一条可见尾 2.6 会越过后一条语义起点 2.5 → 裁到 2.5；后一条可见头
    # 2.1 被推到 2.5——交接点恰是后一条开始说话的位置。
    cues = [
        _cue("a", 0.0, 2.0, lead=0.0, tail=0.6, handoff="cut"),
        _cue("b", 2.5, 2.0, lead=0.4, tail=0.0, handoff="cut"),
    ]

    first, second = de.schedule_caption_cues(cues, total=10.0)

    # 语义窗神圣不可动
    assert (first.start_time, first.duration) == (0.0, 2.0)
    assert (second.start_time, second.duration) == (2.5, 2.0)
    # 可见窗在语义起点交接，互不抢占
    assert _visible(first) == (0.0, 2.5)
    assert _visible(second) == (2.5, 4.5)


def test_schedule_handoff_overlap_does_not_trim() -> None:
    """handoff=overlap（默认）：可见窗可交叠，调度不裁不推。"""
    cues = [
        _cue("a", 0.0, 2.0, lead=0.0, tail=0.6, handoff="overlap"),
        _cue("b", 2.5, 2.0, lead=0.4, tail=0.0, handoff="overlap"),
    ]

    first, second = de.schedule_caption_cues(cues, total=10.0)

    assert _visible(first) == (0.0, 2.6)
    assert _visible(second) == (2.1, 4.5)


def test_schedule_handoff_skips_when_previous_ends_after_next_starts() -> None:
    """前一条语义尾晚于后一条语义头（交叠口播）→ 不裁不推（无从交接）。"""
    cues = [
        _cue("a", 0.0, 3.0, lead=0.0, tail=0.5, handoff="cut"),
        _cue("b", 2.0, 2.0, lead=0.5, tail=0.0, handoff="cut"),
    ]

    first, second = de.schedule_caption_cues(cues, total=10.0)

    assert _visible(first) == (0.0, 3.5)
    assert _visible(second) == (1.5, 4.0)


def test_schedule_handoff_is_per_track() -> None:
    """跨轨（字幕 vs 音效巷）不相干：不同 track_id 之间不交接。"""
    from app.schemas.workflow_v2 import WorkflowV2TimelineSubtitleStyle

    def cue(track_id: str) -> de.WorkflowV2TimelineClip:
        return de.WorkflowV2TimelineClip(
            clip_id=f"{track_id}_1",
            track_id=track_id,
            clip_type="subtitle",
            start_time=1.0,
            duration=2.0,
            text="x",
            subtitle_style=WorkflowV2TimelineSubtitleStyle(tail_seconds=0.6),
        )

    cues = [cue("track-a"), cue("track-b")]

    first, second = de.schedule_caption_cues(cues, total=10.0)

    assert _visible(first) == (1.0, 3.6)
    assert _visible(second) == (1.0, 3.6)


def test_compiled_cues_carry_replica_style_defaults_and_visible_window() -> None:
    """编译层接线：复刻 cue 带 0.1/0.2/cut 样式默认值 + 可见窗元数据。"""
    blueprint = _blueprint(
        beats=[ReplicaBeatV2(beat_id="b1", start_seconds=0.0, end_seconds=6.0)],
        shots=[
            ReplicaShotV2(index=1, start_seconds=0.0, end_seconds=2.0, on_screen_text="A"),
            ReplicaShotV2(index=2, start_seconds=3.0, end_seconds=5.0, on_screen_text="B"),
        ],
    )
    gate = plan_direct_execute(blueprint)
    plan = de.plan_direct_execute_render(blueprint, gate)

    cues = [c for c in plan.timeline.clips if c.clip_type == "subtitle"]
    assert len(cues) == 2
    for cue in cues:
        style = cue.subtitle_style
        assert style.lead_seconds == de.DEFAULT_CUE_LEAD_SECONDS
        assert style.tail_seconds == de.DEFAULT_CUE_TAIL_SECONDS
        assert style.handoff == de.DEFAULT_CUE_HANDOFF
        assert "visible_start_seconds" in cue.metadata
        assert "visible_end_seconds" in cue.metadata
    # 相邻 cue 交接：前可见尾 ≤ 后语义起点（0.4s 合并 + 0.2s tail 下天然成立）
    assert _visible(cues[0])[1] <= cues[1].start_time


def test_renderer_drawtext_uses_visible_window_metadata() -> None:
    """渲染器：可见窗元数据驱动 drawtext 的 enable 窗（缺失回落 clip 窗）。"""
    from app.services.v2_final_composition_filters import (
        V2CompositionCanvas,
        _subtitle_filter,
    )

    canvas = V2CompositionCanvas(
        width=720, height=1280, fps=30, duration_seconds=6.0, subtitle_font_path="/f.ttf"
    )
    scheduled = de.schedule_caption_cues(
        [_cue("a", 1.0, 2.0, lead=0.1, tail=0.2)], total=6.0
    )[0]
    scheduled = scheduled.model_copy(update={"text": "BUY NOW"}, deep=True)

    filter_text = _subtitle_filter(scheduled, canvas)

    assert "between(t,0.900,3.200)" in filter_text

    legacy = _cue("a", 1.0, 2.0)  # 无可见窗元数据的旧 clip
    legacy_filter = _subtitle_filter(legacy.model_copy(update={"text": "X"}, deep=True), canvas)
    assert "between(t,1.000,3.000)" in legacy_filter
