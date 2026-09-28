"""拉片复刻 · direct-execute 字幕轨直出（ADR 0010 R1）。

把可行性门（``direct_execute.py``）判定 ``feasible=True`` 的蓝图编译成
一条**剪辑域可执行的 canonical timeline**（``WorkflowV2Timeline``），零生成
模型费。本模块全部为纯函数：无 IO、无 LLM、无 HTTP，可完整单测。

设计边界（对齐 ADR 0010 + 调研档 §3.5）：

- 输入：可行性门判定可行的蓝图（纯屏上文字镜头 + 字幕 + 音效 + 配乐）；
- 输出：``WorkflowV2Timeline``，subtitle 轨带 cues，可选 audio 轨（BGM/SFX）
  只记录意图（库素材指针在编译后由剪辑域实际解析，不在此层做库查询）；
- 诚实边界：渲染器（``V2FinalCompositionRenderer``）要求至少一个 enabled
  video clip；纯字幕片没有画面源时由调用方决定是否补"占位 video clip"
  （如纯色源），那属于剪辑域决策，不在本编译层。

与 v1 ``TimelineClipV1`` 的区别：本模块产出的是 v2 剪辑域
``WorkflowV2Timeline``（schema 见 ``app.schemas.workflow_v2``），
与既有 ``V2FinalCompositionRenderService`` 同构——不建第二套时间线。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.schemas.workflow_v2 import (
    WorkflowV2Timeline,
    WorkflowV2TimelineClip,
    WorkflowV2TimelineSubtitleStyle,
    WorkflowV2TimelineTrack,
)
from app.services.replica.direct_execute import DirectExecutePlan
from app.services.replica.recipe import ReplicaRecipeV2, apply_recipe

#: 字幕轨默认 fps（与 editing 域一致）
DEFAULT_FPS = 30

#: subtitle 轨 track id（与剪辑域约定；v2 track_type 支持 "subtitle"）
SUBTITLE_TRACK_ID = "track-subtitle"
SUBTITLE_TRACK_NAME = "Captions (replica direct-execute)"

#: BGM/SFX 轨：零模型费直出里库素材是"意图"而非实际 asset 引用——
#: 本层记录意图，剪辑域在组装时解析库并补 source_asset_id/version。
BGM_TRACK_ID = "track-bgm"
SFX_TRACK_ID = "track-sfx"

#: 库素材未解析时使用的占位 asset/version id。
#: 配合 enabled=False 使渲染器跳过该 clip；
#: 剪辑域解析库后须将 enabled 置 True 并回填真实 source_asset_id/version。
UNRESOLVED_LIBRARY_ASSET_ID = "__pending_library_resolution__"

#: 字幕 cue 合并不闪跳的最小间隔（秒）
MIN_CUE_GAP_SECONDS = 0.4

#: 复刻直出的字幕样式默认值（hypit caption-fine 的秒制最小集）：
#: 可见窗比口播窗各提前/延后 0.1/0.2s（读得完、不抢下一句），同角色相邻
#:  cue 竞争交接区间时裁前一条可见尾（cut），且不动口播时间。
#: 与 ADR 0010 R1 的"零模型费"一起，这是 R1 字幕质量的一等公民。
DEFAULT_CUE_LEAD_SECONDS = 0.1
DEFAULT_CUE_TAIL_SECONDS = 0.2
DEFAULT_CUE_HANDOFF = "cut"

#: 调度结果落在 cue metadata 的键（渲染器 _subtitle_filter 读它们画可见窗；
#: 缺失时回落 clip 窗——向后兼容旧时间线）。
VISIBLE_START_KEY = "visible_start_seconds"
VISIBLE_END_KEY = "visible_end_seconds"


@dataclass(frozen=True)
class DirectExecuteRenderPlan:
    """direct-execute R1 编译结果（纯数据,可序列化,零模型费）。

    ``timeline`` 是可直接交给 ``V2FinalCompositionRenderService`` 的
    canonical 时间线；``needs_placeholder_video`` 诚实标注渲染器约束——
    纯字幕片撞 ``composition_input_missing`` 时由调用方决策补占位。
    """

    feasible: bool
    timeline: WorkflowV2Timeline
    rejected: tuple[str, ...]
    needs_placeholder_video: bool
    subtitle_cue_count: int
    #: 库素材待解析意图（B v1：透出给调用方人工解析；自动匹配留 v2）
    unresolved: tuple[dict, ...] = ()


def plan_direct_execute_render(
    blueprint: ReplicaBlueprintContentV2,
    gate: DirectExecutePlan,
    *,
    recipe: ReplicaRecipeV2 | None = None,
) -> DirectExecuteRenderPlan:
    """把可行蓝图编译为零模型费剪辑时间线（纯函数,确定性）。

    只消费 ``gate.feasible=True``；non-feasible 返回 ``feasible=False``
    + ``rejected`` 清单,时间线为空轨,不产 cues。
    """
    if not gate.feasible:
        return DirectExecuteRenderPlan(
            feasible=False,
            timeline=_empty_timeline(blueprint),
            rejected=gate.blockers + gate.generation_steps,
            needs_placeholder_video=False,
            subtitle_cue_count=0,
            unresolved=(),
        )

    total = _content_duration(blueprint)
    cue_clips = _subtitle_cues(blueprint, total, recipe)
    cue_clips = schedule_caption_cues(cue_clips, total=total)
    bgm_clips = _bgm_clips(blueprint, total)
    sfx_clips = _sfx_clips(blueprint, total)

    tracks = [
        WorkflowV2TimelineTrack(
            track_id=SUBTITLE_TRACK_ID,
            track_type="subtitle",
            order=2,
            metadata={"label": SUBTITLE_TRACK_NAME},
        )
    ]
    clips: list[WorkflowV2TimelineClip] = list(cue_clips)
    if bgm_clips:
        tracks.append(
            WorkflowV2TimelineTrack(
                track_id=BGM_TRACK_ID, track_type="audio", order=1,
                metadata={"label": "BGM"},
            )
        )
        clips.extend(bgm_clips)
    if sfx_clips:
        tracks.append(
            WorkflowV2TimelineTrack(
                track_id=SFX_TRACK_ID, track_type="audio", order=3,
                metadata={"label": "SFX"},
            )
        )
        clips.extend(sfx_clips)

    timeline = WorkflowV2Timeline(
        timeline_id="replica-direct-execute-1",
        version=1,
        # WorkflowV2Timeline validator 要求 duration_seconds 与 enabled clips 末端一致；
        # bgm/sfx clips 为 enabled=False，不计入此处
        duration_seconds=round(_enabled_content_end(cue_clips), 3),
        aspect_ratio=_aspect_to_v2(blueprint.aspect),
        resolution={"width": 720, "height": 1280}
        if "9:16" in (blueprint.aspect or "")
        else {"width": 1280, "height": 720},
        fps=DEFAULT_FPS,
        tracks=tracks,
        clips=clips,
        metadata={
            "origin": "replica-direct-execute",
            "source_video_asset_id": blueprint.source_video_asset_id,
            "replica_goal": blueprint.replica_goal,
            # 本编译层只产出 subtitle/audio 轨——纯字幕片没有画面源，
            # 此标记随时间线进入剪辑域渲染器：补一个占位 video clip
            # （纯色源），让 feasible 蓝图能走完渲染（ADR 0010 R1 验收）。
            "needs_placeholder_video": True,
        },
    )
    # 渲染器硬约束：canonical timeline 需至少一个 enabled video clip。
    # 纯字幕片没有画面源——needs_placeholder_video 随时间线元数据传递，
    # 渲染器据此补占位 clip；本层保持诚实（不造假画面）。
    has_video = any(c.clip_type == "video" for c in timeline.clips)
    return DirectExecuteRenderPlan(
        feasible=True,
        timeline=timeline,
        rejected=(),
        needs_placeholder_video=not has_video,
        subtitle_cue_count=len(cue_clips),
        unresolved=unresolved_intents_of(timeline),
    )


# ---------------------------------------------------------------------------
# 时间线内容派生
# ---------------------------------------------------------------------------


def _content_duration(blueprint: ReplicaBlueprintContentV2) -> float:
    """取"有内容的镜头"末端;全空白退段落表,再退根 duration。"""
    content_shots = [
        s
        for s in blueprint.shots
        if s.on_screen_text.strip() or s.subject_action.strip()
    ]
    if content_shots:
        return max(s.end_seconds for s in content_shots)
    if blueprint.beats:
        return max(b.end_seconds for b in blueprint.beats)
    return blueprint.duration_seconds


def _subtitle_cues(
    blueprint: ReplicaBlueprintContentV2,
    total: float,
    recipe: ReplicaRecipeV2 | None = None,
) -> list[WorkflowV2TimelineClip]:
    """段落台词 + 纯屏上文字镜头 → subtitle cues（词窗优先,段落窗兜底）。

    相邻 cue 间隔 < ``MIN_CUE_GAP_SECONDS`` 时合并到前一条（字幕不闪跳）；
    总时长封顶到内容末端。

    **词级 karaoke 不属于这一层**（2026-09-28 决策记录）：本层只服务零模型费
    通道，而该通道的结构性前提是"无台词"——有 ``line`` 的 beat 必被可行性门
    判为需 TTS（模型调用）而不可行。词级对齐内容（``beat.words``，来自转录）
    只存在于有台词的片子，它的消费者是生成通道（TTS 落音后词窗对齐口播）与
    剪辑域 ASS writer 的 ``{\\k}`` 高亮——在那两层落地前，这里不预留死分支。
    词流本身已在蓝图侧保留（``ReplicaBeatV2.words``）并在工作台可见。
    """
    word_events_by_beat: dict[str, list] = {}
    for event in blueprint.anchor_events:
        if event.word and event.word_start_seconds > 0.0:
            word_events_by_beat.setdefault(event.beat_id, []).append(event)

    cues: list[WorkflowV2TimelineClip] = []
    for beat in blueprint.beats:
        if not beat.line.strip():
            continue
        evs = word_events_by_beat.get(beat.beat_id, [])
        if evs:
            start = min(e.word_start_seconds for e in evs)
            end = max(e.word_end_seconds for e in evs)
        else:
            start, end = beat.start_seconds, beat.end_seconds
        cues.append(
            _subtitle_clip(
                clip_id=f"sub_{beat.beat_id}",
                start=start,
                end=end,
                text=beat.line,
                label=beat.role,
                recipe=recipe,
            )
        )

    covered = cues
    for shot in blueprint.shots:
        text = shot.on_screen_text.strip()
        if not text or shot.subject_action.strip():
            continue
        if _covered(covered, shot.start_seconds, shot.end_seconds):
            continue
        cues.append(
            _subtitle_clip(
                clip_id=f"sub_s{shot.index}",
                start=shot.start_seconds,
                end=shot.end_seconds,
                text=text,
                label=f"shot-{shot.index}",
                recipe=recipe,
            )
        )

    merged = _merge_adjacent_cues(cues, total)
    return merged


def schedule_caption_cues(
    cues: list[WorkflowV2TimelineClip], *, total: float
) -> list[WorkflowV2TimelineClip]:
    """给每条 cue 算**可见窗**并写进 metadata（hypit ``scheduleFineCaption`` 秒制移植）。

    语义/可见分离（hypit caption-fine 的核心纪律）：

    - **语义窗**（口播时间，神圣不可动）= cue 的 ``start_time``/``duration``；
    - **可见窗** = 语义窗按样式的 ``lead_seconds``/``tail_seconds`` 向两侧加宽，
      钳到 ``[0, total]``——加宽只影响"看得见"，不影响"说到哪"；
    - 同角色（``metadata.label``）相邻 cue 且 ``handoff="cut"`` 时：前一条可见尾
      裁到不超过后一条语义起点（至少保留到自己的语义尾），后一条可见头推到
      不早于该裁点（至多推到自己的语义起点）——两条都说完，不互相抢占。

    无样式参数（旧时间线）时可见窗 = 语义窗，逐字节等价于不调度。
    纯函数、确定性；输入未排序亦可自排序。
    """
    ordered = sorted(cues, key=lambda cue: (cue.start_time, cue.clip_id))
    scheduled: list[WorkflowV2TimelineClip] = []
    # track_id → 已排程的同轨上一条 cue 在 scheduled 里的下标。
    # hypit 的 handoff 按 role 分组（一条 Use = 一个角色的一条字幕流）；
    # 我们是单条 subtitle 轨，对应物就是**同轨**——同轨相邻 cue 竞争同一块
    # 屏幕，必须交接；跨轨（字幕/音效）互不相干。
    previous_by_track: dict[str, int] = {}
    for cue in ordered:
        style = cue.subtitle_style
        semantic_start = cue.start_time
        semantic_end = round(cue.start_time + cue.duration, 6)
        visible_start = round(max(0.0, semantic_start - style.lead_seconds), 6)
        visible_end = round(min(total, semantic_end + style.tail_seconds), 6)
        previous_index = previous_by_track.get(cue.track_id)
        previous = scheduled[previous_index] if previous_index is not None else None
        if (
            previous is not None
            and style.handoff == "cut"
            and previous.start_time + previous.duration <= semantic_start
        ):
            previous_semantic_end = round(previous.start_time + previous.duration, 6)
            previous_visible_end = float(
                previous.metadata.get(VISIBLE_END_KEY, previous_semantic_end)
            )
            # 裁前一条可见尾：不越过本条语义起点，也不早于前一条语义尾
            trim_to = round(
                max(previous_semantic_end, min(previous_visible_end, semantic_start)),
                6,
            )
            scheduled[previous_index] = previous.model_copy(
                update={"metadata": {**previous.metadata, VISIBLE_END_KEY: trim_to}},
                deep=True,
            )
            # 推本条可见头：不早于裁点，也不晚于本条语义起点
            visible_start = round(min(semantic_start, max(visible_start, trim_to)), 6)
        previous_by_track[cue.track_id] = len(scheduled)
        scheduled.append(
            cue.model_copy(
                update={
                    "metadata": {
                        **cue.metadata,
                        VISIBLE_START_KEY: visible_start,
                        VISIBLE_END_KEY: visible_end,
                    }
                },
                deep=True,
            )
        )
    return scheduled


def _subtitle_clip(
    clip_id: str,
    start: float,
    end: float,
    text: str,
    label: str,
    *,
    recipe: ReplicaRecipeV2 | None = None,
) -> WorkflowV2TimelineClip:
    start = round(max(start, 0.0), 3)
    duration = round(max(0.01, end - start), 3)
    # 基础样式 = G3 的显式默认（0.1/0.2/cut）；配方随后覆盖它设置的维度
    # （G5 .adrecipe：字体/颜色/位置/lead/tail/handoff——全部渲染链真实消费）。
    base_style = WorkflowV2TimelineSubtitleStyle(
        font_size=42,
        color="#FFFFFF",
        position="bottom_center",
        lead_seconds=DEFAULT_CUE_LEAD_SECONDS,
        tail_seconds=DEFAULT_CUE_TAIL_SECONDS,
        handoff=DEFAULT_CUE_HANDOFF,  # type: ignore[arg-type]
    )
    return WorkflowV2TimelineClip(
        clip_id=clip_id,
        track_id=SUBTITLE_TRACK_ID,
        clip_type="subtitle",
        start_time=start,
        duration=duration,
        text=text,
        subtitle_style=apply_recipe(base_style, recipe),
        metadata={"label": label},
    )


def _covered(cues: list[WorkflowV2TimelineClip], start: float, end: float) -> bool:
    return any(
        c.start_time <= start and end <= c.start_time + c.duration for c in cues
    )


def _merge_adjacent_cues(
    cues: list[WorkflowV2TimelineClip], total: float
) -> list[WorkflowV2TimelineClip]:
    """间隔 < MIN_CUE_GAP_SECONDS 的相邻 cue 合并（文本换行拼接）。"""
    ordered = sorted(cues, key=lambda c: (c.start_time, c.clip_id))
    merged: list[WorkflowV2TimelineClip] = []
    for cue in ordered:
        if cue.start_time >= total:
            continue
        if merged:
            prev = merged[-1]
            gap = cue.start_time - (prev.start_time + prev.duration)
            if 0 <= gap < MIN_CUE_GAP_SECONDS:
                new_duration = round(
                    cue.start_time - prev.start_time + cue.duration, 3
                )
                merged[-1] = WorkflowV2TimelineClip(
                    clip_id=f"{prev.clip_id}+{cue.clip_id}",
                    track_id=prev.track_id,
                    clip_type="subtitle",
                    start_time=prev.start_time,
                    duration=new_duration,
                    text=f"{prev.text}\n{cue.text}",
                    subtitle_style=prev.subtitle_style,
                    metadata={
                        "label": "+".join(
                            p for p in (
                                prev.metadata.get("label"),
                                cue.metadata.get("label"),
                            )
                            if p
                        )
                    },
                )
                continue
        merged.append(_clamped_cue(cue, total))
    return merged


def _clamped_cue(cue: WorkflowV2TimelineClip, total: float) -> WorkflowV2TimelineClip:
    start = min(cue.start_time, total)
    return WorkflowV2TimelineClip(
        clip_id=cue.clip_id,
        track_id=cue.track_id,
        clip_type="subtitle",
        start_time=start,
        duration=max(0.01, min(cue.duration, total - start)),
        text=cue.text,
        subtitle_style=cue.subtitle_style,
        metadata=dict(cue.metadata),
    )


def _bgm_clips(
    blueprint: ReplicaBlueprintContentV2, total: float
) -> list[WorkflowV2TimelineClip]:
    if not blueprint.systems_music.strip():
        return []
    return [
        WorkflowV2TimelineClip(
            clip_id="bgm_system",
            track_id=BGM_TRACK_ID,
            clip_type="audio",
            start_time=0.0,
            duration=round(total, 3),
            text=blueprint.systems_music,
            # 库素材未解析：enabled=False 使渲染器跳过此 clip；
            # source_asset_id/version 填哨兵值避免 schema 校验失败，
            # 剪辑域解析库后将 enabled 置 True 并回填真实 id。
            source_asset_id=UNRESOLVED_LIBRARY_ASSET_ID,
            source_version_id=UNRESOLVED_LIBRARY_ASSET_ID,
            enabled=False,
            metadata={
                "label": "bgm-library-intent",
                "library_hint": blueprint.systems_music,
                "library_resolved": False,
                # 剪辑域音频图按 role 识别 BGM（bgm_only 模式只混 BGM）——
                # 不打标记的"音乐意图"在成片里哑掉，等于替用户做了一个静音决定
                "role": "bgm",
            },
        )
    ]


def _sfx_clips(
    blueprint: ReplicaBlueprintContentV2, total: float
) -> list[WorkflowV2TimelineClip]:
    if not blueprint.systems_sfx:
        return []
    return [
        WorkflowV2TimelineClip(
            clip_id="sfx_system",
            track_id=SFX_TRACK_ID,
            clip_type="audio",
            start_time=0.0,
            duration=round(total, 3),
            text="; ".join(blueprint.systems_sfx),
            source_asset_id=UNRESOLVED_LIBRARY_ASSET_ID,
            source_version_id=UNRESOLVED_LIBRARY_ASSET_ID,
            enabled=False,
            metadata={
                "label": "sfx-library-intent",
                "library_hint": list(blueprint.systems_sfx),
                "library_resolved": False,
                "role": "sfx",
            },
        )
    ]


def unresolved_intents_of(timeline: WorkflowV2Timeline) -> tuple[dict, ...]:
    """收集待人工解析的库素材意图（B v1：人解析；自动匹配 v2）。"""
    return tuple(
        {
            "clip_id": clip.clip_id,
            "track_id": clip.track_id,
            "intent": clip.text,
            "library_hint": clip.metadata.get("library_hint"),
            "duration_seconds": clip.duration,
        }
        for clip in timeline.clips
        if not clip.enabled and clip.source_asset_id == UNRESOLVED_LIBRARY_ASSET_ID
    )


def resolve_library_clip(
    timeline: WorkflowV2Timeline,
    *,
    clip_id: str,
    asset_id: str,
    version_id: str,
) -> WorkflowV2Timeline:
    """人工解析回填：把一个待解析 clip 绑到真实库素材并启用（纯函数）。

    未命中 clip_id 时原样返回；已启用或非哨兵 clip 不接受回填（防误覆盖）。
    """
    updated: list[WorkflowV2TimelineClip] = []
    changed = False
    for clip in timeline.clips:
        if clip.clip_id != clip_id:
            updated.append(clip)
            continue
        if clip.enabled or clip.source_asset_id != UNRESOLVED_LIBRARY_ASSET_ID:
            updated.append(clip)
            continue
        changed = True
        updated.append(
            clip.model_copy(
                update={
                    "source_asset_id": asset_id,
                    "source_version_id": version_id,
                    "enabled": True,
                    "metadata": {**clip.metadata, "library_resolved": True},
                }
            )
        )
    if not changed:
        return timeline
    # 启用可能改变 enabled 末端，时长口径与 validator 对齐
    return timeline.model_copy(
        update={
            "clips": updated,
            "duration_seconds": _enabled_content_end(updated),
        }
    )


def _empty_timeline(blueprint: ReplicaBlueprintContentV2) -> WorkflowV2Timeline:
    return WorkflowV2Timeline(
        timeline_id="replica-direct-execute-1",
        version=1,
        duration_seconds=0.0,
        aspect_ratio=_aspect_to_v2(blueprint.aspect),
        fps=DEFAULT_FPS,
        tracks=[],
        clips=[],
        metadata={
            "origin": "replica-direct-execute",
            "source_video_asset_id": blueprint.source_video_asset_id,
        },
    )


def _aspect_to_v2(aspect: str) -> str:
    """蓝图画幅（"9:16" 等）→ v2 timeline aspect_ratio（同形）。"""
    return aspect if ":" in (aspect or "") else "16:9"


def _enabled_content_end(clips: list[WorkflowV2TimelineClip]) -> float:
    """所有 enabled clips 的最远末端（与 WorkflowV2Timeline validator 同口径）。"""
    return round(max((c.start_time + c.duration for c in clips if c.enabled), default=0.0), 3)
