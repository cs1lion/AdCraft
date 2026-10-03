"""From-one-outline creation endpoints (从 0 建片).

The author writes one outline and reviews the shot list; building creates the
script node, the per-shot 设定图 image nodes and the per-shot film nodes and
starts one canvas run.  The guided-flow stages are internal.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from app.services.creation.replica_composition import ReplicaAudioPlacementV1

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
    replica_node_id: str | None = Field(default=None, min_length=1)
    include_captions: bool = False
    audio_clips: list[ReplicaAudioPlacementV1] = Field(default_factory=list, max_length=64)
    source_audio_policy: Literal["mute", "preserve"] = "mute"
    ducking: bool = False


class AssembleFilmResponse(BaseModel):
    success: bool
    render_id: str = ""
    clip_count: int = 0
    skipped: int = 0
    error: str = ""
    effective_render_mode: str = "simple_sequence"
    composition_plan_hash: str | None = None
    warnings: list[str] = Field(default_factory=list)
    caption_timing_quality: str | None = None


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
        n
        for n in workflow.nodes
        if n.node_type == "video" and (n.title or "").startswith("成片镜头")
    ]
    script_node = next(
        (n for n in workflow.nodes if n.node_type == "script" and n.title == "创作纲领"), None
    )
    reused = (
        bool(script_node)
        and len(existing_settings) == len(shots)
        and len(existing_film) == len(shots)
    )

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

        # 设定图 → 成片镜头的参考图绑定：视频节点因此等设定图生成完毕，以其为
        # image_reference 出片（依赖由绑定驱动，run 自然排序）。走 runtime 的
        # bindings 服务（与 v2 端点同款，带角色/世界设定策略校验）。
        from app.api.v2.endpoints.agent_canvas import create_agent_canvas_runtime
        from app.core.config import get_settings
        from app.schemas.agent_canvas import CanvasBindingCreateRequestV2

        settings = get_settings()

        runtime = create_agent_canvas_runtime(settings, bootstrap_model_policy=False)
        for setting_id, film_id in zip(setting_ids, film_ids):
            try:
                runtime.bindings.create(
                    request.workflow_id,
                    CanvasBindingCreateRequestV2(
                        source={"kind": "node_output", "source_node_id": setting_id},
                        target_node_id=film_id,
                        input_role="image_reference",
                    ),
                    expected_revision=workflow.revision,
                )
            except V2PersistenceError as exc:
                raise _film_persistence_error(exc)
            workflow = workflow_repository.get_workflow(request.workflow_id)

    from app.api.v2.endpoints.agent_canvas import create_agent_canvas_runtime
    from app.services.agent_canvas_accepted_background import (
        AcceptedBackgroundOperation,
        AcceptedBackgroundResourceType,
        AcceptedBackgroundWork,
    )

    # runtime 与 settings 在绑定段已构造，直接复用
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

    同一份镜头计划投影到 authoring 存储后走标准 v2 渲染；失败原文透出，
    不把铺好 canvas 时间线误报成已生成成片。
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

    requested_ids = set(request.node_ids)
    nodes = [n for n in workflow.nodes if n.node_id in requested_ids]
    if not nodes:
        return AssembleFilmResponse(success=False, error="没有等到任何镜头节点。")
    if requested_ids != {n.node_id for n in nodes} or any(n.node_type != "video" for n in nodes):
        return AssembleFilmResponse(
            success=False, error="镜头列表包含缺失或非 video 节点，无法合成。"
        )
    missing = [n.node_id for n in nodes if not n.output_asset_id]
    if missing:
        return AssembleFilmResponse(
            success=False,
            error=f"{len(missing)} 个镜头尚未生成完（asset 未就绪），无法合成。",
        )

    settings = get_settings()
    composition = None
    warnings: list[str] = []
    if (
        request.replica_node_id
        or request.include_captions
        or request.audio_clips
        or request.ducking
    ):
        if not request.replica_node_id:
            raise HTTPException(
                status_code=422, detail="replica_node_id is required for replica composition"
            )
        from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2

        replica_node = next(
            (
                n
                for n in workflow.nodes
                if n.node_id == request.replica_node_id and n.node_type == "replica"
            ),
            None,
        )
        if replica_node is None:
            raise HTTPException(
                status_code=422, detail="replica node does not belong to this workflow"
            )
        blueprint = ReplicaBlueprintContentV2.model_validate(replica_node.structured_content)
        from app.services.v2_final_composition_timeline import V2FinalCompositionTimelineService

        existing_final = V2FinalCompositionTimelineService(settings)._load_timeline(
            request.workflow_id
        )
        if existing_final and existing_final.metadata.get("edit_mode") == "user_edited":
            return AssembleFilmResponse(
                success=False,
                error="用户编辑时间线已保留，请在剪辑器局部更新后渲染。",
                warnings=["replica_user_timeline_preserved"],
                effective_render_mode="timeline_editor",
            )
        for audio in request.audio_clips:
            asset = next((a for a in workflow.assets if a.asset_id == audio.asset_id), None)
            if (
                asset is None
                or asset.media_type != "audio"
                or getattr(asset, "version_id", None) != audio.asset_version_id
            ):
                raise HTTPException(
                    status_code=422,
                    detail="audio selection requires a current audio version from this workflow",
                )
            measured_duration = getattr(asset, "duration_seconds", None)
            if (
                measured_duration is not None
                and audio.trim_start_seconds + audio.duration_seconds > measured_duration + 0.001
            ):
                raise HTTPException(
                    status_code=422, detail="audio trim exceeds the selected asset duration"
                )
    database = create_v2_database(settings.media_data_dir)
    session = database.session_factory()
    try:
        repo = TimelineRepository(session)
        timeline = repo.get_by_workflow_id(request.workflow_id)
        video_track = next(
            (t for t in repo.get_tracks(timeline.timeline_id) if t.type == "video"), None
        )
        if video_track is None:
            return AssembleFilmResponse(success=False, error="时间线上没有 video track。")
        plan = plan_assembly(video_track.track_id, nodes)
        if (
            request.replica_node_id
            or request.include_captions
            or request.audio_clips
            or request.ducking
        ):
            from app.services.creation.replica_composition import plan_replica_composition

            try:
                composition = plan_replica_composition(
                    plan,
                    replica_node_id=request.replica_node_id,
                    blueprint=blueprint,
                    include_captions=request.include_captions,
                    audio_clips=request.audio_clips,
                    source_audio_policy=request.source_audio_policy,
                    fps=timeline.fps,
                    ducking=request.ducking,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            warnings.extend(composition.warnings)
            video_clips = [c for c in composition.timeline.clips if c.clip_type == "video"]
            plan.placements = [
                replace(p, start_time=c.start_time, duration=c.duration)
                for p, c in zip(plan.placements, video_clips, strict=True)
            ]
        if composition is not None:
            requested_sources = {p.source_node_id for p in plan.placements}
            for track in repo.get_tracks(timeline.timeline_id):
                clips_on_track = repo.get_clips_for_track(track.track_id)
                non_owned = [
                    c
                    for c in clips_on_track
                    if c.source_node_id not in requested_sources
                    and not (c.source_node_id or "").startswith(composition.owner_id + ":")
                ]
                if track.locked or non_owned:
                    return AssembleFilmResponse(
                        success=False,
                        error="时间线含手工内容或锁定轨道，自动编排已暂停；请在剪辑器确认更新。",
                        warnings=["replica_manual_timeline_preserved"],
                        effective_render_mode="timeline_editor",
                    )
        placed = 0
        for clip in plan.placements:
            existing = [
                item
                for item in repo.get_clips_for_node(clip.source_node_id)
                if item.track_id == video_track.track_id
            ]
            if existing:
                current = existing[0]
                # Refresh rerun assets in place; never touch another timeline or manual clips.
                repo.update_clip(
                    current.clip_id,
                    start_time=clip.start_time,
                    duration=clip.duration,
                    asset_id=clip.asset_id,
                    asset_version_id=clip.asset_version_id,
                )
                for duplicate in existing[1:]:
                    repo.delete_clip(duplicate.clip_id)
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
        if composition is not None:
            from app.schemas.timeline import TimelineDuckingConfigV1, TimelineVolumeKeyframeV1

            tracks = {t.type: t for t in repo.get_tracks(timeline.timeline_id)}
            repo.update_track(tracks["video"].track_id, muted=request.source_audio_policy == "mute")
            for role in ("voice", "bgm", "sfx"):
                repo.update_track(tracks[role].track_id, volume=1, muted=False)
            desired_sources = {
                c.clip_id for c in composition.timeline.clips if c.clip_type != "video"
            }
            for target in tracks.values():
                for old_clip in repo.get_clips_for_track(target.track_id):
                    if (old_clip.source_node_id or "").startswith(
                        composition.owner_id + ":"
                    ) and old_clip.source_node_id not in desired_sources:
                        repo.delete_clip(old_clip.clip_id)
            for clip in composition.timeline.clips:
                if clip.clip_type == "video":
                    continue
                role = "subtitle" if clip.clip_type == "subtitle" else clip.metadata["audio_role"]
                target = tracks[role]
                if target.locked:
                    warnings.append(f"locked_track_preserved:{role}")
                    continue
                source_id = clip.clip_id
                existing = [
                    c for c in repo.get_clips_for_node(source_id) if c.track_id == target.track_id
                ]
                values = dict(
                    start_time=clip.start_time,
                    duration=clip.duration,
                    asset_id=clip.source_asset_id,
                    asset_version_id=clip.source_version_id,
                    source_start=clip.trim_in,
                    source_duration=clip.duration,
                    fade_in=clip.audio.fade_in_seconds,
                    fade_out=clip.audio.fade_out_seconds,
                    subtitle_text=clip.text,
                    label=f"Replica {role}",
                    volume_keyframes=(
                        TimelineVolumeKeyframeV1(time_seconds=0, value=clip.audio.volume),
                    )
                    if clip.clip_type == "audio"
                    else (),
                )
                if existing:
                    repo.update_clip(existing[0].clip_id, **values)
                else:
                    repo.add_clip(track_id=target.track_id, source_node_id=source_id, **values)
            repo.update_timeline(
                timeline.timeline_id,
                ducking=TimelineDuckingConfigV1(enabled=request.ducking),
                duration_seconds=max(
                    composition.timeline.duration_seconds,
                    max(
                        (
                            c.start_time + c.duration
                            for t in repo.get_tracks(timeline.timeline_id)
                            for c in repo.get_clips_for_track(t.track_id)
                        ),
                        default=0,
                    ),
                ),
            )
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 - mapped below
        session.rollback()
        raise _film_persistence_error(exc)
    finally:
        session.close()

    # 最终渲染：用同一份计划桥接存储后走标准 v2 栈。
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

        render_settings = (
            replace(settings, final_composition_render_mode="timeline_editor")
            if composition
            else settings
        )
        timeline_service = V2FinalCompositionTimelineService(render_settings)
        # 桥：canvas 工作流 + 资产投影进 v2 存储，标准渲染栈才够得着（幂等）。
        ensure_canvas_asset_projections(
            settings,
            [str(n.output_asset_id) for n in nodes if n.output_asset_id]
            + [a.asset_id for a in request.audio_clips],
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
                    asset_id=clip.asset_id,
                    asset_version_id=clip.asset_version_id,
                    duration_seconds=clip.duration,
                )
                for index, clip in enumerate(plan.placements, start=1)
            ],
            **(
                {
                    "composition_plan_hash": composition.plan_hash,
                    "audio_mode": "full"
                    if request.audio_clips or request.source_audio_policy == "preserve"
                    else "none",
                }
                if composition
                else {}
            ),
        )
        timeline = timeline_service.get_timeline(request.workflow_id)
        if composition is not None:
            if timeline.timeline.metadata.get("edit_mode") == "user_edited":
                warnings.append("replica_user_timeline_preserved")
            else:
                timeline = timeline_service.save_system_timeline(
                    request.workflow_id,
                    composition.timeline,
                    expected_version=timeline.timeline.version,
                )
        started = V2FinalCompositionRenderService(render_settings).start_render(
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
            "final_render_unavailable_for_canvas_workflow: "
            f"最终渲染或存储桥接失败：{str(exc)[:200]}"
        )

    return AssembleFilmResponse(
        success=True,
        render_id=render_id,
        clip_count=placed,
        skipped=len(plan.placements) - placed,
        error=render_error,
        effective_render_mode="timeline_editor"
        if composition
        else getattr(settings, "final_composition_render_mode", "simple_sequence"),
        composition_plan_hash=composition.plan_hash if composition else None,
        warnings=warnings,
        caption_timing_quality="authored_shot"
        if composition and request.include_captions
        else None,
    )
