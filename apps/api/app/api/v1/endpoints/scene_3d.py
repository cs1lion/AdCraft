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
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.blender_renderer import (
    get_blender_capability,
    render_scene_script,
)
from app.services.scene3d.encoder import encode_png_sequence
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


class RenderResponse(BaseModel):
    success: bool
    job_id: str
    output_dir: str | None = None
    frame_count: int = 0
    video_path: str | None = None
    keyframes: list[dict[str, Any]] = []
    duration_seconds: float = 0.0
    blender_version: str | None = None
    error: str | None = None


class KeyframesRequest(BaseModel):
    scene_script: dict[str, Any]
    frames_dir: str = Field(..., description="Directory containing rendered frame_XXXX.png files")
    output_dir: str | None = None


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
    )
    return RenderResponse(job_id=job_id, **result)


def _run_render_pipeline(
    scene_script: SceneScriptRoot,
    render_video: bool,
    do_extract_keyframes: bool,
    blender_executable: str | None,
    timeout_seconds: int,
    job_id: str,
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
            "keyframes": [],
            "duration_seconds": render_result.duration_seconds,
            "blender_version": render_result.blender_version,
            "error": render_result.error or "Render produced no frames",
        }

    video_path = None
    if render_video:
        video_path = os.path.join(output_dir, "previs.mp4")
        encode_result = encode_png_sequence(
            frames_dir,
            video_path,
            fps=scene_script.scene.frame_rate,
        )
        if not encode_result.success:
            video_path = None  # Don't fail the whole render if encoding fails

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
        "keyframes": keyframes_result,
        "duration_seconds": render_result.duration_seconds,
        "blender_version": render_result.blender_version,
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
    manager = get_render_job_manager()
    job_id = manager.submit(
        scene_script=request.scene_script,
        render_video=request.render_video,
        extract_keyframes_flag=request.extract_keyframes,
        blender_executable=request.blender_executable,
        timeout_seconds=request.timeout_seconds,
        output_dir=request.output_dir,
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
            "keyframes": job.result.keyframes,
            "duration_seconds": job.result.duration_seconds,
            "blender_version": job.result.blender_version,
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

    Validates format (MP4/WebM/MOV), size (<=100MB), duration (<=10s),
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

