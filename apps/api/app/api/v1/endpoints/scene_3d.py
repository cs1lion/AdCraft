"""SceneScript 3D previs rendering API endpoints.

Provides HTTP endpoints for rendering SceneScript animations via Blender,
extracting keyframes, and querying renderer capability.

Endpoints:
- GET  /scene-3d/capability  — Query Blender renderer availability
- POST /scene-3d/render      — Render a SceneScript to video + keyframes
- POST /scene-3d/keyframes   — Extract 5 keyframes per shot from rendered frames
- POST /scene-3d/prompt      — Generate video-model prompts from a SceneScript
- POST /scene-3d/template    — Generate a SceneScript from a shot template
- POST /scene-3d/adapt-aspect — Adapt a SceneScript for a target aspect ratio
- POST /scene-3d/transition-proposals — Propose A→B 衔接方案 (advisory)
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.speech_orchestration import SpeechSegment
from app.services.scene3d.transition_proposals import (
    audit_declared_intent,
    propose_transitions,
)
from app.services.scene3d.blender_renderer import (
    get_blender_capability,
    render_scene_script,
)
from app.services.scene3d.encoder import encode_png_sequence, mux_audio_to_video
from app.services.scene3d.keyframes import extract_keyframes, keyframe_manifest
from app.services.scene3d.prompt_builder import (
    build_video_prompt_bundle,
    determine_reference_mode,
)
from app.services.scene3d.reference_assets import (
    build_video_model_input,
    format_reference_instructions,
)
from app.services.scene3d.shot_templates import (
    generate_from_template,
    list_templates,
)
from app.services.scene3d.render_job_manager import (
    get_render_job_manager,
)
from app.services.scene3d.aspect_ratios import (
    adapt_scene_script_for_aspect,
    list_aspect_ratios,
)
from app.services.scene3d.reference_upload import (
    UploadError,
    get_reference_video_path,
    list_reference_videos,
    save_reference_video,
)

router = APIRouter(prefix="/scene-3d", tags=["scene-3d"])


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class CapabilityResponse(BaseModel):
    state: str
    version: str | None = None
    executable: str | None = None
    error: str | None = None


class RenderRequest(BaseModel):
    scene_script: dict[str, Any] = Field(..., description="Validated SceneScript JSON")
    render_video: bool = Field(True, description="Whether to encode PNG frames to MP4")
    extract_keyframes: bool = Field(True, description="Whether to extract 5 keyframes per shot")
    quality: str = Field("preview", description="Render quality: preview | standard | high")
    blender_executable: str | None = Field(None, description="Override Blender executable path")
    timeout_seconds: int = Field(600, ge=30, le=3600)
    audio_path: str | None = Field(
        None,
        description=(
            "Dialogue bed to mux into the render (the V0.2 §14.9 animatic: "
            "480P picture + real voice). A missing file degrades to a silent "
            "render with a reported reason, never a failed render."
        ),
    )
    audio_asset_id: str | None = Field(
        None,
        description="Project asset whose content is the bed (resolved server-side)",
    )


class RenderResponse(BaseModel):
    success: bool
    job_id: str
    output_dir: str | None = None
    frame_count: int = 0
    video_path: str | None = None
    animatic_video_path: str | None = None
    audio_muxed: bool = False
    keyframes: list[dict[str, Any]] = []
    duration_seconds: float = 0.0
    blender_version: str | None = None
    warnings: list[str] = []
    error: str | None = None


class KeyframesRequest(BaseModel):
    scene_script: dict[str, Any]
    frames_dir: str = Field(..., description="Directory containing rendered frame_XXXX.png files")
    output_dir: str | None = None


class TransitionProposalsRequest(BaseModel):
    """Ask how shot A could lead into shot B.

    ``segments`` is optional: with the speech timeline the proposals can reason
    about pauses (the time-jump reading); without it they degrade honestly.
    ``polish_narratives`` asks the LLM to explain each reading for THIS pair
    (V0.2 §6.2/§15). The operations never change — only the prose does — and
    an unavailable LLM degrades to the rule narratives with a reported reason.
    """

    scene_script: dict[str, Any]
    shot_a_id: str = Field(..., description="The outgoing shot id")
    shot_b_id: str = Field(..., description="The incoming shot id")
    segments: list[dict[str, Any]] = Field(default_factory=list)
    transition_frames: int = Field(default=45, ge=1, le=600)
    polish_narratives: bool = Field(
        default=False,
        description="Ask the LLM to explain each reading (degradation is reported)",
    )
    propose_readings: bool = Field(
        default=False,
        description=(
            "Ask the LLM for readings beyond the rule catalogue; every proposed "
            "reading is validated against the operation vocabulary and the scene "
            "(unverifiable ones are dropped with a reason)"
        ),
    )
    exclude_reading_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Reading ids the author already engaged with (applied or dismissed). "
            "The multi-round memory (V0.2 §15): they are reserved, so the LLM "
            "is asked for something new rather than re-pitching them."
        ),
    )
    retained_reading_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Reading ids to PERSIST on the scene-3d node so they survive "
            "across sessions (V0.2 §14.5 known boundary: memory lives in "
            "panel state, reset on refresh). Written to the node's "
            "structured_content.retained_reading_ids alongside the request. "
            "Target the node via workflow_id + node_id."
        ),
    )
    workflow_id: str | None = Field(
        default=None,
        description=(
            "Workflow id of the scene-3d node receiving retained_reading_ids. "
            "Optional: empty means no persistence."
        ),
    )
    node_id: str | None = Field(
        default=None,
        description=(
            "Node id of the scene-3d node receiving retained_reading_ids. "
            "Required together with workflow_id for persistence."
        ),
    )


class TransitionProposalsResponse(BaseModel):
    success: bool
    proposals: list[dict[str, Any]] = []
    warnings: list[str] = []
    narrative_source: str = "rules"
    #: Whether the shot's DECLARED entry reading still holds for this pair
    #: (V0.2 §13 第 5 问). A declaration that outlives the timeline it was
    #: made against is a lie, and nothing else would ever notice it.
    intent_audit: dict[str, Any] = {}


class KeyframesResponse(BaseModel):
    success: bool
    keyframes: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {}
    error: str | None = None


class PromptRequest(BaseModel):
    scene_script: dict[str, Any]
    model_supports_reference_video: bool = False
    model_supports_reference_images: bool = True


class PromptResponse(BaseModel):
    success: bool
    reference_mode: str
    global_prompt: str
    global_negative_prompt: str
    shots: list[dict[str, Any]] = []
    reference_instructions: str | None = None
    error: str | None = None


class TemplateGenerateRequest(BaseModel):
    template_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class TemplateResponse(BaseModel):
    success: bool
    scene_script: dict[str, Any] | None = None
    error: str | None = None


class TemplateListResponse(BaseModel):
    templates: list[dict[str, Any]]


class AspectAdaptRequest(BaseModel):
    scene_script: dict[str, Any]
    target_ratio: str = Field(..., description="Target aspect ratio ID, e.g. '9:16', '1:1'")


class AspectAdaptResponse(BaseModel):
    success: bool
    scene_script: dict[str, Any] | None = None
    render_settings: dict[str, Any] = {}
    error: str | None = None


class AspectListResponse(BaseModel):
    ratios: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _validate_scene_script(data: dict[str, Any]) -> SceneScriptRoot:
    """Validate and parse a SceneScript dict, raising HTTPException on failure."""
    try:
        return SceneScriptRoot.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid SceneScript: {exc}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/capability", response_model=CapabilityResponse)
async def get_capability() -> CapabilityResponse:
    """Query Blender renderer availability and version."""
    cap = get_blender_capability()
    return CapabilityResponse(
        state=cap.state,
        version=cap.version,
        executable=cap.executable,
        error=cap.error,
    )


@router.post("/render", response_model=RenderResponse)
async def render_scene(request: RenderRequest) -> RenderResponse:
    """Render a SceneScript to video frames, optionally encode to MP4 and
    extract 5 keyframes per shot.

    This is a synchronous endpoint suitable for short scenes (<= 30 seconds).
    For longer scenes, consider using the async job endpoint (future).
    """
    job_id = str(uuid.uuid4())[:8]

    # Validate SceneScript before doing any blocking work.
    try:
        scene_script = _validate_scene_script(request.scene_script)
    except HTTPException:
        raise

    # The animatic bed (V0.2 §14.9): resolved here so a missing file is a
    # reported degradation, not a failed render — the previs itself is the
    # deliverable; the sound is the审片面 that makes it watchable.
    audio_path, audio_warning = _resolve_render_audio(
        request.audio_path, request.audio_asset_id
    )

    # Run the entire blocking render pipeline in a worker thread so that a
    # long-running Blender subprocess does not stall the API event loop.
    result = await asyncio.to_thread(
        _run_render_pipeline,
        scene_script=scene_script,
        render_video=request.render_video,
        do_extract_keyframes=request.extract_keyframes,
        blender_executable=request.blender_executable,
        timeout_seconds=request.timeout_seconds,
        job_id=job_id,
        audio_path=audio_path,
    )
    warnings = list(audio_warning)
    warnings.extend(result.pop("warnings", []) or [])
    return RenderResponse(job_id=job_id, warnings=warnings, **result)


def _run_render_pipeline(
    scene_script: SceneScriptRoot,
    render_video: bool,
    do_extract_keyframes: bool,
    blender_executable: str | None,
    timeout_seconds: int,
    job_id: str,
    audio_path: str | None = None,
) -> dict[str, Any]:
    """Execute the blocking Blender render + encode + keyframe pipeline."""

    # Check capability first
    cap = get_blender_capability(blender_executable)
    if cap.state == "unsupported":
        return {
            "success": False,
            "output_dir": None,
            "frame_count": 0,
            "video_path": None,
            "animatic_video_path": None,
            "audio_muxed": False,
            "keyframes": [],
            "duration_seconds": 0.0,
            "blender_version": None,
            "error": f"Blender not available: {cap.error}",
        }

    # Create output directory
    output_dir = os.path.join(tempfile.gettempdir(), f"scene3d_{job_id}")
    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    # Render PNG frames
    render_result = render_scene_script(
        scene_script,
        frames_dir,
        executable=blender_executable,
        timeout_seconds=timeout_seconds,
    )

    if not render_result.success or render_result.frame_count == 0:
        return {
            "success": False,
            "output_dir": output_dir,
            "frame_count": render_result.frame_count,
            "video_path": None,
            "animatic_video_path": None,
            "audio_muxed": False,
            "keyframes": [],
            "duration_seconds": render_result.duration_seconds,
            "blender_version": render_result.blender_version,
            "error": render_result.error or "Render produced no frames",
        }

    video_path = None
    animatic_video_path = None
    audio_muxed = False
    warnings: list[str] = []
    if render_video:
        video_path = os.path.join(output_dir, "previs.mp4")
        encode_result = encode_png_sequence(
            frames_dir,
            video_path,
            fps=scene_script.scene.frame_rate,
        )
        if not encode_result.success:
            video_path = None  # Don't fail the whole render if encoding fails
        elif audio_path:
            animatic_video_path = os.path.join(output_dir, "previs_animatic.mp4")
            mux_result = mux_audio_to_video(video_path, audio_path, animatic_video_path)
            if getattr(mux_result, "success", False):
                audio_muxed = True
            else:
                # The previs ships; the sound does not. Reported, not silent.
                animatic_video_path = None
                warnings.append(
                    f"音频床混入失败，已输出无声预演：{getattr(mux_result, 'error', 'unknown')}"
                )

    keyframes_result = []
    if do_extract_keyframes:
        keyframes_dir = os.path.join(output_dir, "keyframes")
        shot_keyframes = extract_keyframes(scene_script, frames_dir, keyframes_dir)
        for skf in shot_keyframes:
            keyframes_result.append(
                {
                    "shot_id": skf.shot_id,
                    "frames": skf.frames,
                    "files": skf.files,
                }
            )

    return {
        "success": True,
        "output_dir": output_dir,
        "frame_count": render_result.frame_count,
        "video_path": video_path,
        "animatic_video_path": animatic_video_path,
        "audio_muxed": audio_muxed,
        "keyframes": keyframes_result,
        "duration_seconds": render_result.duration_seconds,
        "blender_version": render_result.blender_version,
        "warnings": warnings,
        "error": None,
    }


@router.post("/keyframes", response_model=KeyframesResponse)
async def extract_shot_keyframes(request: KeyframesRequest) -> KeyframesResponse:
    """Extract 5 keyframes per shot from already-rendered PNG frames."""
    try:
        scene_script = _validate_scene_script(request.scene_script)
    except HTTPException:
        raise

    if not os.path.isdir(request.frames_dir):
        raise HTTPException(status_code=404, detail=f"Frames directory not found: {request.frames_dir}")

    output_dir = request.output_dir or os.path.join(request.frames_dir, "keyframes")
    shot_keyframes = extract_keyframes(scene_script, request.frames_dir, output_dir)
    manifest = keyframe_manifest(scene_script)

    return KeyframesResponse(
        success=True,
        keyframes=[{"shot_id": skf.shot_id, "frames": skf.frames, "files": skf.files} for skf in shot_keyframes],
        manifest=manifest,
    )


@router.post("/prompt", response_model=PromptResponse)
async def generate_prompts(request: PromptRequest) -> PromptResponse:
    """Generate video-model prompts and reference asset guidance from a SceneScript."""
    try:
        scene_script = _validate_scene_script(request.scene_script)
    except HTTPException:
        raise

    reference_mode = determine_reference_mode(
        request.model_supports_reference_video,
        request.model_supports_reference_images,
    )

    bundle = build_video_prompt_bundle(scene_script, reference_mode)

    # Build reference instructions (without actual rendered assets)
    model_input = build_video_model_input(
        scene_script,
        model_supports_reference_video=request.model_supports_reference_video,
        model_supports_reference_images=request.model_supports_reference_images,
    )
    instructions = format_reference_instructions(model_input)

    return PromptResponse(
        success=True,
        reference_mode=reference_mode,
        global_prompt=bundle.global_prompt,
        global_negative_prompt=bundle.global_negative_prompt,
        shots=[{
            "shot_id": s.shot_id,
            "camera": s.camera_id,
            "duration_seconds": s.duration_seconds,
            "prompt": s.prompt,
            "negative_prompt": s.negative_prompt,
            "camera_description": s.camera_description,
            "characters": s.characters_in_shot,
        } for s in bundle.shots],
        reference_instructions=instructions,
    )


@router.get("/templates", response_model=TemplateListResponse)
async def list_shot_templates(category: str | None = None) -> TemplateListResponse:
    """List available shot templates, optionally filtered by category."""
    templates = list_templates(category)
    return TemplateListResponse(
        templates=[{
            "template_id": t.template_id,
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "min_characters": t.min_characters,
            "max_characters": t.max_characters,
            "default_duration": t.default_duration,
            "tags": t.tags,
        } for t in templates],
    )


@router.post("/template", response_model=TemplateResponse)
async def generate_from_template_endpoint(request: TemplateGenerateRequest) -> TemplateResponse:
    """Generate a SceneScript from a named shot template."""
    try:
        scene_script = generate_from_template(request.template_id, **request.params)
        return TemplateResponse(
            success=True,
            scene_script=scene_script.model_dump(mode="json"),
        )
    except ValueError as exc:
        return TemplateResponse(success=False, error=str(exc))
    except Exception as exc:
        return TemplateResponse(success=False, error=f"Template generation failed: {exc}")


@router.get("/aspect-ratios", response_model=AspectListResponse)
async def list_aspect_ratio_options() -> AspectListResponse:
    """List available aspect ratios for video output."""
    ratios = list_aspect_ratios()
    return AspectListResponse(
        ratios=[{
            "ratio_id": r.ratio_id,
            "name": r.name,
            "width": r.width,
            "height": r.height,
            "ratio": r.ratio,
            "orientation": r.orientation,
            "common_uses": r.common_uses,
        } for r in ratios],
    )


@router.post("/adapt-aspect", response_model=AspectAdaptResponse)
async def adapt_for_aspect_ratio(request: AspectAdaptRequest) -> AspectAdaptResponse:
    """Adapt a SceneScript for a target aspect ratio (adjusts camera positions
    and provides render resolution settings)."""
    try:
        scene_script = _validate_scene_script(request.scene_script)
    except HTTPException:
        raise

    try:
        adapted, render_settings = adapt_scene_script_for_aspect(scene_script, request.target_ratio)
        return AspectAdaptResponse(
            success=True,
            scene_script=adapted.model_dump(mode="json"),
            render_settings=render_settings,
        )
    except ValueError as exc:
        return AspectAdaptResponse(success=False, error=str(exc))


# ---------------------------------------------------------------------------
# Async render job endpoints
# ---------------------------------------------------------------------------


class AsyncRenderRequest(BaseModel):
    scene_script: dict[str, Any] = Field(..., description="Validated SceneScript JSON")
    render_video: bool = True
    extract_keyframes: bool = True
    blender_executable: str | None = None
    timeout_seconds: int = Field(600, ge=30, le=3600)
    output_dir: str | None = None
    audio_path: str | None = Field(
        None,
        description="Dialogue bed to mux into the render (the animatic, V0.2 §14.9)",
    )
    audio_asset_id: str | None = Field(
        None,
        description="Project asset whose content is the bed (resolved server-side)",
    )


class AsyncRenderResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: float = 0.0
    created_at: float | None = None
    started_at: float | None = None
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class JobListResponse(BaseModel):
    jobs: list[dict[str, Any]]
    total: int


@router.post("/render/async", response_model=AsyncRenderResponse)
async def submit_async_render(request: AsyncRenderRequest) -> AsyncRenderResponse:
    """Submit an asynchronous render job. Returns immediately with a job ID;
    poll GET /scene-3d/render/{job_id} for status."""
    # The animatic bed resolves here (same rule as the sync endpoint): a
    # missing file degrades with a warning, it does not fail the submission.
    audio_path, audio_warning = _resolve_render_audio(
        request.audio_path, request.audio_asset_id
    )
    manager = get_render_job_manager()
    job_id = manager.submit(
        scene_script=request.scene_script,
        render_video=request.render_video,
        extract_keyframes_flag=request.extract_keyframes,
        blender_executable=request.blender_executable,
        timeout_seconds=request.timeout_seconds,
        output_dir=request.output_dir,
        audio_path=audio_path,
        audio_warning=audio_warning,
    )
    return AsyncRenderResponse(
        job_id=job_id,
        status="pending",
        message="Render job submitted. Poll GET /scene-3d/render/{job_id} for status.",
    )


@router.get("/render/jobs", response_model=JobListResponse)
async def list_render_jobs(status: str | None = None) -> JobListResponse:
    """List all render jobs, optionally filtered by status.

    Must stay declared before ``/render/{job_id}``: FastAPI matches routes in
    declaration order, so a later declaration would be shadowed and resolve as
    ``job_id="jobs"``.
    """
    manager = get_render_job_manager()
    jobs = manager.list_jobs(status=status)
    return JobListResponse(
        jobs=[{
            "job_id": j.job_id,
            "status": j.status,
            "progress": j.progress,
            "created_at": j.created_at,
            "started_at": j.started_at,
            "completed_at": j.completed_at,
            "error": j.error,
        } for j in jobs],
        total=len(jobs),
    )


@router.get("/render/{job_id}", response_model=JobStatusResponse)
async def get_render_job_status(job_id: str) -> JobStatusResponse:
    """Get the status of an asynchronous render job."""
    manager = get_render_job_manager()
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    result_dict = None
    if job.result:
        result_dict = {
            "output_dir": job.result.output_dir,
            "frame_count": job.result.frame_count,
            "video_path": job.result.video_path,
            "animatic_video_path": job.result.animatic_video_path,
            "audio_muxed": job.result.audio_muxed,
            "keyframes": job.result.keyframes,
            "duration_seconds": job.result.duration_seconds,
            "blender_version": job.result.blender_version,
            "warnings": job.result.warnings,
        }

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        result=result_dict,
        error=job.error,
    )


@router.post("/render/{job_id}/cancel")
async def cancel_render_job(job_id: str) -> dict[str, Any]:
    """Cancel a pending or running render job."""
    manager = get_render_job_manager()
    success = manager.cancel(job_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Job not found or not cancellable: {job_id}",
        )
    return {"job_id": job_id, "status": "cancelled", "message": "Cancellation requested."}

# ---------------------------------------------------------------------------
# Reference video upload endpoints
# ---------------------------------------------------------------------------


class ReferenceVideoMetadata(BaseModel):
    duration_seconds: float
    width: int
    height: int
    frame_rate: float
    frame_count: int
    codec_name: str
    file_size_bytes: int


class ReferenceUploadResponse(BaseModel):
    success: bool
    asset_id: str
    file_path: str
    file_name: str
    file_size_bytes: int
    metadata: ReferenceVideoMetadata
    keyframes_dir: str | None = None
    keyframe_count: int = 0


class ReferenceVideoInfo(BaseModel):
    asset_id: str
    file_name: str
    file_size_bytes: int
    upload_time: float


class ReferenceListResponse(BaseModel):
    success: bool
    videos: list[ReferenceVideoInfo]


@router.post("/upload-reference", response_model=ReferenceUploadResponse)
async def upload_reference_video(
    file: UploadFile = File(...),
    extract_keyframes: bool = True,
    num_keyframes: int = 5,
) -> ReferenceUploadResponse:
    """Upload a reference video for video model conditioning.

    Validates format (MP4/WebM/MOV), size (<=100MB), duration (<=60s),
    and extracts metadata. Optionally extracts evenly-spaced keyframes.
    """
    try:
        file_bytes = await file.read()
        result = save_reference_video(
            file_bytes=file_bytes,
            file_name=file.filename or "reference.mp4",
            content_type=file.content_type,
            extract_keyframes=extract_keyframes,
            num_keyframes=num_keyframes,
        )
        return ReferenceUploadResponse(
            success=True,
            asset_id=result.asset_id,
            file_path=result.file_path,
            file_name=result.file_name,
            file_size_bytes=result.file_size_bytes,
            metadata=ReferenceVideoMetadata(
                duration_seconds=result.metadata.duration_seconds,
                width=result.metadata.width,
                height=result.metadata.height,
                frame_rate=result.metadata.frame_rate,
                frame_count=result.metadata.frame_count,
                codec_name=result.metadata.codec_name,
                file_size_bytes=result.metadata.file_size_bytes,
            ),
            keyframes_dir=result.keyframes_dir,
            keyframe_count=result.keyframe_count,
        )
    except UploadError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": str(e), "error_type": e.error_type},
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Upload failed: {str(e)[:200]}",
        )


@router.get("/reference-videos", response_model=ReferenceListResponse)
async def list_uploaded_reference_videos() -> ReferenceListResponse:
    """List all uploaded reference videos."""
    videos = list_reference_videos()
    return ReferenceListResponse(
        success=True,
        videos=[
            ReferenceVideoInfo(
                asset_id=v["asset_id"],
                file_name=v["file_name"],
                file_size_bytes=v["file_size_bytes"],
                upload_time=v["upload_time"],
            )
            for v in videos
        ],
    )


@router.get("/reference-videos/{asset_id}")
async def get_reference_video_info(asset_id: str) -> dict:
    """Get metadata for a specific uploaded reference video."""
    file_path = get_reference_video_path(asset_id)
    if not file_path:
        raise HTTPException(
            status_code=404,
            detail=f"Reference video not found: {asset_id}",
        )
    from app.services.scene3d.reference_upload import extract_metadata
    try:
        metadata = extract_metadata(file_path)
        return {
            "success": True,
            "asset_id": asset_id,
            "file_path": str(file_path),
            "metadata": {
                "duration_seconds": metadata.duration_seconds,
                "width": metadata.width,
                "height": metadata.height,
                "frame_rate": metadata.frame_rate,
                "frame_count": metadata.frame_count,
                "codec_name": metadata.codec_name,
                "file_size_bytes": metadata.file_size_bytes,
            },
        }
    except UploadError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": str(e), "error_type": e.error_type},
        )

# ---------------------------------------------------------------------------
# Depth estimation (white model extraction) endpoints
# ---------------------------------------------------------------------------


class DepthEstimationRequest(BaseModel):
    input_video_path: str = Field(..., description="Path to input video file")
    model_type: str = Field(default="DPT_Hybrid", description="MiDaS model type")
    colormap: str = Field(default="grayscale", description="Depth colormap")
    output_width: int = Field(default=960, description="Output video width")
    output_height: int = Field(default=540, description="Output video height")
    extract_keyframes: bool = Field(default=True, description="Extract keyframes from output")
    num_keyframes: int = Field(default=5, description="Number of keyframes to extract")
    max_frames: int | None = Field(default=None, description="Max frames to process")


class DepthEstimationResponse(BaseModel):
    success: bool
    asset_id: str
    input_video_path: str
    output_video_path: str
    output_width: int
    output_height: int
    frame_count: int
    duration_seconds: float
    fps: float
    model_type: str
    colormap: str
    keyframes_dir: str | None = None
    keyframe_count: int = 0
    processing_time_seconds: float = 0.0


class DepthDependenciesResponse(BaseModel):
    success: bool
    torch: bool
    opencv: bool
    numpy: bool
    timm: bool
    ffmpeg: bool
    all_available: bool
    available_models: list[str]
    available_colormaps: list[str]


@router.post("/extract-depth", response_model=DepthEstimationResponse)
async def extract_depth_map(request: DepthEstimationRequest) -> DepthEstimationResponse:
    """Extract depth map (white model) from a video using MiDaS.

    Converts an uploaded video into a depth-map visualization that can be
    used as a 3D previs reference. Closer objects are brighter, farther
    objects are darker.
    """
    from app.services.scene3d.depth_estimator import (
        DepthEstimationError,
        extract_depth_from_video,
    )

    try:
        # MiDaS inference is CPU/GPU-bound and can run for minutes: offload to
        # a worker thread so the API event loop stays responsive (same pattern
        # as the /render endpoint).
        result = await asyncio.to_thread(
            extract_depth_from_video,
            input_video_path=request.input_video_path,
            model_type=request.model_type,
            colormap=request.colormap,
            output_width=request.output_width,
            output_height=request.output_height,
            extract_keyframes=request.extract_keyframes,
            num_keyframes=request.num_keyframes,
            max_frames=request.max_frames,
        )
        return DepthEstimationResponse(
            success=True,
            asset_id=result.asset_id,
            input_video_path=result.input_video_path,
            output_video_path=result.output_video_path,
            output_width=result.output_width,
            output_height=result.output_height,
            frame_count=result.frame_count,
            duration_seconds=result.duration_seconds,
            fps=result.fps,
            model_type=result.model_type,
            colormap=result.colormap,
            keyframes_dir=result.keyframes_dir,
            keyframe_count=result.keyframe_count,
            processing_time_seconds=result.processing_time_seconds,
        )
    except DepthEstimationError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": str(e), "error_type": e.error_type},
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Depth estimation failed: {str(e)[:200]}",
        )


@router.get("/depth-dependencies", response_model=DepthDependenciesResponse)
async def check_depth_dependencies() -> DepthDependenciesResponse:
    """Check if depth estimation dependencies are installed."""
    from app.services.scene3d.depth_estimator import (
        check_dependencies,
        get_available_colormaps,
        get_available_models,
    )

    deps = check_dependencies()
    all_available = all([deps["torch"], deps["opencv"], deps["numpy"], deps["ffmpeg"]])

    return DepthDependenciesResponse(
        success=True,
        torch=deps["torch"],
        opencv=deps["opencv"],
        numpy=deps["numpy"],
        timm=deps["timm"],
        ffmpeg=deps["ffmpeg"],
        all_available=all_available,
        available_models=get_available_models(),
        available_colormaps=get_available_colormaps(),
    )


# ---------------------------------------------------------------------------
# Reference video analysis (multimodal LLM -> SceneScript)
# ---------------------------------------------------------------------------


class AnalyzeReferenceResponse(BaseModel):
    success: bool
    scene_script: dict[str, Any]
    summary: dict[str, Any]
    frame_analyses: list[dict[str, Any]]
    video_metadata: dict[str, Any]
    num_frames_analyzed: int
    user_description: str | None = None


@router.post("/analyze-reference", response_model=AnalyzeReferenceResponse)
async def analyze_reference_video_endpoint(
    file: UploadFile = File(...),
    user_description: str | None = None,
    num_frames: int = 6,
) -> AnalyzeReferenceResponse:
    """Analyze an uploaded reference video and generate a SceneScript.

    Uses a multimodal LLM to analyze extracted keyframes (scene, characters,
    actions, camera, props), then synthesizes a valid SceneScript JSON that
    can be rendered by the Blender previs pipeline.

    This is the "upload reference video -> 3D previs" path:
      user video -> extract frames -> multimodal LLM analysis -> SceneScript -> Blender render

    Args:
        file: Uploaded video file (MP4/WebM/MOV, <=100MB, <=10s).
        user_description: Optional user-provided description to guide analysis.
        num_frames: Number of evenly-spaced frames to analyze (default 6).

    Returns:
        AnalyzeReferenceResponse with SceneScript, analysis summary, and frame details.
    """
    import tempfile
    from pathlib import Path
    from app.services.scene3d.reference_video_analyzer import (
        AnalysisError,
        analyze_reference_video,
    )

    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        # Save to temp file for analysis
        suffix = Path(file.filename or "reference.mp4").suffix.lower()
        if suffix not in {".mp4", ".webm", ".mov", ".m4v"}:
            suffix = ".mp4"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            # Run analysis in thread pool (LLM calls are blocking)
            result = await asyncio.to_thread(
                analyze_reference_video,
                video_path=tmp_path,
                num_frames=num_frames,
                user_description=user_description,
            )
        finally:
            # Clean up temp file
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

        # Build response
        frame_analyses_dicts = []
        for fa in result.frame_analyses:
            frame_analyses_dicts.append({
                "frame_index": fa.frame_index,
                "timestamp_seconds": fa.timestamp_seconds,
                "scene_type": fa.scene_type,
                "environment_description": fa.environment_description,
                "lighting": fa.lighting,
                "camera_angle": fa.camera_angle,
                "shot_size": fa.shot_size,
                "camera_motion_hint": fa.camera_motion_hint,
                "characters": [
                    {
                        "description": c.description,
                        "position_hint": c.position_hint,
                        "action": c.action,
                        "facing": c.facing,
                    }
                    for c in fa.characters
                ],
                "props": fa.props,
                "notable_elements": fa.notable_elements,
            })

        return AnalyzeReferenceResponse(
            success=True,
            scene_script=result.scene_script_dict,
            summary={
                "scene_overview": result.summary.scene_overview,
                "characters_summary": result.summary.characters_summary,
                "camera_movement_summary": result.summary.camera_movement_summary,
                "action_timeline": result.summary.action_timeline,
                "inferred_duration_seconds": result.summary.inferred_duration_seconds,
            },
            frame_analyses=frame_analyses_dicts,
            video_metadata={
                "duration_seconds": result.video_metadata.duration_seconds,
                "width": result.video_metadata.width,
                "height": result.video_metadata.height,
                "frame_rate": result.video_metadata.frame_rate,
                "frame_count": result.video_metadata.frame_count,
                "codec_name": result.video_metadata.codec_name,
                "file_size_bytes": result.video_metadata.file_size_bytes,
            },
            num_frames_analyzed=result.num_frames_analyzed,
            user_description=result.user_description,
        )

    except AnalysisError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": str(e), "error_type": e.error_type},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Reference video analysis failed: {str(e)[:200]}",
        )


# ---------------------------------------------------------------------------
# Reference image analysis (multimodal LLM -> SceneScript)
# ---------------------------------------------------------------------------


class AnalyzeImageResponse(BaseModel):
    success: bool
    scene_script: dict[str, Any] | None = None
    summary: dict[str, Any] = {}
    image_analyses: list[dict[str, Any]] = []
    image_count: int = 0
    analyzed_image_count: int = 0
    panorama_image_indices: list[int] = []
    warnings: list[str] = []
    error: str | None = None


@router.post("/analyze-image", response_model=AnalyzeImageResponse)
async def analyze_reference_images_endpoint(
    files: list[UploadFile] = File(..., description="1-6 images of the same scene"),
    user_description: str | None = None,
    scene_name: str | None = None,
    duration_seconds: float | None = None,
    panorama: bool | None = None,
) -> AnalyzeImageResponse:
    """Analyze uploaded reference images and generate a SceneScript blockout.

    This is the "drop an image in, get an editable 3D blockout" path:
    user image(s) -> multimodal LLM analysis -> SceneScript -> 3D workbench.

    Equirectangular panoramas (~2:1 aspect) are detected automatically and
    sliced into 6 cubic faces before analysis so the LLM reads undistorted
    perspective views; ``panorama=false`` forces whole-image analysis and
    ``panorama=true`` is a hint that degrades with a warning when the image
    does not look equirectangular.

    Args:
        files: 1-6 images (PNG/JPEG/WebP/BMP, <=20MB each) of the same scene.
        user_description: Optional user description to guide analysis.
        scene_name: Optional name for the generated scene.
        duration_seconds: Target scene duration (default 6s, max 600s).
        panorama: Force panorama slicing on/off (default: auto-detect).

    Returns:
        AnalyzeImageResponse with SceneScript, per-image analyses, and warnings.
    """
    from app.services.scene3d.image_analyzer import (
        DEFAULT_DURATION_SECONDS,
        AnalysisError,
        analyze_images,
    )

    try:
        if not files:
            raise HTTPException(status_code=400, detail="No images uploaded")

        # Save uploads to temp files for analysis (ASCII-only paths: ffmpeg and
        # downstream tooling reject non-ASCII paths).
        import tempfile
        from pathlib import Path

        tmp_paths: list[str] = []
        for upload in files:
            file_bytes = await upload.read()
            if not file_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Uploaded image is empty: {upload.filename or 'unnamed'}",
                )
            suffix = Path(upload.filename or "image.png").suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                suffix = ".png"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_paths.append(tmp.name)

        try:
            # Run analysis in thread pool (LLM calls are blocking)
            result = await asyncio.to_thread(
                analyze_images,
                image_paths=tmp_paths,
                user_description=user_description,
                scene_name=scene_name,
                duration_seconds=(
                    duration_seconds
                    if duration_seconds is not None
                    else DEFAULT_DURATION_SECONDS
                ),
                panorama=panorama,
            )
        finally:
            # Clean up temp files (analyzed face files live in their own dir)
            for tmp_path in tmp_paths:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

        image_analyses_dicts = []
        for fa in result.image_analyses:
            image_analyses_dicts.append({
                "image_index": fa.frame_index,
                "scene_type": fa.scene_type,
                "environment_description": fa.environment_description,
                "lighting": fa.lighting,
                "camera_angle": fa.camera_angle,
                "shot_size": fa.shot_size,
                "camera_motion_hint": fa.camera_motion_hint,
                "characters": [
                    {
                        "description": c.description,
                        "position_hint": c.position_hint,
                        "action": c.action,
                        "facing": c.facing,
                    }
                    for c in fa.characters
                ],
                "props": fa.props,
                "notable_elements": fa.notable_elements,
            })

        return AnalyzeImageResponse(
            success=True,
            scene_script=result.scene_script_dict,
            summary={
                "scene_overview": result.summary.scene_overview,
                "characters_summary": result.summary.characters_summary,
                "camera_movement_summary": result.summary.camera_movement_summary,
                "action_timeline": result.summary.action_timeline,
                "inferred_duration_seconds": result.summary.inferred_duration_seconds,
            },
            image_analyses=image_analyses_dicts,
            image_count=len(result.image_paths),
            analyzed_image_count=len(result.analyzed_image_paths),
            panorama_image_indices=result.panorama_image_indices,
            warnings=result.warnings,
        )

    except AnalysisError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": str(e), "error_type": e.error_type},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Reference image analysis failed: {str(e)[:200]}",
        )

# ---------------------------------------------------------------------------
# Dialogue-driven lip-sync (dialogue -> speech timeline -> SceneScript keyframes)
# ---------------------------------------------------------------------------


class DialogueLipSyncRequest(BaseModel):
    scene_script: dict[str, Any] = Field(..., description="Validated SceneScript JSON")
    dialogue_lines: list[dict[str, Any]] = Field(
        ...,
        description="[{character_id, text, start_time?, emotion?}]; start_time omitted = sequential",
    )
    syllables_per_second: float = Field(4.0, ge=1.0, le=12.0)
    apply_gestures: bool = Field(
        default=False,
        description="V3 dialogue-as-performance: translate the speech/emotion envelope into programmatic body gestures (arm raise / forward lean / head shake) layered on top of the lip-sync keyframes; the same SpeechSegment list is the single source of truth."
    )
    propose_advisories: bool = Field(
        default=False,
        description=(
            "Ask the LLM to propose remedies for the shot advisories "
            "(V0.2 §14.3/§14.5). Advisory only: every proposal references a "
            "shot and an advisory that exist, and an unavailable/unusable LLM "
            "degrades to the rule remedies with a reported reason."
        ),
    )


class DialogueLipSyncResponse(BaseModel):
    success: bool
    scene_script: dict[str, Any] | None = None
    summary: dict[str, Any] = {}
    error: str | None = None


@router.post("/dialogue-lipsync", response_model=DialogueLipSyncResponse)
async def apply_dialogue_lip_sync_endpoint(
    request: DialogueLipSyncRequest,
) -> DialogueLipSyncResponse:
    """Apply dialogue-driven lip-sync keyframes to a SceneScript.

    Chains the speech track (ADR 0003) into the 3D previs pipeline:
    measured/estimated speech durations -> speech timeline -> lip-sync
    keyframes merged into character keyframes (position/rotation inherited
    by forward-hold). Timeline overlaps/gaps are reported in the summary,
    never silently resolved.
    """
    from app.services.scene3d.dialogue_lipsync_service import (
        DialogueLipSyncError,
        apply_dialogue_lip_sync,
    )

    try:
        result = apply_dialogue_lip_sync(
            request.scene_script,
            request.dialogue_lines,
            syllables_per_second=request.syllables_per_second,
            apply_gestures=request.apply_gestures,
        )
        summary = result.summary
        # Optional LLM proposal layer for the shot advisories (V0.2
        # §14.3/§14.5 audit-table gap: the advisor was rule-only). Every
        # proposal references an advisory and a shot that EXIST in this
        # scene, and an unavailable/unusable LLM degrades to the rule
        # remedies with a reported reason — never silent (standard §4).
        # The call is sync httpx, so it runs off the event loop.
        if request.propose_advisories:
            import asyncio

            from app.schemas.scene_script import SceneScriptRoot
            from app.services.scene3d.advisory_narratives import (
                propose_advisory_narratives,
            )
            from app.services.scene3d.shot_advisor import ShotAdvisory
            from app.services.scene3d.speech_orchestration import SpeechSegment

            script = SceneScriptRoot.model_validate(request.scene_script)
            advisories = [
                ShotAdvisory(
                    code=entry.get("code", ""),
                    shot_id=entry.get("shot_id"),
                    message=entry.get("message", ""),
                    remedy=entry.get("remedy", ""),
                    severity=entry.get("severity", "warning"),
                    proposal_ids=tuple(entry.get("proposal_ids") or ()),
                )
                for entry in summary.get("shot_advisories", [])
            ]
            segments = [
                SpeechSegment(
                    segment_id=entry.get("segment_id", f"seg_{index}"),
                    character_id=entry.get("character_id", ""),
                    text=entry.get("text", ""),
                    start_time=float(entry.get("start_time") or 0.0),
                    end_time=float(entry.get("end_time") or 0.0),
                )
                for index, entry in enumerate(summary.get("segments", []))
            ]
            proposed = await asyncio.to_thread(
                propose_advisory_narratives,
                shots=list(script.shots),
                segments=segments,
                advisories=advisories,
            )
            summary = {
                **summary,
                "advisory_proposals": proposed.to_dict(),
            }
        return DialogueLipSyncResponse(
            success=True,
            scene_script=result.scene_script.model_dump(mode="json"),
            summary=summary,
        )
    except DialogueLipSyncError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": str(e), "error_code": e.code},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Dialogue lip-sync failed: {str(e)[:200]}",
        )

# ---------------------------------------------------------------------------
# Scene operations (white-model design mode: agent ops -> SceneScript)
# ---------------------------------------------------------------------------


class SceneOperationsRequest(BaseModel):
    scene_script: dict[str, Any] = Field(..., description="Validated SceneScript JSON")
    operations: list[dict[str, Any]] = Field(
        ...,
        description=(
            "Structured scene ops: add_environment/add_prop/add_character/add_camera/"
            "move_object/rotate_object/scale_object/set_camera/add_keyframe/remove_object/"
            "mcp_request. All-or-nothing: any invalid op rejects the batch."
        ),
    )
    use_mcp: bool = Field(
        False,
        description="Execute mcp_request ops against a Blender MCP server",
    )


class SceneOperationsResponse(BaseModel):
    success: bool
    scene_script: dict[str, Any] | None = None
    applied: list[dict[str, Any]] = []
    warnings: list[str] = []
    mcp_results: list[dict[str, Any]] = []
    error: str | None = None


class DirectorMotionCommandRequest(BaseModel):
    """The director command bar's intent-level expansion request."""

    scene_script: dict[str, Any] = Field(..., description="Validated SceneScript JSON")
    intent: str = Field(..., description="camera_motion | character_motion")
    target_id: str | None = Field(default=None, description="camera/character id to animate")
    preset_id: str
    start_frame: int = Field(default=0, ge=0)
    duration_frames: int = Field(default=15, ge=1)
    target_position: list[float] | None = Field(default=None, description="[x, y, z] for character presets")
    stop_distance: float = Field(default=1.2)


