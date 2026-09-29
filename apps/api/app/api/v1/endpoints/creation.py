"""From-one-outline creation endpoints (从 0 建片).

The author writes one outline and reviews the shot list; building creates the
script node, the per-shot 设定图 image nodes and the per-shot film nodes and
starts one canvas run.  The guided-flow stages are internal.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.creation.outline_expander import (
    OutlineExpansionError,
    OutlineShotV1,
    plan_outline_build,
    request_outline_expansion,
)

router = APIRouter()


class ExpandOutlineRequest(BaseModel):
    outline: str = Field(min_length=1)


class ExpandOutlineResponse(BaseModel):
    success: bool
    shots: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""


class BuildFromOutlineRequest(BaseModel):
    workflow_id: str = Field(min_length=1)
    outline: str = Field(min_length=1)
    shots: list[dict[str, Any]] = Field(default_factory=list)


class BuildFromOutlineResponse(BaseModel):
    success: bool
    script_node_id: str = ""
    setting_node_ids: list[str] = Field(default_factory=list)
    film_node_ids: list[str] = Field(default_factory=list)
    execution_id: str = ""
    reused: bool = False


class AssembleFilmRequest(BaseModel):
    """S8 成片合成：把镜头 video 节点按序铺到 final-composition 时间线并渲染。"""

    workflow_id: str = Field(min_length=1)
    node_ids: list[str] = Field(default_factory=list)


class AssembleFilmResponse(BaseModel):
    success: bool
    render_id: str = ""
    clip_count: int = 0
    skipped: int = 0
    error: str = ""


@router.post("/expand-outline", response_model=ExpandOutlineResponse)
async def expand_outline(request: ExpandOutlineRequest) -> ExpandOutlineResponse:
    """创作纲领 → 分镜清单（一次 LLM 调用，无副作用）。"""

    settings = get_settings()
    try:
        plan = request_outline_expansion(settings=settings, outline=request.outline)
    except OutlineExpansionError as exc:
        return ExpandOutlineResponse(success=False, error=str(exc))
    return ExpandOutlineResponse(
        success=True,
        shots=[
            {
                "summary": shot.summary,
                "visual": shot.visual,
                "duration_seconds": shot.duration_seconds,
                "on_screen_text": shot.on_screen_text,
            }
            for shot in plan.shots
        ],
    )


@router.post("/build-from-outline", response_model=BuildFromOutlineResponse)
async def build_from_outline(
    request: BuildFromOutlineRequest,
    background_tasks: BackgroundTasks,
) -> BuildFromOutlineResponse:
    """分镜清单 → script 节点 + 每镜设定图 + 每镜成片节点 + 一次 run。"""

    from uuid import uuid4

    from app.api.v1.endpoints.replica import _canvas_node_service, _film_persistence_error
    from app.persistence.errors import V2PersistenceError
    from app.schemas.agent_canvas import CanvasNodeCreateRequestV2
    from app.schemas.agent_canvas_runtime import CanvasRunRequestV2

    node_service, workflow_repository = _canvas_node_service()
    try:
        workflow = workflow_repository.get_workflow(request.workflow_id)
    except V2PersistenceError as exc:
        raise _film_persistence_error(exc)

    shots = [
        OutlineShotV1(
            summary=str(shot.get("summary") or "").strip(),
            visual=str(shot.get("visual") or "").strip(),
            duration_seconds=float(shot.get("duration_seconds") or 5),
            on_screen_text=str(shot.get("on_screen_text") or "").strip(),
        )
        for shot in request.shots
        if str(shot.get("summary") or "").strip() and str(shot.get("visual") or "").strip()
    ]
    if not shots:
        raise HTTPException(status_code=422, detail="分镜清单为空（每条需要 summary 与 visual）。")

    plan = plan_outline_build(request.outline, type("P", (), {"shots": shots})())

    # Reuse: same shot count and a script node already titled 创作纲领 → reuse all.
    existing_settings = [
        n for n in workflow.nodes if n.node_type == "image" and (n.title or "").startswith("设定图")
    ]
    existing_film = [
        n for n in workflow.nodes if n.node_type == "video" and (n.title or "").startswith("成片镜头")
    ]
    script_node = next(
        (n for n in workflow.nodes if n.node_type == "script" and n.title == "创作纲领"), None
    )
    reused = bool(script_node) and len(existing_settings) == len(shots) and len(existing_film) == len(shots)

    script_id = script_node.node_id if script_node else ""
    setting_ids = [n.node_id for n in existing_settings] if reused else []
    film_ids = [n.node_id for n in existing_film] if reused else []

    if not reused:
        position = workflow.nodes[0].position if workflow.nodes else None
        base_x = float(position.x) if position else 80.0
        base_y = float(position.y) if position else 80.0
        try:
            created_script = node_service.create(
                request.workflow_id,
                CanvasNodeCreateRequestV2(
                    node_type="script",
                    creative_role="script",
                    title=plan.script_title,
                    generation_prompt=plan.script_text,
                    structured_content={"content": plan.script_text},
                    position={"x": base_x, "y": base_y},
                ),
                expected_revision=workflow.revision,
            )
        except V2PersistenceError as exc:
            raise _film_persistence_error(exc)
        script_id = created_script.node_id
        workflow = workflow_repository.get_workflow(request.workflow_id)

        for offset, node_plan in enumerate(plan.settings_nodes):
            try:
                created = node_service.create(
                    request.workflow_id,
                    CanvasNodeCreateRequestV2(
                        **node_plan,
                        position={
                            "x": base_x + 300.0 * offset,
                            "y": base_y + 260.0,
                        },
                    ),
                    expected_revision=workflow.revision,
                )
            except V2PersistenceError as exc:
                raise _film_persistence_error(exc)
            setting_ids.append(created.node_id)
            workflow = workflow_repository.get_workflow(request.workflow_id)

        for offset, node_plan in enumerate(plan.film_nodes):
            try:
                created = node_service.create(
                    request.workflow_id,
                    CanvasNodeCreateRequestV2(
                        **node_plan,
                        position={
                            "x": base_x + 300.0 * (offset % 3),
                            "y": base_y + 520.0 + 220.0 * (offset // 3),
                        },
                    ),
                    expected_revision=workflow.revision,
                )
            except V2PersistenceError as exc:
                raise _film_persistence_error(exc)
            film_ids.append(created.node_id)
            workflow = workflow_repository.get_workflow(request.workflow_id)

    from app.api.v2.endpoints.agent_canvas import create_agent_canvas_runtime
    from app.services.agent_canvas_accepted_background import (
        AcceptedBackgroundOperation,
        AcceptedBackgroundResourceType,
        AcceptedBackgroundWork,
    )

    settings = get_settings()
    runtime = create_agent_canvas_runtime(settings, bootstrap_model_policy=False)
    run_request = CanvasRunRequestV2(
        scope="selected_nodes",
        node_ids=(*setting_ids, *film_ids),
        retry_failed=True,
        source_action="outline_build",
    )
    try:
        accepted = runtime.run_service.start_or_extend(
            request.workflow_id,
            run_request,
            idempotency_key=f"outline-build-{request.workflow_id}-{uuid4().hex}",
            expected_revision=workflow.revision,
        )
    except V2PersistenceError as exc:
        raise _film_persistence_error(exc)
    background_tasks.add_task(
        runtime.accepted_background.run,
        AcceptedBackgroundWork(
            operation=AcceptedBackgroundOperation.CANVAS_RUN_RESUME,
            workflow_id=request.workflow_id,
            resource_type=AcceptedBackgroundResourceType.EXECUTION,
            resource_id=accepted.execution_id,
            callback=runtime.scheduler.resume,
            args=(accepted.execution_id,),
        ),
    )
    return BuildFromOutlineResponse(
        success=True,
        script_node_id=script_id,
        setting_node_ids=setting_ids,
        film_node_ids=film_ids,
        execution_id=accepted.execution_id,
        reused=reused,
    )


@router.post("/assemble-film", response_model=AssembleFilmResponse)
async def assemble_film(request: AssembleFilmRequest) -> AssembleFilmResponse:
    """S8：镜头节点 → 画布时间线 video track（按序铺满，幂等）。

    随后尝试 v2 final-composition 渲染；canvas 工作流不在 authoring 存储
    （2026-09-29 实机确认的架构缺口）时返回带码失败 + finding，不假装成片。
    """

    from app.api.v1.endpoints.replica import _canvas_node_service, _film_persistence_error
    from app.core.config import get_settings
    from app.persistence.database import create_v2_database
    from app.persistence.timeline_repository import TimelineRepository
    from app.services.creation.film_assembly import plan_assembly

    node_service, workflow_repository = _canvas_node_service()
    try:
        workflow = workflow_repository.get_workflow(request.workflow_id)
    except Exception as exc:  # noqa: BLE001 - mapped below
        raise _film_persistence_error(exc)

    nodes = [n for n in workflow.nodes if n.node_id in set(request.node_ids)]
    if not nodes:
        return AssembleFilmResponse(success=False, error="没有等到任何镜头节点。")
    missing = [n.node_id for n in nodes if not n.output_asset_id]
    if missing:
        return AssembleFilmResponse(
            success=False,
            error=f"{len(missing)} 个镜头尚未生成完（asset 未就绪），无法合成。",
        )

    settings = get_settings()
    database = create_v2_database(settings.media_data_dir)
    session = database.session_factory()
    try:
        repo = TimelineRepository(session)
        timeline = repo.get_by_workflow_id(request.workflow_id)
        video_track = next((t for t in repo.get_tracks(timeline.timeline_id) if t.type == "video"), None)
        if video_track is None:
            return AssembleFilmResponse(success=False, error="时间线上没有 video track。")
        plan = plan_assembly(video_track.track_id, nodes)
        placed = 0
        for clip in plan.placements:
            existing = repo.get_clips_for_node(clip.source_node_id)
            if existing:
                continue
            repo.add_clip(
                track_id=clip.track_id,
                start_time=clip.start_time,
                duration=clip.duration,
                asset_id=clip.asset_id,
                asset_version_id=clip.asset_version_id,
                source_node_id=clip.source_node_id,
            )
            placed += 1
        session.commit()
    except Exception as exc:  # noqa: BLE001 - mapped below
        session.rollback()
        raise _film_persistence_error(exc)
    finally:
        session.close()

    # 最终渲染：标准 v2 栈。canvas 工作流不在 authoring 存储时明确失败。
    render_error = ""
    try:
        from app.schemas.workflow_v2 import WorkflowV2TimelineRenderRequest
        from app.services.creation.canvas_render_bridge import (
            BridgeShotV1,
            bridge_canvas_workflow,
            ensure_canvas_asset_projections,
        )
        from app.services.v2_final_composition_render_service import (
            V2FinalCompositionRenderService,
        )
        from app.services.v2_final_composition_timeline import (
            V2FinalCompositionTimelineService,
        )

        timeline_service = V2FinalCompositionTimelineService(settings)
        # 桥：canvas 工作流 + 资产投影进 v2 存储，标准渲染栈才够得着（幂等）。
        ensure_canvas_asset_projections(
            settings, [str(n.output_asset_id) for n in nodes if n.output_asset_id]
        )
        bridge_canvas_workflow(
            settings,
            request.workflow_id,
            project_id=getattr(workflow, "project_id", None),
            name=str(
                getattr(workflow, "name", None)
                or getattr(workflow, "title", None)
                or "拉片复刻成片"
            ),
            shots=[
                BridgeShotV1(
                    index=index,
                    asset_id=str(n.output_asset_id),
                    asset_version_id=n.output_asset_version_id,
                    duration_seconds=1.0,
                )
                for index, n in enumerate(
                    sorted(
                        (x for x in nodes if x.output_asset_id),
                        key=lambda x: x.node_id,
                    ),
                    start=1,
                )
            ],
        )
        timeline = timeline_service.get_timeline(request.workflow_id)
        started = V2FinalCompositionRenderService(settings).start_render(
            request.workflow_id,
            WorkflowV2TimelineRenderRequest(
                timeline_id=timeline.timeline.timeline_id,
                timeline_version=timeline.timeline.version,
            ),
        )
        render_id = started.render_id
    except Exception as exc:  # noqa: BLE001 - 渲染缺口如实上报
        render_id = ""
        render_error = (
            "final_render_unavailable_for_canvas_workflow: v2 final-composition 渲染栈绑在 "
            f"authoring 存储（workflows 表为空），够不到 canvas 工作流：{str(exc)[:200]}"
        )

    return AssembleFilmResponse(
        success=True,
        render_id=render_id,
        clip_count=placed,
        skipped=len(plan.placements) - placed,
        error=render_error,
    )
