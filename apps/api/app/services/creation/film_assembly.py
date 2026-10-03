"""S8 镜头合成：镜头 video 节点 → canvas 时间线 video track。

两条一键流的收尾：镜头全部就绪后，把它们按序铺到画布自己的
final-composition 时间线（`TimelineRepository`，即时间线编辑器用的同一
存储）。调用方幂等刷新同一源节点的 clip，保留 clip 身份。

本模块规划镜号顺序与镜头时长；调用方将同一份计划写入 canvas 时间线并
投影到 authoring 存储，最终复用标准 v2 final-composition 渲染栈。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite


@dataclass(frozen=True)
class TimelineClipPlacementV1:
    track_id: str
    source_node_id: str
    asset_id: str
    asset_version_id: str | None
    start_time: float
    duration: float
    title: str
    source_shot_index: int = 0


@dataclass
class AssemblyPlanV1:
    placements: list[TimelineClipPlacementV1] = field(default_factory=list)


def _shot_order(title: str) -> int:
    digits = "".join(ch for ch in title if ch.isdigit())
    return int(digits) if digits else 0


def _segment_duration(node) -> float:
    content = node.structured_content or {}
    segment = content.get("segment") if isinstance(content, dict) else None
    source = segment if isinstance(segment, dict) else content
    try:
        duration = float(source.get("duration_seconds") or 5)
        return max(0.5, duration) if isfinite(duration) else 5.0
    except (TypeError, ValueError):
        return 5.0


def plan_assembly(video_track_id: str, nodes) -> AssemblyPlanV1:
    """按镜头序号铺排；调用方幂等更新已有 clip 与最终渲染投影。"""

    ordered = sorted(
        (n for n in nodes if n.node_type == "video" and n.output_asset_id),
        key=lambda n: (_shot_order(n.title or ""), n.node_id),
    )
    plan = AssemblyPlanV1()
    cursor = 0.0
    for node in ordered:
        duration = round(_segment_duration(node), 3)
        plan.placements.append(
            TimelineClipPlacementV1(
                track_id=video_track_id,
                source_node_id=node.node_id,
                asset_id=str(node.output_asset_id),
                asset_version_id=node.output_asset_version_id,
                start_time=round(cursor, 3),
                duration=duration,
                title=node.title or node.node_id,
                source_shot_index=_shot_order(node.title or ""),
            )
        )
        cursor += duration
    return plan
