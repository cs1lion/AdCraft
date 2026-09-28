"""拉片复刻 · direct-execute 渲染桥（ADR 0010 R3 后端半边）。

把可行性门编译出的零模型费时间线写进工作流的 final-composition 时间线
（``V2FinalCompositionTimelineService``），再复用剪辑域的耐久 detached
渲染服务（``V2FinalCompositionRenderService.start_render``）出片——
**不建第二执行链**（ADR 0010 的接口契约）。前端拿到 ``render_id`` 后
轮询 ``GET /workflows/{id}/final-composition/renders/{render_id}``。

链式步骤（全部可单测，服务以参数注入）：

1. ``plan_direct_execute`` —— 可行性门（非可行直接拒绝，带 rejected 清单）；
2. ``plan_direct_execute_render`` —— 编译 canonical timeline；
3. ``resolve_library_clip`` ×N —— 可选的人工库素材解析回填；
4. 剥掉未解析的哨兵 clip（见下方"诚实边界"）；
5. ``get_timeline`` → ``save_timeline``（乐观锁 expected_version）；
6. ``start_render`` —— 耐久渲染（可轮询/可取消/可重放）。

诚实边界（写进响应，不隐瞒）：

- **非可行即拒绝**：渲染桥不降低门的标准，``rejected`` 原样透出；
- **未解析库素材不计入**：BGM/SFX 的哨兵 clip（``enabled=False``、
  ``source_asset_id=__pending_library_resolution__``）不是真实资产——
  写进 v2 时间线会被 ``_validate_clip_source`` 以 404 拒。因此在写盘前
  剥掉，被剥的 clip id 随 ``dropped_unresolved_clip_ids`` 透出，前端可
  明说"BGM/SFX 未解析，未计入本次直出"；
- **写盘替换当前 final 时间线**：用户在时间线编辑器里的改动会被这份
  复刻时间线取代——``previous_timeline_version`` 随响应透出。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
from app.schemas.workflow_v2 import (
    WorkflowV2Timeline,
    WorkflowV2TimelineClip,
    WorkflowV2TimelineRenderRequest,
    WorkflowV2TimelineRenderStartResponse,
    WorkflowV2TimelineUpdateRequest,
)
from app.services.replica.direct_execute import DirectExecutePlan, plan_direct_execute
from app.services.replica.direct_execute_render import (
    UNRESOLVED_LIBRARY_ASSET_ID,
    plan_direct_execute_render,
    resolve_library_clip,
    unresolved_intents_of,
)


class ReplicaRenderNotFeasible(ValueError):
    """蓝图未过可行性门：拒绝渲染，rejected 透出缺失清单。

    ``rejected`` 可以是 str（blockers）或 dict（generation_steps 的成本条目）——
    统一规范成可读字符串，端点原样透出，不吞信息。
    """

    def __init__(self, rejected: tuple[Any, ...]) -> None:
        self.rejected: tuple[str, ...] = tuple(
            str(item.get("step") or item) if isinstance(item, dict) else str(item)
            for item in rejected
        )
        super().__init__("; ".join(self.rejected) or "blueprint is not direct-execute feasible")


@dataclass(frozen=True)
class ReplicaLibraryResolution:
    """一条人工库素材解析（clip_id → 真实 asset/version）。"""

    clip_id: str
    asset_id: str
    version_id: str


@dataclass(frozen=True)
class ReplicaRenderOutcome:
    """渲染桥的完整结果（可序列化，供端点直接转响应）。"""

    workflow_id: str
    render_id: str
    status: str
    timeline_id: str
    timeline_version: int
    previous_timeline_version: int
    subtitle_cue_count: int
    needs_placeholder_video: bool
    unresolved_assets: tuple[dict[str, Any], ...] = ()
    dropped_unresolved_clip_ids: tuple[str, ...] = ()
    events_cursor: int = 0
    output_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # P4 pace 预检告警（预估口播超窗）：渲染发起时随响应透出
    pace_warnings: tuple[dict[str, Any], ...] = ()

def strip_unresolved_clips(
    timeline: WorkflowV2Timeline,
) -> tuple[WorkflowV2Timeline, tuple[str, ...]]:
    """剥掉未解析库素材的哨兵 clip，返回 (新时间线, 被剥 clip id)。

    哨兵 clip 一律 ``enabled=False``（渲染器本就跳过）；剥掉它们不改变
    enabled 末端，因此时长口径不变。没有哨兵时原样返回（同一对象）。
    """
    keep: list[WorkflowV2TimelineClip] = []
    dropped: list[str] = []
    for clip in timeline.clips:
        if clip.source_asset_id == UNRESOLVED_LIBRARY_ASSET_ID:
            dropped.append(clip.clip_id)
            continue
        keep.append(clip)
    if not dropped:
        return timeline, ()
    used_tracks = {clip.track_id for clip in keep}
    tracks = [track for track in timeline.tracks if track.track_id in used_tracks]
    return (
        timeline.model_copy(
            update={"clips": keep, "tracks": tracks},
            deep=True,
        ),
        tuple(dropped),
    )


def render_replica_blueprint(
    workflow_id: str,
    blueprint: ReplicaBlueprintContentV2,
    *,
    library_resolutions: tuple[ReplicaLibraryResolution, ...] = (),
    timeline_service: Any,
    render_service: Any,
) -> ReplicaRenderOutcome:
    """复刻蓝图 → 工作流 final 时间线 → 耐久渲染（R3 桥本体）。

    ``timeline_service`` / ``render_service`` 以参数注入（端点用依赖，
    测试用 fake）——本函数自身不发 HTTP、不直接读盘。
    """
    gate: DirectExecutePlan = plan_direct_execute(blueprint)
    if not gate.feasible:
        raise ReplicaRenderNotFeasible(gate.blockers + gate.generation_steps)

    render_plan = plan_direct_execute_render(blueprint, gate)
    if not render_plan.feasible:  # 双重防线：门与编译层结论不一致时拒绝
        raise ReplicaRenderNotFeasible(render_plan.rejected)

    timeline = render_plan.timeline
    for resolution in library_resolutions:
        timeline = resolve_library_clip(
            timeline,
            clip_id=resolution.clip_id,
            asset_id=resolution.asset_id,
            version_id=resolution.version_id,
        )
    timeline, dropped = strip_unresolved_clips(timeline)
    unresolved = tuple(dict(entry) for entry in unresolved_intents_of(timeline))

    current = timeline_service.get_timeline(workflow_id)
    previous_version = int(current.timeline.version)

    saved = timeline_service.save_timeline(
        workflow_id,
        WorkflowV2TimelineUpdateRequest(
            expected_version=previous_version,
            timeline=timeline,
        ),
    )

    started: WorkflowV2TimelineRenderStartResponse = render_service.start_render(
        workflow_id,
        WorkflowV2TimelineRenderRequest(
            timeline_id=saved.timeline.timeline_id,
            timeline_version=saved.timeline.version,
        ),
    )

    return ReplicaRenderOutcome(
        workflow_id=workflow_id,
        render_id=started.render_id,
        status=started.status,
        timeline_id=saved.timeline.timeline_id,
        timeline_version=saved.timeline.version,
        previous_timeline_version=previous_version,
        subtitle_cue_count=render_plan.subtitle_cue_count,
        needs_placeholder_video=render_plan.needs_placeholder_video,
        unresolved_assets=unresolved,
        dropped_unresolved_clip_ids=dropped,
        events_cursor=getattr(started, "events_cursor", 0),
        output_url=getattr(started, "output_url", None),
        pace_warnings=tuple(dict(w) for w in gate.pace_warnings),
    )