class DirectorMotionCommandResponse(BaseModel):
    success: bool
    intent: str | None = None
    target: str | None = None
    preset_id: str | None = None
    operations: list[dict[str, Any]] = []
    applied_scene_script: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    violations: list[dict[str, Any]] = []


@router.post("/apply-operations", response_model=SceneOperationsResponse)
async def apply_scene_operations_endpoint(
    request: SceneOperationsRequest,
) -> SceneOperationsResponse:
    """Validate and apply structured scene operations to a SceneScript.

    The white-model design mode's single application point: an agent (or a
    future editor) emits ops, the service validates the batch against the
    SceneScript schema (enum-checked, bbox-bounded, all-or-nothing) and
    returns the new script. ``mcp_request`` ops execute against a Blender MCP
    server when ``use_mcp`` is set; a batch containing them without a server
    is rejected with a queryable ``mcp_unavailable`` code.
    """
    from app.services.scene3d.scene_script_tool_service import (
        SceneOperationError,
        SceneScriptToolService,
    )

    service = SceneScriptToolService()
    mcp_client = None
    if request.use_mcp:
        from app.core.config import get_settings
        from app.services.scene3d.blender_mcp_client import BlenderMcpClient

        try:
            mcp_client = BlenderMcpClient(get_settings())
        except Exception as exc:  # noqa: BLE001 - spawn failure is a coded 503.
            raise HTTPException(
                status_code=503,
                detail={
                    "error": f"Blender MCP server unavailable: {str(exc)[:200]}",
                    "error_code": "mcp_unavailable",
                },
            ) from exc

    try:
        result = service.apply_operations(
            request.scene_script,
            request.operations,
            mcp_client=mcp_client,
        )
        return SceneOperationsResponse(
            success=True,
            scene_script=result.scene_script.model_dump(mode="json"),
            applied=result.applied,
            warnings=result.warnings,
            mcp_results=result.mcp_results,
        )
    except SceneOperationError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": str(e),
                "error_code": e.code,
                "violations": e.violations,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Scene operations failed: {str(e)[:200]}",
        )
    finally:
        if mcp_client is not None:
            mcp_client.close()


