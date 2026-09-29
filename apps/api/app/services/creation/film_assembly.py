"""S8 镜头合成：镜头 video 节点 → canvas 时间线 video track。

两条一键流的收尾：镜头全部就绪后，把它们按序铺到画布自己的
final-composition 时间线（`TimelineRepository`，即时间线编辑器用的同一
存储）。幂等——同一源节点的 clip 已存在则跳过。

关于最终渲染（诚实边界）：v2 final-composition 渲染栈
（`V2FinalCompositionRenderService`）綁定 authoring 存储
（`workflows`/`workflow_revisions` 表），而真实工作流全部住在
`agent_canvas_workflows`——2026-09-29 实机确认该表为空、渲染栈对所有
canvas 工作流不可达（出厂 ✔ 仅有 fake 单测撑腰）。本模块只负责"铺满
时间线"；渲染尝试走标准栈，够不着时返回带码的明确失败，不假装成功。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TimelineClipPlacementV1:
    track_id: str
    source_node_id: str
    asset_id: str
    asset_version_id: str | None
    start_time: float
    duration: float
    title: str


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
        return max(0.5, float(source.get("duration_seconds") or 5))
    except (TypeError, ValueError):
        return 5.0


def plan_assembly(video_track_id: str, nodes) -> AssemblyPlanV1:
    """按镜头序号铺排；调用方负责幂等过滤（已有 clip 的节点跳过）。"""

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
            )
        )
        cursor += duration
    return plan
