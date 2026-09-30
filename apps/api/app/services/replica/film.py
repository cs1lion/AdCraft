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


def _shot_visual(
    shot,
    blueprint: ReplicaBlueprintContentV2,
    rewritten: str | None = None,
) -> str:
    """One shot's regeneration brief.

    ``rewritten`` 是复刻改写后的新版描述（原产品/品牌/文案已按槽位换掉）：
    此时描述整体用它，不再回抄原片文本、也不再附槽位指令行——那是在
    告诉模型"存在一个原片元素"，实测会把新旧元素搅成一锅（作者判：
    完全达不到风格复刻）。没拿到改写就退回原行为：原描述 + 槽指令行。
    """

    lines = [
        f"镜头{shot.index}（{shot.start_seconds:.1f}–{shot.end_seconds:.1f}s，"
        f"{shot.shot_size or '中景'}/{shot.camera_motion or '固定'}）",
    ]
    if rewritten:
        lines.append(rewritten)
    else:
        lines.append(shot.subject_action or "（动作未标注）")
        if shot.on_screen_text:
            lines.append(f"屏上文字：{shot.on_screen_text}")
    if shot.recreate_hint:
        lines.append(f"复刻提示：{shot.recreate_hint}")
    lines.append(f"转场：{shot.transition_to_next or '切'}")
    lines.append(
        f"整体视觉风格与节奏复刻原片（{blueprint.format_name}），构图与机位保持一致。"
    )
    if not rewritten:
        applied = [slot for slot in blueprint.slots if slot.applied and slot.replace_with.strip()]
        if applied:
            directives = [
                f"【{slot.label}】用「{slot.replace_with}」取代原片对应元素" for slot in applied
            ]
            lines.append("槽位替换：" + "；".join(directives) + "。其余保持不变。")
    return "\n".join(lines)


def plan_film_shots(
    blueprint: ReplicaBlueprintContentV2,
    rewritten_visuals: list[str] | None = None,
) -> list[ReplicaFilmShotPlan]:
    """Blueprint → per-shot film nodes.

    ``rewritten_visuals``：复刻改写产物（每镜一条新版描述，次序与
    ``blueprint.shots`` 一致）。给了就整体替换原片描述，实现"同风格、
    新元素"；数量不符时忽略改写退回原行为。
    """

    briefs = list(rewritten_visuals) if rewritten_visuals else None
    if briefs is not None and len(briefs) != len(blueprint.shots):
        briefs = None
    negative = ""
    if briefs:
        # 改写版另配负面约束：把原产品/品牌显式挡在生成门外（视频模型对
        # 负面约束是直接生效的通道，比只在描述里回避更硬）。
        originals = [
            slot.source_value.strip()
            for slot in blueprint.slots
            if slot.applied and (slot.source_value or "").strip()
        ]
        if originals:
            negative = "不得出现：" + "、".join(originals) + "；不得出现任何原片包装与屏上文字。"
    plans: list[ReplicaFilmShotPlan] = []
    for offset, shot in enumerate(blueprint.shots):
        duration = _clamp_seconds(shot.end_seconds - shot.start_seconds)
        visual = _shot_visual(
            shot,
            blueprint,
            rewritten=briefs[offset] if briefs else None,
        )
        segment = VideoSegmentContentV2(
            segment_summary=f"复刻镜头{shot.index}（{shot.shot_size or '中景'}，{duration:.0f}s）",
            duration_seconds=duration,
            storyboard_content=visual,
            **({"negative_constraints": negative} if negative else {}),
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
