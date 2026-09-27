"""拉片复刻（Replica）API 端点。

当前最小可用切片：

- POST /replica/teardown — 上传（或按 asset_id 引用）一条参考视频，
  返回结构化拉片拆解报告（整片解读 / 结构 Beats / 镜头表 / 节奏 / 视觉
  系统）与"复刻分镜草稿"文本，可直接粘贴进 script 节点或对话，进入
  正常创作流。

输入约定与 scene_3d 的 /analyze-reference 保持一致：multipart 上传走临时
文件；asset_id 走 reference_upload 的安全解析（限定上传目录，防路径穿越）。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.services.replica.adreplica import (
    AdReplicaParseError,
    adreplica_filename,
    adreplica_from_blueprint,
    blueprint_from_adreplica,
)
from app.services.replica.blueprint import (
    apply_slot_updates,
    blueprint_from_teardown,
    plan_script_instantiation,
    render_replica_script,
)
from app.services.replica.teardown import (
    DEFAULT_NUM_FRAMES,
    MAX_NUM_FRAMES,
    MIN_NUM_FRAMES,
    AnalysisError,
    analyze_reference_teardown,
)
from app.schemas.agent_canvas import CanvasNodeCreateRequestV2
from app.services.agent_canvas_nodes import AgentCanvasNodeService
from app.services.scene3d.reference_upload import get_reference_video_path

router = APIRouter(prefix="/replica", tags=["replica"])

ALLOWED_SUFFIXES = {".mp4", ".webm", ".mov", ".m4v"}


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class TeardownResponse(BaseModel):
    success: bool
    report: dict[str, Any] = Field(default_factory=dict)
    frame_analyses: list[dict[str, Any]] = Field(default_factory=list)
    video_metadata: dict[str, Any] = Field(default_factory=dict)
    num_frames_analyzed: int = 0
    user_description: str | None = None


class BlueprintRequest(BaseModel):
    """teardown 报告 → 复刻蓝图。"""

    report: dict[str, Any]
    source_video_asset_id: str = ""
    duration_seconds: float = 0.0
    aspect: str = ""
    replica_goal: str = ""


class BlueprintResponse(BaseModel):
    success: bool
    blueprint: dict[str, Any] = Field(default_factory=dict)
    replica_script: str = ""


class AdReplicaExportRequest(BaseModel):
    """复刻蓝图（replica 节点内容）→ .adreplica 标记文本。"""

    blueprint: dict[str, Any]


class AdReplicaExportResponse(BaseModel):
    success: bool
    adreplica: str = ""
    filename: str = ""


class AdReplicaImportRequest(BaseModel):
    """.adreplica 标记文本 → 复刻蓝图（文档即真相源：改文本 = 改蓝图）。"""

    adreplica: str = Field(min_length=1, max_length=200_000)


class StyleVariantsRequest(BaseModel):
    """复刻蓝图 → N 个风格变体候选（Jev 式确定性风格导演）。"""

    blueprint: dict[str, Any]
    n: int = Field(default=5, ge=1, le=12)
    mix_size: int = Field(default=1, ge=1, le=3)


class StyleVariantsResponse(BaseModel):
    success: bool
    variants: list[dict[str, Any]] = Field(default_factory=list)


class IngestLinkRequest(BaseModel):
    """视频链接 → 服务端下载（与上传同一套校验/存储）。"""

    url: str = Field(min_length=1, max_length=2_048)


class IngestLinkResponse(BaseModel):
    success: bool
    asset_id: str = ""
    file_name: str = ""
    source_url: str = ""


class DirectExecuteRequest(BaseModel):
    """复刻蓝图 → direct-execute 可行性判定（零模型费门）。"""

    blueprint: dict[str, Any]


class DirectExecuteResponse(BaseModel):
    success: bool
    feasible: bool = False
    blockers: list[str] = Field(default_factory=list)
    zero_model_steps: list[dict[str, Any]] = Field(default_factory=list)
    generation_steps: list[dict[str, Any]] = Field(default_factory=list)


class DirectExecuteRenderRequest(BaseModel):
    """复刻蓝图 + 可行性判定结果 → 零模型费渲染计划（ADR 0010 R1）。"""

    blueprint: dict[str, Any]
    plan: dict[str, Any]


class DirectExecuteRenderResponse(BaseModel):
    success: bool
    feasible: bool = False
    # WorkflowV2Timeline 序列化形式（直接喂给剪辑域渲染服务）
    timeline: dict[str, Any] | None = None
    # 渲染器要求至少一个 enabled video clip；纯字幕片此处诚实标注
    needs_placeholder_video: bool = False
    subtitle_cue_count: int = 0
    rejected: list[str] = Field(default_factory=list)


class InstantiateRequest(BaseModel):
    """蓝图（replica 节点内容）→ script 节点 + 返回锚定关系。"""

    workflow_id: str = Field(min_length=1)
    replica_node_id: str = Field(min_length=1)
    slot_updates: dict[str, str] = Field(default_factory=dict)


class InstantiateResponse(BaseModel):
    success: bool
    script_node_id: str = ""
    script_text: str = ""
    workflow_revision: int = 0
    binding_id: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _frame_analysis_to_dict(frame: Any) -> dict[str, Any]:
    return {
        "frame_index": frame.frame_index,
        "timestamp_seconds": frame.timestamp_seconds,
        "scene_type": frame.scene_type,
        "environment_description": frame.environment_description,
        "lighting": frame.lighting,
        "camera_angle": frame.camera_angle,
        "shot_size": frame.shot_size,
        "camera_motion_hint": frame.camera_motion_hint,
        "characters": frame.characters,
        "props": frame.props,
        "on_screen_text": frame.on_screen_text,
        "notable_elements": frame.notable_elements,
    }


def _video_metadata_to_dict(metadata: Any) -> dict[str, Any]:
    return {
        "duration_seconds": metadata.duration_seconds,
        "width": metadata.width,
        "height": metadata.height,
        "frame_rate": metadata.frame_rate,
        "frame_count": metadata.frame_count,
        "codec_name": metadata.codec_name,
        "file_size_bytes": metadata.file_size_bytes,
    }


async def _resolve_source_path(
    file: UploadFile | None,
    asset_id: str | None,
) -> tuple[Path, bool]:
    """Resolve the video to analyze. Returns (path, is_temp).

    Priority: multipart upload (temp file) > asset_id lookup under the
    reference-videos upload dir (traversal-safe resolver).
    """
    if file is not None and file.filename:
        return await _save_temp_upload(file), True

    if asset_id:
        resolved = get_reference_video_path(asset_id)
        if resolved is None:
            raise HTTPException(
                status_code=404,
                detail=f"Reference video asset not found: {asset_id}",
            )
        return resolved, False

    raise HTTPException(
        status_code=400,
        detail="Provide either an uploaded file or an asset_id of a reference video",
    )


async def _save_temp_upload(file: UploadFile) -> Path:
    """Persist an uploaded video to a temp file for analysis."""
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    suffix = Path(file.filename or "reference.mp4").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        suffix = ".mp4"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        return Path(tmp.name)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/teardown", response_model=TeardownResponse)
async def teardown_reference_video(
    file: UploadFile | None = File(None),
    asset_id: str | None = Form(None),
    user_description: str | None = Form(None),
    num_frames: int = Form(DEFAULT_NUM_FRAMES),
) -> TeardownResponse:
    """拉片复刻：拆解一条参考视频，产出结构化拆解报告 + 复刻分镜草稿。

    参考视频 → 抽帧 → 多模态 LLM 读片 → 整片解读/结构/镜头表/节奏/系统
    → 复刻分镜草稿（可直接进入正常创作流）。

    Product boundary (also surfaced in report.constraints): the teardown
    replicates STRUCTURE AND RELATIONSHIPS, not pixels — shot boundaries and
    camera motion are LLM inferences from sparse frames, not measurements.
    """
    video_path, is_temp = await _resolve_source_path(file, asset_id)

    clamped_frames = max(MIN_NUM_FRAMES, min(MAX_NUM_FRAMES, int(num_frames)))

    try:
        # LLM 调用是阻塞的：放到线程池，避免拖住事件循环。
        result = await asyncio.to_thread(
            analyze_reference_teardown,
            video_path=video_path,
            num_frames=clamped_frames,
            user_description=user_description,
        )
    except AnalysisError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": str(exc), "error_type": exc.error_type},
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500,
            detail=f"Teardown analysis failed: {str(exc)[:200]}",
        )
    finally:
        if is_temp:
            try:
                os.unlink(video_path)
            except Exception:
                pass

    return TeardownResponse(
        success=True,
        report=result.report.model_dump(mode="json"),
        frame_analyses=[_frame_analysis_to_dict(f) for f in result.frame_analyses],
        video_metadata=_video_metadata_to_dict(result.video_metadata),
        num_frames_analyzed=result.num_frames_analyzed,
        user_description=result.user_description,
    )


# ---------------------------------------------------------------------------
# Blueprint & instantiation（拉片复刻的"复刻"半场）
# ---------------------------------------------------------------------------


@router.post("/blueprint", response_model=BlueprintResponse)
async def build_blueprint(request: BlueprintRequest) -> BlueprintResponse:
    """teardown 报告 → 复刻蓝图（可编辑、可实例化）。

    纯转换：不调 LLM、不落库。蓝图随后作为 ``replica`` 节点的
    structured_content 持久化（前端经画布节点 API 创建）。
    """
    blueprint = blueprint_from_teardown(
        request.report,
        source_asset_id=request.source_video_asset_id,
        duration_seconds=request.duration_seconds,
        aspect=request.aspect,
        replica_goal=request.replica_goal,
    )
    return BlueprintResponse(
        success=True,
        blueprint=blueprint.model_dump(mode="json"),
        replica_script=render_replica_script(blueprint),
    )


@router.post("/blueprint/style-variants", response_model=StyleVariantsResponse)
async def plan_blueprint_style_variants(
    request: StyleVariantsRequest,
) -> StyleVariantsResponse:
    """蓝图 → N 个风格变体候选（调研档 §4.4 Jev 式风格导演的确定性实现）。

    纯转换：不调 LLM、不落库、可复现（seed 派生自蓝图内容）。多风格组合
    候选（mix_size>1）返回但标记 ``mixable_applied=false``——多风格并行
    激活尚未支持，前端只允许把单风格应用进风格槽位。
    """
    from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
    from app.services.replica.variants import (
        StyleVariantError,
        plan_style_variants,
    )

    try:
        blueprint = ReplicaBlueprintContentV2.model_validate(request.blueprint)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid replica blueprint content: {exc}",
        )
    try:
        variants = plan_style_variants(
            blueprint, n=request.n, mix_size=request.mix_size
        )
    except StyleVariantError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc)})
    return StyleVariantsResponse(
        success=True,
        variants=[
            {
                "variant_id": v.variant_id,
                "skill_ids": list(v.skill_ids),
                "names": list(v.names),
                "score": v.score,
                "rationale": v.rationale,
                "mixable_applied": v.mixable_applied,
            }
            for v in variants
        ],
    )


@router.post("/ingest-link", response_model=IngestLinkResponse)
async def ingest_reference_from_link(request: IngestLinkRequest) -> IngestLinkResponse:
    """粘贴视频链接 → yt-dlp 下载 → 与上传同一套校验/存储（hypit media fetch）。

    yt-dlp 是可选外部工具：未安装/下载失败/产物不合格都返回结构化错误
    （error_type 明确），前端展示原因——静默降级禁止。下载走临时目录，
    成功后经 ``save_reference_video`` 与本地上传同流（≤60s、抽帧、asset_id）。
    """
    import asyncio

    from app.services.replica.ingest import IngestError, ingest_reference_link

    try:
        result = await asyncio.to_thread(
            ingest_reference_link, request.url.strip()
        )
    except IngestError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": str(exc), "error_type": exc.code},
        )
    return IngestLinkResponse(
        success=True,
        asset_id=result.asset_id,
        file_name=result.file_name,
        source_url=result.source_url,
    )


@router.post("/blueprint/direct-execute-plan", response_model=DirectExecuteResponse)
async def plan_blueprint_direct_execute(
    request: DirectExecuteRequest,
) -> DirectExecuteResponse:
    """蓝图 → direct-execute 可行性门（零模型费/需生成的确定性成本清单）。

    纯转换：不调 LLM、不落库。完整直出渲染器属于剪辑域（ADR 0008）；
    本端点回答"这条片子能不能零模型费直出、缺什么"——结果喂给既有
    工作流做执行决策，而不是绕开它。
    """
    from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
    from app.services.replica.direct_execute import plan_direct_execute

    try:
        blueprint = ReplicaBlueprintContentV2.model_validate(request.blueprint)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid replica blueprint content: {exc}",
        )
    plan = plan_direct_execute(blueprint)
    return DirectExecuteResponse(success=True, **plan.to_dict())


@router.post("/blueprint/direct-execute", response_model=DirectExecuteRenderResponse)
async def plan_blueprint_direct_execute_render(
    request: DirectExecuteRenderRequest,
) -> DirectExecuteRenderResponse:
    """蓝图 + 可行性门 → 零模型费剪辑时间线（ADR 0010 R1 字幕轨直出本体）。

    纯转换：不调 LLM、不落库。产出的 clips 可直接喂给 editing 域既有
    ``V2FinalCompositionRenderService`` 出片。non-feasible 蓝图返回
    feasible=False + rejected 清单，不产出 clips。
    """
    from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
    from app.services.replica.direct_execute import DirectExecutePlan
    from app.services.replica.direct_execute_render import (
        plan_direct_execute_render,
    )

    try:
        blueprint = ReplicaBlueprintContentV2.model_validate(request.blueprint)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid replica blueprint content: {exc}",
        )
    try:
        gate = DirectExecutePlan(
            feasible=bool(request.plan.get("feasible", False)),
            blockers=tuple(request.plan.get("blockers", [])),
            zero_model_steps=tuple(request.plan.get("zero_model_steps", [])),
            generation_steps=tuple(request.plan.get("generation_steps", [])),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid direct-execute plan: {exc}")

    render_plan = plan_direct_execute_render(blueprint, gate)
    return DirectExecuteRenderResponse(
        success=True,
        feasible=render_plan.feasible,
        timeline=render_plan.timeline.model_dump(),
        needs_placeholder_video=render_plan.needs_placeholder_video,
        subtitle_cue_count=render_plan.subtitle_cue_count,
        rejected=list(render_plan.rejected),
    )


# ---------------------------------------------------------------------------
# .adreplica 文档层（蓝图 ↔ 标记文本，hypit "文件即真相源"）
# ---------------------------------------------------------------------------


@router.post("/blueprint/export", response_model=AdReplicaExportResponse)
async def export_blueprint_adreplica(
    request: AdReplicaExportRequest,
) -> AdReplicaExportResponse:
    """复刻蓝图 → ``.adreplica`` 标记文本（词汇表见 services/replica/adreplica.py）。

    纯转换：不调 LLM、不落库。文本是人与 Agent 都可编辑的真相源形态；
    改完后经 ``/blueprint/import`` 重编译回蓝图再写回 replica 节点
    （画布节点 patch API），即 hypit 的"编辑必回写"闭环。
    """
    from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2

    try:
        blueprint = ReplicaBlueprintContentV2.model_validate(request.blueprint)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid replica blueprint content: {exc}",
        )
    return AdReplicaExportResponse(
        success=True,
        adreplica=adreplica_from_blueprint(blueprint),
        filename=adreplica_filename(blueprint),
    )


@router.post("/blueprint/import", response_model=BlueprintResponse)
async def import_blueprint_adreplica(request: AdReplicaImportRequest) -> BlueprintResponse:
    """``.adreplica`` 标记文本 → 复刻蓝图（含 normalize 兜底，结构性错误 422）。

    响应与 ``/blueprint`` 同形，可无缝衔接既有前端流：返回的 blueprint
    可直接 patch 回 replica 节点，replica_script 可直接进 script 节点。
    """
    try:
        blueprint = blueprint_from_adreplica(request.adreplica)
    except AdReplicaParseError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": str(exc), "error_type": "adreplica_parse"},
        )
    return BlueprintResponse(
        success=True,
        blueprint=blueprint.model_dump(mode="json"),
        replica_script=render_replica_script(blueprint),
    )


def _canvas_node_service() -> tuple[AgentCanvasNodeService, Any]:
    """Construct the canvas node service against the v2 database.

    Same construction pattern as the Agent Canvas runtime (per-request
    database from settings.media_data_dir); no model-policy bootstrap is
    needed because replica instantiation only creates a script node with
    ``model_selection_mode="default"``.
    """
    from app.core.config import get_settings
    from app.persistence.agent_canvas_repository import (
        AgentCanvasWorkflowRepository,
    )
    from app.persistence.database import create_v2_database
    from app.persistence.event_repository import EventRepository
    from app.persistence.project_repository import ProjectRepository

    settings = get_settings()
    database = create_v2_database(settings.media_data_dir)
    project_repository = ProjectRepository(database)
    event_repository = EventRepository(database)
    workflow_repository = AgentCanvasWorkflowRepository(
        database, project_repository, event_repository
    )
    return AgentCanvasNodeService(workflow_repository), workflow_repository


@router.post("/instantiate", response_model=InstantiateResponse)
async def instantiate_blueprint(request: InstantiateRequest) -> InstantiateResponse:
    """把 replica 节点的蓝图实例化为 script 节点（执行仍走既有工作流引擎）。

    - 节点类型/角色契约经 AdMediaRoleRegistry 校验（replica_blueprint）；
    - 创建经 AgentCanvasNodeService.create（既有画布生命周期，expected_revision
      防并发覆盖）；
    - slot_updates 可选：先应用到蓝图再渲染脚本（不写回 replica 节点——
      持久化由画布节点 patch 端点负责，避免双写）。
    """
    from app.persistence.errors import V2PersistenceError

    node_service, workflow_repository = _canvas_node_service()

    try:
        workflow = workflow_repository.get_workflow(request.workflow_id)
        node = workflow_repository.get_node(request.workflow_id, request.replica_node_id)
    except V2PersistenceError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": str(exc), "code": getattr(exc, "code", "not_found")},
        )
    if node.node_type != "replica":
        raise HTTPException(
            status_code=400,
            detail=f"Node {request.replica_node_id} is {node.node_type}, not a replica blueprint",
        )

    from app.schemas.agent_canvas_ad_media import ReplicaBlueprintContentV2
    from app.services.replica.blueprint import BLUEPRINT_VERSION

    try:
        blueprint = ReplicaBlueprintContentV2.model_validate(node.structured_content)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid replica blueprint content: {exc}",
        )
    if blueprint.blueprint_version != BLUEPRINT_VERSION:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported blueprint version: {blueprint.blueprint_version}",
        )
    if request.slot_updates:
        blueprint = apply_slot_updates(blueprint, request.slot_updates)

    position = node.position
    plan = plan_script_instantiation(
        blueprint,
        replica_node_id=request.replica_node_id,
        position={"x": float(position.x), "y": float(position.y) + 260.0},
    )

    try:
        create_request = CanvasNodeCreateRequestV2(**plan.node_request)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid node request: {exc}")

    try:
        created = node_service.create(
            request.workflow_id,
            create_request,
            expected_revision=workflow.revision,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Failed to instantiate blueprint: {str(exc)[:200]}",
        )

    from datetime import datetime, timezone
    from uuid import uuid4

    from app.schemas.agent_canvas import (
        CanvasBindingSourceNodeV2,
        CanvasBindingV2,
        CanvasNodePatchRequestV2,
    )

    # 1) 自动创建 replica→script 绑定（蓝图作为 script 的 text_context 输入）
    now = datetime.now(timezone.utc)
    binding = CanvasBindingV2(
        binding_id=f"binding_{uuid4().hex}",
        workflow_id=request.workflow_id,
        source=CanvasBindingSourceNodeV2(source_node_id=request.replica_node_id),
        target_node_id=created.node_id,
        input_role="text_context",
        enabled=True,
        order=0,
        label=plan.binding.get("label") or "复刻蓝图",
        metadata={"origin": "replica_instantiate"},
        created_at=now,
        updated_at=now,
    )
    try:
        fresh_workflow = workflow_repository.get_workflow(request.workflow_id)
        workflow_repository.add_binding(
            binding, expected_revision=fresh_workflow.revision
        )
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Failed to bind blueprint to script node: {str(exc)[:200]}",
        )

    # 2) 实例化指针写回：instantiated_script_node_id 是蓝图节点的运行时状态，
    #    与槽位/锚点一起进单一真相源（避免双实例化时指针漂移）。
    try:
        fresh_workflow = workflow_repository.get_workflow(request.workflow_id)
        pointer_blueprint = blueprint.model_copy(
            update={"instantiated_script_node_id": created.node_id}
        )
        node_service.patch(
            request.workflow_id,
            request.replica_node_id,
            CanvasNodePatchRequestV2(
                structured_content=pointer_blueprint.model_dump(mode="json")
            ),
            expected_revision=fresh_workflow.revision,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Failed to write back instantiation pointer: {str(exc)[:200]}",
        )

    return InstantiateResponse(
        success=True,
        script_node_id=created.node_id,
        script_text=plan.script_text,
        workflow_revision=workflow.revision + 1,
        binding_id=binding.binding_id,
    )