@router.post("/director-motion", response_model=DirectorMotionCommandResponse)
def apply_director_motion_command(request: DirectorMotionCommandRequest) -> DirectorMotionCommandResponse:
    """Expand a director motion intent into gated SceneScript ops."""
    from app.services.scene3d.director_motion import (
        DirectorMotionError,
        expand_director_motion,
    )
    from app.services.scene3d.scene_script_tool_service import (
        SceneOperationError,
        SceneScriptToolService,
    )

    try:
        from app.schemas.scene_script import SceneScriptRoot

        validated_script = SceneScriptRoot.model_validate(request.scene_script)
        command = expand_director_motion(
            validated_script,
            intent=request.intent,
            target_id=request.target_id,
            preset_id=request.preset_id,
            start_frame=request.start_frame,
            duration_frames=request.duration_frames,
            target=request.target_position,
            stop_distance=request.stop_distance,
)
    except DirectorMotionError as error:
        raise HTTPException(
            status_code=400,
            detail={"error": error.message, "error_code": error.code},
) from error

    operations = command["operations"]
    if not operations:
        return DirectorMotionCommandResponse(success=True, intent=command["intent"], target=command["target"], preset_id=command["preset_id"], operations=[])

    service = SceneScriptToolService()
    try:
        result = service.apply_operations(request.scene_script, operations)
    except SceneOperationError as error:
        raise HTTPException(
            status_code=400,
            detail={"error": str(error), "error_code": error.code, "violations": error.violations},
) from error

    return DirectorMotionCommandResponse(
        success=True,
        intent=command["intent"],
        target=command["target"],
        preset_id=command["preset_id"],
        operations=operations,
        applied_scene_script=result.scene_script.model_dump(mode="json"),
    )

