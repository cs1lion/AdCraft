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
    cue_clips = _subtitle_cues(blueprint, total)
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
    blueprint: ReplicaBlueprintContentV2, total: float
) -> list[WorkflowV2TimelineClip]:
    """段落台词 + 纯屏上文字镜头 → subtitle cues（词窗优先,段落窗兜底）。

    相邻 cue 间隔 < ``MIN_CUE_GAP_SECONDS`` 时合并到前一条（字幕不闪跳）；
    总时长封顶到内容末端。
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
            )
        )

    merged = _merge_adjacent_cues(cues, total)
    return merged


def _subtitle_clip(
    clip_id: str, start: float, end: float, text: str, label: str
) -> WorkflowV2TimelineClip:
    start = round(max(start, 0.0), 3)
    duration = round(max(0.01, end - start), 3)
    return WorkflowV2TimelineClip(
        clip_id=clip_id,
        track_id=SUBTITLE_TRACK_ID,
        clip_type="subtitle",
        start_time=start,
        duration=duration,
        text=text,
        subtitle_style=WorkflowV2TimelineSubtitleStyle(
            font_size=42, color="#FFFFFF", position="bottom_center"
        ),
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
        merged.append(
            WorkflowV2TimelineClip(
                clip_id=cue.clip_id,
                track_id=cue.track_id,
                clip_type="subtitle",
                start_time=min(cue.start_time, total),
                duration=max(
                    0.01, min(cue.duration, total - min(cue.start_time, total))
                ),
                text=cue.text,
                subtitle_style=cue.subtitle_style,
                metadata=dict(cue.metadata),
            )
        )
    return merged


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
