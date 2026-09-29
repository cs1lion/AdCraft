"""One-call replica film generation (拉片复刻 → 成片).

The author's flow is: pick slots, press generate, get the film.  This module
turns a blueprint into one video node per shot; the script node, the
blueprint vocabulary and the old multi-step "instantiate" ritual stay
internal (2026-09-29 author ruling on 简约好用).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.agent_canvas_ad_media import (
    ReplicaBlueprintContentV2,
    VideoSegmentContentV2,
)

#: Video models generate 4–12s per clip (catalog duration_range_seconds).
MIN_SHOT_SECONDS = 4.0
MAX_SHOT_SECONDS = 12.0

#: Title prefix for generated shot nodes — re-running the film reuses them
#: instead of spawning duplicates on the canvas.
FILM_NODE_TITLE_PREFIX = "复刻镜头"


@dataclass(frozen=True)
class ReplicaFilmShotPlan:
    shot_index: int
    title: str
    generation_prompt: str
    segment: dict


def _clamp_seconds(value: float) -> float:
    return min(MAX_SHOT_SECONDS, max(MIN_SHOT_SECONDS, value))


def _shot_visual(shot, blueprint: ReplicaBlueprintContentV2) -> str:
    """One shot's regeneration brief: composition from the teardown, content from the slots."""

    lines = [
        f"镜头{shot.index}（{shot.start_seconds:.1f}–{shot.end_seconds:.1f}s，"
        f"{shot.shot_size or '中景'}/{shot.camera_motion or '固定'}）",
        shot.subject_action or "（动作未标注）",
    ]
    if shot.on_screen_text:
        lines.append(f"屏上文字：{shot.on_screen_text}")
    if shot.recreate_hint:
        lines.append(f"复刻提示：{shot.recreate_hint}")
    lines.append(f"转场：{shot.transition_to_next or '切'}")
    lines.append(
        f"整体视觉风格与节奏复刻原片（{blueprint.format_name}），构图与机位保持一致。"
    )
    applied = [slot for slot in blueprint.slots if slot.applied and slot.replace_with.strip()]
    if applied:
        directives = [f"【{slot.label}】用「{slot.replace_with}」取代原片对应元素" for slot in applied]
        lines.append("槽位替换：" + "；".join(directives) + "。其余保持不变。")
    return "\n".join(lines)


def plan_film_shots(blueprint: ReplicaBlueprintContentV2) -> list[ReplicaFilmShotPlan]:
    plans: list[ReplicaFilmShotPlan] = []
    for shot in blueprint.shots:
        duration = _clamp_seconds(shot.end_seconds - shot.start_seconds)
        visual = _shot_visual(shot, blueprint)
        segment = VideoSegmentContentV2(
            segment_summary=f"复刻镜头{shot.index}（{shot.shot_size or '中景'}，{duration:.0f}s）",
            duration_seconds=duration,
            storyboard_content=visual,
        )
        plans.append(
            ReplicaFilmShotPlan(
                shot_index=shot.index,
                title=f"{FILM_NODE_TITLE_PREFIX}{shot.index}",
                generation_prompt=visual,
                segment=segment.model_dump(mode="json"),
            )
        )
    return plans