# ---------------------------------------------------------------------------
# SceneScript consistency gate (Dramagic-style pre-render check)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# When/then trigger events (director command bar V2)
# ---------------------------------------------------------------------------


class TriggerEventRequest(BaseModel):
    """A when/then trigger event to expand through the gate."""

    scene_script: dict[str, Any] = Field(..., description="Validated SceneScript JSON")
    trigger: str = Field(..., description="sit | stand | arrive | face | line_spoken")
    trigger_target_id: str = Field(..., description="character id the trigger watches")
    trigger_frame: int = Field(default=0, ge=0)
    trigger_target_position: list[float] | None = Field(default=None)
    trigger_target_yaw: float | None = Field(default=None)
    then_ops: list[dict[str, Any]] = Field(default_factory=list)
    then_frame: int = Field(default=0, ge=0)


class TriggerEventResponse(BaseModel):
    success: bool
    trigger: str | None = None
    trigger_target: str | None = None
    trigger_frame: int | None = None
    then_frame: int | None = None
    operations: list[dict[str, Any]] = []
    applied_scene_script: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None


@router.post("/trigger-event", response_model=TriggerEventResponse)
def apply_trigger_event_command(request: TriggerEventRequest) -> TriggerEventResponse:
    """Expand a when/then trigger into gated SceneScript ops."""
    from app.services.scene3d.trigger_events import (
        TriggerError,
        expand_trigger_event,
    )
    from app.services.scene3d.scene_script_tool_service import (
        SceneOperationError,
        SceneScriptToolService,
    )
    from app.schemas.scene_script import SceneScriptRoot

    try:
        validated_script = SceneScriptRoot.model_validate(request.scene_script)
        event = expand_trigger_event(
            trigger=request.trigger,
            trigger_target_id=request.trigger_target_id,
            trigger_scene_script=validated_script,
            trigger_frame=request.trigger_frame,
            trigger_target_position=request.trigger_target_position,
            trigger_target_yaw=request.trigger_target_yaw,
            then_ops=request.then_ops,
            then_frame=request.then_frame,
        )
    except TriggerError as error:
        return TriggerEventResponse(
            success=False,
            trigger=request.trigger,
            trigger_target=request.trigger_target_id,
            trigger_frame=request.trigger_frame,
            then_frame=request.then_frame,
            error=error.message,
            error_code=error.code,
        )

    operations = event["operations"]
    if not operations:
        return TriggerEventResponse(
            success=True,
            trigger=request.trigger,
            trigger_target=request.trigger_target_id,
            trigger_frame=request.trigger_frame,
            then_frame=request.then_frame,
        )

    service = SceneScriptToolService()
    try:
        result = service.apply_operations(validated_script, operations)
        return TriggerEventResponse(
            success=True,
            trigger=request.trigger,
            trigger_target=request.trigger_target_id,
            trigger_frame=request.trigger_frame,
            then_frame=request.then_frame,
            operations=operations,
            applied_scene_script=result.scene_script.model_dump(mode="json"),
        )
    except SceneOperationError as error:
        return TriggerEventResponse(
            success=False,
            trigger=request.trigger,
            trigger_target=request.trigger_target_id,
            trigger_frame=request.trigger_frame,
            then_frame=request.then_frame,
            error=str(error),
            error_code=error.code,
        )


class ConsistencyCheckRequest(BaseModel):
    scene_script: dict[str, Any] = Field(..., description="Validated SceneScript JSON")


class ConsistencyCheckResponse(BaseModel):
    success: bool
    passed: bool = True
    error_count: int = 0
    warning_count: int = 0
    issues: list[dict[str, Any]] = []
    error: str | None = None


@router.post("/consistency-check", response_model=ConsistencyCheckResponse)
async def check_scene_consistency_endpoint(
    request: ConsistencyCheckRequest,
) -> ConsistencyCheckResponse:
    """Run the Dramagic-style consistency checks against a SceneScript.

    Warnings (never errors) for the ways a script can quietly lose identity:
    unbound characters in multi-shot scenes, color collisions, dead cameras,
    shot coverage gaps, empty scenes. The workbench's pre-render gate calls
    this; the node executor also publishes the same report onto the node.
    """
    from app.schemas.scene_script import SceneScriptRoot
    from app.services.scene3d.scene_consistency import check_scene_script_consistency

    try:
        scene_script = SceneScriptRoot.model_validate(request.scene_script)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"SceneScript failed schema validation: {str(e)[:300]}",
                "error_code": "scene_script_invalid",
            },
        ) from e

    report = check_scene_script_consistency(scene_script)
    return ConsistencyCheckResponse(
        success=True,
        passed=report.passed,
        error_count=len(report.errors),
        warning_count=len(report.warnings),
        issues=[issue.to_dict() for issue in report.issues],
    )


class StoryboardRequest(BaseModel):
    scene_script: dict[str, Any] = Field(..., description="Validated SceneScript JSON")


class StoryboardResponse(BaseModel):
    success: bool
    scene_name: str = ""
    total_shots: int = 0
    total_frames: int = 0
    shots: list[dict[str, Any]] = []
    all_keyframe_frames: list[int] = []
    # E3: 分镜 advisory findings（空隙/短镜/空分镜）——算了就必须返回，
    # 否则 16 条 finding 测试锁定的语义到不了用户眼前。
    findings: list[dict[str, Any]] = []
    error: str | None = None
    error_code: str | None = None


@router.post("/storyboard", response_model=StoryboardResponse)
async def export_storyboard_endpoint(
    request: StoryboardRequest,
) -> StoryboardResponse:
    """Export a storyboard strip + shot list for a SceneScript (V3)."""
    from app.schemas.scene_script import SceneScriptRoot
    from app.services.scene3d.storyboard_export import build_storyboard, check_storyboard_span

    try:
        scene_script = SceneScriptRoot.model_validate(request.scene_script)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail={"error": f"SceneScript failed schema validation: {str(e)[:300]}", "error_code": "scene_script_invalid"},
        ) from e

    try:
        strip = build_storyboard(scene_script)
    except ValueError as e:
        return StoryboardResponse(success=False, error=str(e)[:300], error_code="storyboard_expansion_failed")

    # E3: findings 与 strip 同程返回（advisory：不因有 finding 拒绝出分镜，
    # 但必须让调用方看得见"哪些帧存疑"）
    findings = [finding.to_dict() for finding in check_storyboard_span(strip)]

    return StoryboardResponse(
        success=True,
        scene_name=strip.scene_name,
        total_shots=strip.total_shots,
        total_frames=strip.total_frames,
        shots=[entry.to_dict() for entry in strip.shots],
        all_keyframe_frames=list(strip.all_keyframe_frames),
        findings=findings,
    )


class ContinuitySuggestionsRequest(BaseModel):
    scene_script: dict[str, Any] = Field(..., description="Validated SceneScript JSON")
    segments: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional SpeechSegment list for the emotion check; omit to skip.",
    )


class ContinuitySuggestionsResponse(BaseModel):
    success: bool
    suggestions: list[dict[str, Any]] = []
    untranslated: list[dict[str, Any]] = []
    error: str | None = None
    error_code: str | None = None


@router.post("/continuity-suggestions", response_model=ContinuitySuggestionsResponse)
async def continuity_suggestions_endpoint(
    request: ContinuitySuggestionsRequest,
) -> ContinuitySuggestionsResponse:
    """Convert continuity advisory findings into conversational suggestions (V3)."""
    from app.schemas.scene_script import SceneScriptRoot
    from app.services.scene3d.continuity_suggestions import build_continuity_suggestions

    try:
        scene_script = SceneScriptRoot.model_validate(request.scene_script)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail={"error": f"SceneScript failed schema validation: {str(e)[:300]}", "error_code": "scene_script_invalid"},
        ) from e

    segments = None
    if request.segments is not None and len(request.segments) > 0:
        from app.services.scene3d.speech_orchestration import SpeechSegment
        segments = []
        for index, entry in enumerate(request.segments):
            try:
                segments.append(
                    SpeechSegment(
                        segment_id=str(entry.get("segment_id") or f"seg_{index}"),
                        character_id=str(entry.get("character_id") or ""),
                        text=str(entry.get("text") or ""),
                        start_time=float(entry.get("start_time") or 0.0),
                        end_time=float(entry.get("end_time") or 0.0),
                    )
                )
            except (AttributeError, TypeError, ValueError):
                continue

    suggestions, untranslated = build_continuity_suggestions(scene_script, segments)
    return ContinuitySuggestionsResponse(
        success=True,
        suggestions=[s.to_dict() for s in suggestions],
        untranslated=untranslated,
    )

# ---------------------------------------------------------------------------
# Speech forced alignment (bed audio -> per-line timings, C mode)
# ---------------------------------------------------------------------------


class AlignSpeechRequest(BaseModel):
    audio_path: str | None = Field(
        default=None,
        description="Path to the audio take (the generated bed); omit to resolve by asset_id",
    )
    asset_id: str | None = Field(
        default=None,
        description="Project asset whose content is the audio take (resolved server-side)",
    )
    lines: list[dict[str, Any]] = Field(
        ...,
        description="Known script lines: [{character_id, text, start_time?}]",
    )
    speech_only: bool = Field(
        True,
        description="Hint: the take mixes dialogue with SFX/ambience/BGM",
    )
    regenerate_low_confidence: bool = Field(
        True,
        description=(
            "Automatically re-measure low-confidence lines on their own "
            "(B mode, V0.2 §14.3): the aligned start is kept, the duration is "
            "re-measured and clamped against the next line. Set false to get "
            "the raw alignment boundaries."
        ),
    )


class AlignSpeechResponse(BaseModel):
    success: bool
    align_source: str = "estimated"
    segments: list[dict[str, Any]] = []
    low_confidence_ids: list[str] = []
    regenerated_ids: list[str] = []
    regeneration_duration_source: str | None = None
    bed_duration_seconds: float | None = None
    warnings: list[str] = []
    error: str | None = None


def _resolve_render_audio(
    audio_path: str | None,
    audio_asset_id: str | None,
) -> tuple[str | None, list[str]]:
    """Resolve the animatic bed, degrading to (None, [reason]) when it can't.

    The bed is decoration on top of a successful render: a path that does not
    exist must never fail the render — it must be reported so the author knows
    why the previs is silent (engineering standard §4).
    """

    if not audio_path and not audio_asset_id:
        return None, []
    resolved = audio_path
    if not resolved and audio_asset_id:
        from app.core.config import get_settings

        resolved = _resolve_asset_path(get_settings(), audio_asset_id)
    if not resolved or not os.path.isfile(resolved):
        return None, [
            "音频床不可用（路径不存在或资产未解析），已输出无声预演。"
        ]
    return resolved, []


def _resolve_asset_path(settings: Any, asset_id: str) -> str:
    """Resolve a project asset id to a local file path (timeline pattern)."""

    from app.persistence.asset_library_repository import V2AssetLibraryRepository
    from app.persistence.database import create_v2_database
    from app.services.scene3d.speech_alignment import SpeechAlignmentError
    from app.services.v2_storage_adapter import StorageAdapter

    database = create_v2_database(settings.media_data_dir)
    try:
        version = V2AssetLibraryRepository(database).find_version(asset_id=asset_id)
    finally:
        database.dispose()
    if version is None:
        raise SpeechAlignmentError("alignment_asset_not_found", f"Asset not found: {asset_id}")
    path = StorageAdapter(settings.media_data_dir).resolve_local_path(version.storage_key)
    return str(path)


@router.post("/align-speech", response_model=AlignSpeechResponse)
async def align_speech_endpoint(request: AlignSpeechRequest) -> AlignSpeechResponse:
    """Recover per-line timings from one audio take (forced alignment).

    The C-mode foundation: StepAudio 3 Gen returns no timestamps, so a
    dialogue-driven pipeline must align the known script against the take.
    ``align_source`` names the engine that actually ran (whisperx when
    installed, else the deterministic estimated layout) and
    ``low_confidence_ids`` marks segments too weak to drive lip-sync
    silently — the caller decides whether to accept or regenerate.
    """
    from pathlib import Path

    from app.core.config import get_settings
    from app.services.scene3d.speech_alignment import (
        SpeechAlignmentError,
        build_speech_aligner,
        low_confidence_ids,
        probe_audio_duration_seconds,
    )

    settings = get_settings()
    try:
        audio_path = request.audio_path
        if not audio_path:
            if not request.asset_id:
                raise SpeechAlignmentError(
                    "alignment_audio_required",
                    "Provide audio_path or asset_id for the audio take.",
                )
            audio_path = _resolve_asset_path(settings, request.asset_id)
        if not Path(audio_path).is_file():
            raise SpeechAlignmentError(
                "alignment_audio_missing",
                f"Audio file not found: {audio_path}",
            )
        aligner = build_speech_aligner(settings)
        segments = aligner.align(
            audio_path=audio_path,
            lines=request.lines,
            speech_only=request.speech_only,
        )
    except SpeechAlignmentError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": str(e), "error_code": e.code},
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Speech alignment failed: {str(e)[:200]}",
        ) from e

    low = low_confidence_ids(segments)
    warnings: list[str] = []
    if low:
        warnings.append(
            f"{len(low)} segment(s) below the lip-sync confidence threshold; "
            "regenerate them per-line or accept the estimated band explicitly.",
        )
    if aligner.name == "estimated":
        warnings.append(
            "Alignment used the deterministic estimated layout (whisperX not "
            "installed): order is right, boundaries are not measured."
        )

    # B-mode regeneration (V0.2 §14.3): a weak line is re-measured on its own
    # instead of silently trusted. The aligned START is kept, the DURATION is
    # re-measured (a real TTS engine when configured, the deterministic
    # estimator otherwise — the report names which), and an overrun is clamped
    # against the next line and said, never overlapped silently. Opt-out keeps
    # the raw boundaries for callers that want to do their own repair.
    regenerated_ids: list[str] = []
    regeneration_duration_source: str | None = None
    if request.regenerate_low_confidence and low:
        import asyncio

        from app.services.scene3d.speech_alignment import (
            regenerate_low_confidence_segments,
        )
        from app.services.scene3d.tts_engine_factory import (
            create_tts_engine_from_settings,
        )

        engine = create_tts_engine_from_settings(settings)
        # A real engine measures; the placeholder estimates — the report must
        # not pretend an estimate is a measurement (engineering standard §4).
        duration_source = (
            "estimated"
            if type(engine).__name__ == "SimpleTTSEngine"
            else "measured"
        )
        bed_duration = probe_audio_duration_seconds(audio_path, settings.ffprobe_path)
        regenerated = await asyncio.to_thread(
            regenerate_low_confidence_segments,
            segments,
            duration_estimator=engine.estimate_duration,
            duration_source=duration_source,
            bed_duration=bed_duration,
        )
        segments = regenerated.segments
        regenerated_ids = regenerated.regenerated_ids
        regeneration_duration_source = regenerated.duration_source
        warnings.extend(regenerated.warnings)
        if regenerated_ids:
            warnings.append(
                f"{len(regenerated_ids)} 句低置信台词已按 B 模式重测时长"
                f"（来源：{duration_source}）；起句时间仍来自对齐，"
                "置信度保持低位——长度可信不等于位置可信。"
            )

    return AlignSpeechResponse(
        success=True,
        align_source=aligner.name,
        segments=[segment.to_dict() for segment in segments],
        low_confidence_ids=low,
        regenerated_ids=regenerated_ids,
        regeneration_duration_source=regeneration_duration_source,
        bed_duration_seconds=probe_audio_duration_seconds(
            audio_path, settings.ffprobe_path
        ),
        warnings=warnings,
    )

# ---------------------------------------------------------------------------
# Voice-cast single-line resynthesis (V0.2 14.7, ADR 0003)
# ---------------------------------------------------------------------------


class VoiceCastResynthLineRequest(BaseModel):
    workflow_id: str = Field(..., description="Owning agent-canvas workflow")
    node_id: str = Field(..., description="Voice-cast node whose take to re-make")
    line_id: str = Field(..., description="The single line to re-synthesize")
    emotion_override: str | None = Field(
        default=None,
        description=(
            "Optional new emotion annotation; overrides the stored emotion. "
            "Empty string clears it."
        ),
    )
    force_remake: bool = Field(
        False,
        description=(
            "Re-synthesize even when the content-addressed cache has the "
            "identical words+emotion - the author wants a fresh take."
        ),
    )


class VoiceCastResynthLineResponse(BaseModel):
    success: bool
    line_id: str
    emotion: str = ""
    duration_seconds: float | None = None
    take_asset_id: str | None = None
    regenerated_line_ids: list[str] = []
    warnings: list[str] = []
    error: str | None = None


@router.post("/voice-cast-resynth-line", response_model=VoiceCastResynthLineResponse)
async def voice_cast_resynth_line_endpoint(
    request: VoiceCastResynthLineRequest,
) -> VoiceCastResynthLineResponse:
    """Re-synthesize one dialogue line on a stored voice-cast node.

    V0.2 14.7 content/performance layer: changing one line must not
    re-make the take. Every other line's recording is reused from the
    content-addressed cache; only the target line (or a forced-remake) goes
    to the TTS engine. The joined take is published as a new asset version
    and the node's manifest is updated in place, so downstream consumers
    (lip-sync, timeline) see the change without re-running the whole node.
    """
    import os
    from pathlib import Path

    from app.core.config import get_settings
    from app.persistence.agent_canvas_repository import (
        AgentCanvasWorkflowRepository,
    )
    from app.persistence.asset_library_repository import V2AssetLibraryRepository
    from app.persistence.database import create_v2_database
    from app.persistence.event_repository import EventRepository
    from app.persistence.project_repository import ProjectRepository
    from app.persistence.errors import V2PersistenceError
    from app.services.agent_canvas_assets import AgentCanvasAssetService
    from app.services.dialogue.audio_concat import concat_audio_files
    from app.services.dialogue.voice_cast_lines import (
        DialogueLine,
        parse_dialogue_lines,
        plan_line_synthesis,
    )
    from app.services.scene3d.speech_alignment import (
        probe_audio_duration_seconds,
    )
    from app.services.scene3d.tts_engine_factory import (
        create_tts_engine_from_settings,
    )

    settings = get_settings()
    database = create_v2_database(settings.media_data_dir)
    try:
        repo = AgentCanvasWorkflowRepository(
            database, ProjectRepository(database), EventRepository(database)
        )
        try:
            workflow = repo.get_workflow(request.workflow_id)
            node = next(
                (n for n in workflow.nodes if n.node_id == request.node_id), None
            )
        except V2PersistenceError:
            return VoiceCastResynthLineResponse(
                success=False,
                line_id=request.line_id,
                error=(
                    f"Workflow {request.workflow_id!r} not found.",
                ),
            )
        if node is None:
            return VoiceCastResynthLineResponse(
                success=False,
                line_id=request.line_id,
                error=(
                    f"Node {request.node_id!r} not found in workflow "
                    f"{request.workflow_id!r}."
                ),
            )

        lines, dropped = parse_dialogue_lines(
            node.structured_content.get("dialogue_lines")
        )
        if not lines:
            return VoiceCastResynthLineResponse(
                success=False,
                line_id=request.line_id,
                error=(
                    "The node has no stored dialogue_lines. "
                    "Run the voice-cast node first."
                ),
            )
        target = next(
            (item for item in lines if item.line_id == request.line_id), None
        )
        if target is None:
            known = ", ".join(item.line_id for item in lines)
            return VoiceCastResynthLineResponse(
                success=False,
                line_id=request.line_id,
                error=(
                    f"Line {request.line_id!r} not in dialogue_lines. "
                    f"Known: {known}"
                ),
            )

        warnings: list[str] = list(dropped)
        if request.emotion_override is not None:
            target = DialogueLine(
                line_id=target.line_id,
                text=target.text,
                emotion=request.emotion_override.strip(),
            )
            lines = [
                target if item.line_id == target.line_id else item
                for item in lines
            ]

        cache_dir = os.path.join(
            str(settings.media_data_dir), "voicecast", request.node_id
        )
        os.makedirs(cache_dir, exist_ok=True)

        # Content-addressed lookup: does the target's take already exist?
        cached_path = os.path.join(cache_dir, target.filename)
        needs_synth = request.force_remake or not os.path.isfile(cached_path)

        if needs_synth:
            engine = create_tts_engine_from_settings(settings)
            if engine is None or not getattr(engine, "is_configured", False) or type(engine).__name__ in ("SimpleTTSEngine", "PlaceholderTTSEngine"):
                return VoiceCastResynthLineResponse(
                    success=False,
                    line_id=request.line_id,
                    emotion=target.emotion,
                    warnings=warnings + [
                        "No live TTS provider configured. Add a StepFun or Fish Audio key."
                    ],
                )
            import shutil
            import tempfile

            with tempfile.TemporaryDirectory(prefix="vc_resynth_") as tmp:
                out = os.path.join(tmp, target.filename)
                batch = getattr(engine, "synthesize_batch", None)
                if batch:
                    produced = batch(
                        [{
                            "text": target.text,
                            "emotion": target.emotion or None,
                            "character_id": "",
                            "segment_id": target.line_id,
                        }],
                        tmp,
                    )
                    out = produced[0] if produced else os.path.join(tmp, f"{target.line_id}.mp3")
                else:
                    engine.synthesize(
                        target.text,
                        character_id="",
                        output_path=out,
                        emotion=target.emotion or None,
                    )
                shutil.copy2(out, cached_path)

        # Build the path map for every line (cached or just written).
        paths_map: dict[str, str] = {}
        for line in lines:
            p = os.path.join(cache_dir, line.filename)
            if os.path.isfile(p):
                paths_map[line.line_id] = p
            else:
                warnings.append(
                    f"Line {line.line_id!r} take missing from cache; "
                    "it will be silent in the re-joined take."
                )

        take_path = os.path.join(cache_dir, "take.mp3")
        ordered_paths = [
            paths_map[item.line_id] for item in lines if item.line_id in paths_map
        ]
        joined = concat_audio_files(ordered_paths, take_path)
        if not getattr(joined, "success", False):
            return VoiceCastResynthLineResponse(
                success=False,
                line_id=request.line_id,
                emotion=target.emotion,
                warnings=warnings + [
                    f"Take join failed: {getattr(joined, 'error', 'unknown')}"
                ],
            )

        # Probe the re-made line's duration.
        duration = probe_audio_duration_seconds(cached_path, settings.ffprobe_path)

        # Publish the new take so downstream consumers see it.
        take_asset_id: str | None = None
        if os.path.isfile(take_path):
            asset_repo = V2AssetLibraryRepository(database)
            asset_service = AgentCanvasAssetService(
                settings.media_data_dir, asset_repo, repo
            )
            take_bytes = Path(take_path).read_bytes()
            try:
                published = asset_service.publish_generated_bytes(
                    workflow_id=workflow.workflow_id,
                    node_id=node.node_id,
                    execution_id=(node.latest_attempt.execution_id if node.latest_attempt else ""),
                    filename="voice-cast-take.mp3",
                    mime_type="audio/mpeg",
                    content=take_bytes,
                    fingerprint=target.content_key,
                    publication_metadata={
                        "per_line": True,
                        "resynth_line_id": target.line_id,
                        "force_remake": request.force_remake,
                    },
                )
                take_asset_id = published.asset_id if published else None
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Take publish failed: {exc}")

        # Update the node's manifest in place (queryable, never-silent).
        durations: dict[str, float | None] = {}
        for item in lines:
            p = paths_map.get(item.line_id)
            if p and os.path.isfile(p):
                if item.line_id == target.line_id and needs_synth:
                    durations[item.line_id] = duration
                else:
                    durations[item.line_id] = probe_audio_duration_seconds(
                        p, settings.ffprobe_path
                    )
        plan = plan_line_synthesis(lines, cache_dir=cache_dir, regenerate_ids=[])
        manifest = plan.manifest(durations)
        # Persist the new manifest on the node. update_node treats a content
        # change as a prompt-input change (it would reset queued prep), so we
        # write the row directly under BEGIN IMMEDIATE — the same fencing
        # the repository uses, but without the preparation semantics.
        from sqlalchemy import update as _sql_update
        from app.persistence.models import AgentCanvasNodeRow

        merged_content = {
            **node.structured_content,
            "dialogue_line_manifest": manifest,
            "regenerated_line_ids": [target.line_id],
            "reused_line_ids": [
                item.line_id
                for item in lines
                if item.line_id != target.line_id
            ],
        }
        with database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                import json as _json

                result = connection.execute(
                    _sql_update(AgentCanvasNodeRow)
                    .where(
                        AgentCanvasNodeRow.workflow_id == workflow.workflow_id,
                        AgentCanvasNodeRow.node_id == node.node_id,
                    )
                    .values(structured_content_json=_json.dumps(merged_content))
                )
                if result.rowcount != 1:
                    raise RuntimeError("node row not found for manifest update")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

        return VoiceCastResynthLineResponse(
            success=True,
            line_id=request.line_id,
            emotion=target.emotion,
            duration_seconds=duration,
            take_asset_id=take_asset_id,
            regenerated_line_ids=[target.line_id],
            warnings=warnings,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return VoiceCastResynthLineResponse(
            success=False,
            line_id=request.line_id,
            emotion="",
            error=str(exc)[:300],
        )
    finally:
        database.dispose()


# ---------------------------------------------------------------------------
# Single-image depth map (white model) extraction
# ---------------------------------------------------------------------------


class DepthImageResponse(BaseModel):
    success: bool
    depth_url: str | None = None
    width: int = 0
    height: int = 0
    model_type: str = ""
    colormap: str = ""
    warnings: list[str] = []
    error: str | None = None


@router.post("/extract-depth-image", response_model=DepthImageResponse)
async def extract_depth_image_endpoint(
    file: UploadFile = File(...),
    model_type: str = "DPT_Hybrid",
    colormap: str = "grayscale",
) -> DepthImageResponse:
    """Extract a depth map (white model) from a single uploaded image.

    The panorama/照片 counterpart of ``/extract-depth``: the result is stored
    under the media data dir and served from ``/media`` so the workbench can
    show it (and a video node can bind it as a control reference). Missing
    MiDaS dependencies surface as a 400 with the dependency report — never a
    silent placeholder image.
    """
    import tempfile
    from pathlib import Path

    from app.services.scene3d.depth_estimator import (
        DepthEstimationError,
        check_dependencies,
        estimate_depth_from_image,
    )

    deps = check_dependencies()
    if not (deps["torch"] and deps["opencv"] and deps["numpy"]):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Depth estimation dependencies are not installed "
                "(need torch + opencv + numpy).",
                "error_type": "missing_dependency",
                "dependencies": deps,
            },
        )

    suffix = Path(file.filename or "image.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        suffix = ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = await asyncio.to_thread(
            estimate_depth_from_image,
            input_image_path=tmp_path,
            model_type=model_type,
            colormap=colormap,
        )
    except DepthEstimationError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": str(e), "error_type": e.error_type},
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Depth estimation failed: {str(e)[:200]}",
        ) from e
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    # Serve the depth map from the mounted media dir so the workbench (and a
    # video node) can fetch it.
    from app.core.config import get_settings
    from app.services.v2_data_boundary import validate_v2_data_path

    settings = get_settings()
    relative = (
        Path("assets")
        / "provider-output"
        / "depth"
        / f"{result.asset_id}.png"
    )
    target = settings.media_data_dir / relative
    try:
        validate_v2_data_path(settings.media_data_dir, target, operation="v2-depth-image-store")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(result.output_video_path).read_bytes())
    except OSError:
        # The temp file is gone once this request returns; serving from the
        # media dir is the durable path, so a failure is an error, not a
        # silent degradation.
        raise HTTPException(
            status_code=500,
            detail="Depth map could not be stored for serving.",
        ) from None

    return DepthImageResponse(
        success=True,
        depth_url=f"/media/{relative.as_posix()}",
        width=result.output_width,
        height=result.output_height,
        model_type=result.model_type,
        colormap=result.colormap,
    )

# ---------------------------------------------------------------------------
# 2.5D depth-reprojection orbit render
# ---------------------------------------------------------------------------


class DepthOrbitResponse(BaseModel):
    success: bool
    video_url: str | None = None
    frame_count: int = 0
    keyframe_urls: list[str] = []
    max_hole_fraction: float = 0.0
    warnings: list[str] = []
    error: str | None = None


@router.post("/render-depth-orbit", response_model=DepthOrbitResponse)
async def render_depth_orbit_endpoint(
    file: UploadFile = File(..., description="Source image"),
    depth_file: UploadFile | None = File(None, description="Optional grayscale depth map"),
    num_frames: int = Form(60),
    sweep_degrees: float = Form(40.0),
    elevation_degrees: float = Form(6.0),
    depth_near: float = Form(0.6),
    depth_far: float = Form(5.0),
    encode_video: bool = Form(True),
) -> DepthOrbitResponse:
    """Render an orbiting virtual camera over an image (2.5D reprojection).

    The panorama's first-tier path: back-project the image onto its depth
    map and swing a virtual camera. Disocclusion holes are inpainted and the
    per-frame hole fraction is REPORTED (``max_hole_fraction`` + warnings) —
    never silently presented as geometry. Output is served from ``/media``.
    """
    import tempfile
    from pathlib import Path

    from app.core.config import get_settings
    from app.services.scene3d.depth_reprojection import render_depth_orbit

    settings = get_settings()
    tmp_paths: list[str] = []
    try:
        suffix = Path(file.filename or "image.png").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webm", ".bmp", ".webp"}:
            suffix = ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            image_path = tmp.name
        tmp_paths.append(image_path)

        depth_path = None
        if depth_file is not None and depth_file.filename:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(await depth_file.read())
                depth_path = tmp.name
            tmp_paths.append(depth_path)

        result = await asyncio.to_thread(
            render_depth_orbit,
            image_path=image_path,
            depth_path=depth_path,
            num_frames=max(2, min(300, num_frames)),
            sweep_degrees=max(-180.0, min(180.0, sweep_degrees)),
            elevation_degrees=max(-60.0, min(60.0, elevation_degrees)),
            depth_near=max(0.1, depth_near),
            depth_far=max(depth_near + 0.5, depth_far),
            encode_video=encode_video,
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail={"error": str(e)[:200], "error_type": "orbit_render_failed"},
        ) from e
    finally:
        for path in tmp_paths:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass

    if not result.success:
        raise HTTPException(
            status_code=500,
            detail={"error": result.error or "orbit render failed", "error_type": "orbit_render_failed"},
        )

    # Serve artifacts from the mounted media dir.
    from app.services.v2_data_boundary import validate_v2_data_path

    keyframe_urls: list[str] = []
    video_url: str | None = None
    try:
        if result.video_path:
            relative = Path("assets") / "provider-output" / "orbit" / (Path(result.video_path).name)
            target = settings.media_data_dir / relative
            validate_v2_data_path(settings.media_data_dir, target, operation="v2-orbit-store")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(Path(result.video_path).read_bytes())
            video_url = f"/media/{relative.as_posix()}"
        for index, keyframe_path in enumerate(
            sorted(Path(result.frames_dir or "").glob("keyframe_*.png"))
        ):
            relative = (
                Path("assets") / "provider-output" / "orbit" / f"orbit_{index}_{keyframe_path.name}"
            )
            target = settings.media_data_dir / relative
            validate_v2_data_path(settings.media_data_dir, target, operation="v2-orbit-store")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(keyframe_path.read_bytes())
            keyframe_urls.append(f"/media/{relative.as_posix()}")
    except OSError:
        raise HTTPException(
            status_code=500,
            detail="Orbit artifacts could not be stored for serving.",
        ) from None

    return DepthOrbitResponse(
        success=True,
        video_url=video_url,
        frame_count=result.frame_count,
        keyframe_urls=keyframe_urls,
        max_hole_fraction=result.max_hole_fraction,
        warnings=result.warnings,
    )


@router.post("/transition-proposals", response_model=TransitionProposalsResponse)
async def propose_shot_transitions(request: TransitionProposalsRequest) -> TransitionProposalsResponse:
    """Propose ways to get from shot A to shot B (advisory, never applied).

    The readings come from the V0.2 research (A 连续运动 / B 视线特写切换 /
    声音桥 / 说完再切 / C 时间空间跳跃 / D 视角切换); each carries the
    operations the front-end's motion presets can execute. The creator
    chooses — nothing is auto-applied.
    """
    try:
        scene_script = _validate_scene_script(request.scene_script)
    except HTTPException:
        raise

    warnings: list[str] = []
    shots_by_id = {shot.id: shot for shot in scene_script.shots}
    shot_a = shots_by_id.get(request.shot_a_id)
    shot_b = shots_by_id.get(request.shot_b_id)
    if shot_a is None or shot_b is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Shot not found: "
                f"{request.shot_a_id if shot_a is None else request.shot_b_id}"
            ),
        )

    # Speech segments are best-effort: a malformed entry must not kill the
    # proposals (silence-based readings simply degrade).
    segments: list[SpeechSegment] = []
    for index, raw_segment in enumerate(request.segments):
        try:
            segments.append(
                SpeechSegment(
                    segment_id=str(raw_segment.get("segment_id") or f"seg_{index}"),
                    character_id=str(raw_segment.get("character_id") or ""),
                    text=str(raw_segment.get("text") or ""),
                    start_time=float(raw_segment.get("start_time") or 0.0),
                    end_time=float(raw_segment.get("end_time") or 0.0),
                )
            )
        except (AttributeError, TypeError, ValueError):
            warnings.append(f"segments[{index}] 无法解析，已忽略（停顿类方案可能退化）。")

    proposals = propose_transitions(
        shot_a=shot_a,
        shot_b=shot_b,
        characters=list(scene_script.characters),
        cameras=list(scene_script.cameras),
        segments=segments,
        frame_rate=scene_script.scene.frame_rate,
        scene_duration=scene_script.scene.duration,
        transition_frames=request.transition_frames,
    )

    # Optional LLM narrative layer (V0.2 §6.2/§15): the prose explaining each
    # reading for THIS pair. Operations stay the rule layer's; an unavailable
    # LLM degrades to rule narratives with a reported reason (never silent).
    # The call is sync httpx, so it runs off the event loop (same discipline as
    # the render endpoints).
    narrative_source = "rules"
    if request.polish_narratives:
        import asyncio

        from app.services.scene3d.transition_narratives import (
            polish_transition_narratives,
        )

        polished = await asyncio.to_thread(
            polish_transition_narratives,
            shot_a_id=request.shot_a_id,
            shot_b_id=request.shot_b_id,
            proposals=proposals,
        )
        proposals = polished.proposals
        narrative_source = polished.source
        if polished.degraded_reason:
            warnings.append(polished.degraded_reason)

    # Optional LLM proposal layer (V0.2 §15 deepening): readings beyond the
    # rule catalogue. Every proposed reading is validated against the operation
    # vocabulary and this scene's ids before it reaches the response; drops are
    # reported, never silent.
    if request.propose_readings:
        import asyncio

        from app.services.scene3d.transition_narratives import (
            SceneVocabulary,
            propose_additional_readings,
        )

        vocabulary = SceneVocabulary.from_scene(
            shots=list(scene_script.shots),
            characters=list(scene_script.characters),
            cameras=list(scene_script.cameras),
            reserved_ids=[proposal.id for proposal in proposals],
        )
        additional = await asyncio.to_thread(
            propose_additional_readings,
            shot_a_id=request.shot_a_id,
            shot_b_id=request.shot_b_id,
            vocabulary=vocabulary,
            existing_labels=[
                proposal.label for proposal in proposals
            ] + list(request.exclude_reading_ids),
            exclude_ids=list(request.exclude_reading_ids),
        )
        proposals = [*proposals, *additional.readings]
        if additional.degraded_reason:
            warnings.append(additional.degraded_reason)
        warnings.extend(additional.dropped)

    # The declared entry reading, checked against the pair the picker is
    # currently showing (V0.2 §13 第 5 问). Computed here because this is
    # where the applied speech timeline arrives.
    if request.workflow_id and request.node_id:
        persist_warning = _persist_retained_readings(
            request,
            node_id=request.node_id,
            workflow_id=request.workflow_id,
        )
        # E7/§4 never-silent：持久化失败可见化，并入响应 warnings（而非静默丢多轮记忆）
        if persist_warning:
            warnings.append(persist_warning)

    return TransitionProposalsResponse(
        success=True,
        proposals=[proposal.to_dict() for proposal in proposals],
        warnings=warnings,
        narrative_source=narrative_source,
        intent_audit=audit_declared_intent(
            declared_id=shot_b.transition_intent,
            proposals=proposals,
            shot_b_id=shot_b.id,
        ),
    )

def _persist_retained_readings(request, node_id, workflow_id, settings=None):
    """Write retained_reading_ids onto the scene-3d node's structured_content.

    V0.2 §14.5 known boundary: multi-round proposal memory lives in panel
    state, reset on refresh. This call persists the author's applied or
    dismissed readings so a session reload can read them back, closing the
    cross-session gap without changing the endpoint contract.
    """
    if not request.retained_reading_ids:
        return
    if settings is None:
        from app.core.config import get_settings
        settings = get_settings()
    from app.persistence.agent_canvas_repository import (
        AgentCanvasWorkflowRepository,
    )
    from app.persistence.database import create_v2_database
    from app.persistence.event_repository import EventRepository
    from app.persistence.project_repository import ProjectRepository

    database = create_v2_database(settings.media_data_dir)
    try:
        repo = AgentCanvasWorkflowRepository(
            database, ProjectRepository(database), EventRepository(database)
        )
        workflow = repo.get_workflow(workflow_id)
        node = next(
            (n for n in workflow.nodes if n.node_id == node_id), None
        )
        if node is None:
            return
        # Same direct-row-write rationale as the resynth manifest: a content
        # change must not re-enter prompt preparation (ADR 0004 discipline).
        from sqlalchemy import update as _sql_update
        from app.persistence.models import AgentCanvasNodeRow

        merged = {
            **node.structured_content,
            "retained_reading_ids": list(request.retained_reading_ids),
        }
        with database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                import json as _json

                connection.execute(
                    _sql_update(AgentCanvasNodeRow)
                    .where(
                        AgentCanvasNodeRow.workflow_id == workflow_id,
                        AgentCanvasNodeRow.node_id == node_id,
                    )
                    .values(structured_content_json=_json.dumps(merged))
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
    except Exception:
        # E7 / §4 可观测降级：持久化失败不阻断响应，但也绝不静默 pass
        import logging
        logging.getLogger(__name__).warning(
            "retained_readings persist failed (workflow=%s node=%s); multi-round memory will not survive a reload",
            workflow_id,
            node_id,
            exc_info=True,
        )
        return "多轮记忆保留集持久化失败（本次会话有效，刷新后可能丢失；详见后端日志）。"
    finally:
        database.dispose()
