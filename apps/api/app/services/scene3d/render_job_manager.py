"""Asynchronous render job manager for SceneScript 3D previs.

Manages a queue of render jobs executed in background threads. Jobs are
stored in memory (suitable for single-instance deployments); for multi-instance
or persistent deployments, replace the in-memory store with a database/Redis
backend.

Usage:
    manager = RenderJobManager()
    job_id = manager.submit(scene_script, render_video=True)
    job = manager.get(job_id)
    if job.status == "completed":
        print(job.result.video_path)
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from typing import Any

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.blender_renderer import render_scene_script
from app.services.scene3d.encoder import encode_png_sequence, mux_audio_to_video
from app.services.scene3d.keyframes import extract_keyframes


# ---------------------------------------------------------------------------
# Job data structures
# ---------------------------------------------------------------------------


@dataclass
class RenderJobResult:
    """Result of a completed render job."""

    output_dir: str
    frame_count: int = 0
    video_path: str | None = None
    animatic_video_path: str | None = None
    audio_muxed: bool = False
    keyframes: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    blender_version: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class RenderJob:
    """A render job with its current state."""

    job_id: str
    status: str = "pending"  # pending | running | completed | failed | cancelled
    scene_script: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    result: RenderJobResult | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    progress: float = 0.0  # 0.0 - 1.0
    _future: Future | None = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Job manager
# ---------------------------------------------------------------------------


class RenderJobManager:
    """Manages asynchronous render jobs.

    Thread-safe in-memory job store with a background thread pool for
    executing renders. Jobs are retained in memory until explicitly cleaned
    up or the process restarts.
    """

    def __init__(self, max_workers: int = 2, job_ttl_seconds: int = 3600):
        """Initialize the job manager.

        Args:
            max_workers: Maximum concurrent render threads.
            job_ttl_seconds: Time-to-live for completed/failed jobs before
                              they are eligible for cleanup.
        """
        self._jobs: dict[str, RenderJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="scene3d-render",
        )
        self._job_ttl = job_ttl_seconds

    # ------------------------------------------------------------------
    # Job submission
    # ------------------------------------------------------------------

    def submit(
        self,
        scene_script: dict[str, Any] | SceneScriptRoot,
        render_video: bool = True,
        extract_keyframes_flag: bool = True,
        blender_executable: str | None = None,
        timeout_seconds: int = 600,
        output_dir: str | None = None,
        audio_path: str | None = None,
        audio_warning: list[str] | None = None,
    ) -> str:
        """Submit a new render job.

        Args:
            scene_script: SceneScript dict or validated SceneScriptRoot.
            render_video: Whether to encode PNG frames to MP4.
            extract_keyframes_flag: Whether to extract 5 keyframes per shot.
            blender_executable: Override Blender executable path.
            timeout_seconds: Maximum render time per job.
            output_dir: Override output directory (auto-generated if None).
            audio_path: Dialogue bed to mux into the render (the animatic,
                V0.2 §14.9). Omit for a silent previs.
            audio_warning: Resolution warnings to publish with the job (e.g.
                an unresolvable bed), so the degradation stays visible.

        Returns:
            Job ID string.
        """
        job_id = str(uuid.uuid4())[:12]

        # Convert SceneScriptRoot to dict if needed
        if isinstance(scene_script, SceneScriptRoot):
            scene_script_dict = scene_script.model_dump(mode="json")
        else:
            scene_script_dict = scene_script

        job = RenderJob(
            job_id=job_id,
            scene_script=scene_script_dict,
            options={
                "render_video": render_video,
                "extract_keyframes": extract_keyframes_flag,
                "blender_executable": blender_executable,
                "timeout_seconds": timeout_seconds,
                "output_dir": output_dir,
                # Animatic (V0.2 §14.9): the bed path plus any resolution
                # warning, both published with the result so the degradation
                # stays queryable after the job finishes.
                "audio_path": audio_path,
                "audio_warning": list(audio_warning or []),
            },
        )

        with self._lock:
            self._jobs[job_id] = job

        # Submit to thread pool
        future = self._executor.submit(self._execute_job, job_id)
        job._future = future

        return job_id

    # ------------------------------------------------------------------
    # Job queries
    # ------------------------------------------------------------------

    def get(self, job_id: str) -> RenderJob | None:
        """Get a job by ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, status: str | None = None) -> list[RenderJob]:
        """List all jobs, optionally filtered by status."""
        with self._lock:
            jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status == status]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> bool:
        """Attempt to cancel a pending or running job.

        Note: Blender subprocess cannot be forcibly killed from Python in all
        cases; cancellation sets the job status and the render thread will
        check for cancellation between phases.

        Returns:
            True if job was found and cancellation requested.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in ("pending", "running"):
                job.status = "cancelled"
                job.completed_at = time.time()
                if job._future:
                    job._future.cancel()
                return True
            return False

    def cleanup(self) -> int:
        """Remove jobs older than TTL. Returns number of jobs removed."""
        now = time.time()
        removed = 0
        with self._lock:
            for job_id in list(self._jobs.keys()):
                job = self._jobs[job_id]
                if job.completed_at and (now - job.completed_at) > self._job_ttl:
                    del self._jobs[job_id]
                    removed += 1
        return removed

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the thread pool."""
        self._executor.shutdown(wait=wait)

    # ------------------------------------------------------------------
    # Internal: job execution
    # ------------------------------------------------------------------

    def _execute_job(self, job_id: str) -> None:
        """Execute a render job (runs in background thread)."""
        import os
        import tempfile

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "running"
            job.started_at = time.time()

        try:
            # Validate SceneScript
            scene_script = SceneScriptRoot.model_validate(job.scene_script)

            # Setup output directory
            output_dir = job.options.get("output_dir")
            if output_dir is None:
                output_dir = os.path.join(tempfile.gettempdir(), f"scene3d_{job_id}")
            frames_dir = os.path.join(output_dir, "frames")
            os.makedirs(frames_dir, exist_ok=True)

            # Check for cancellation
            if self._is_cancelled(job_id):
                return

            # Phase 1: Render PNG frames
            job.progress = 0.1
            render_result = render_scene_script(
                scene_script,
                frames_dir,
                executable=job.options.get("blender_executable"),
                timeout_seconds=job.options.get("timeout_seconds", 600),
            )

            if not render_result.success or render_result.frame_count == 0:
                raise RuntimeError(
                    render_result.error or "Render produced no frames"
                )

            job.progress = 0.6

            # Phase 2: Encode video (optional)
            video_path = None
            animatic_video_path = None
            audio_muxed = False
            job_warnings: list[str] = list(job.options.get("audio_warning") or [])
            if job.options.get("render_video", True):
                if self._is_cancelled(job_id):
                    return
                video_path = os.path.join(output_dir, "previs.mp4")
                encode_result = encode_png_sequence(
                    frames_dir,
                    video_path,
                    fps=scene_script.scene.frame_rate,
                )
                if not encode_result.success:
                    video_path = None  # Don't fail whole job if encoding fails
                elif job.options.get("audio_path"):
                    # Phase 2.5: the animatic mux (V0.2 §14.9). A failure keeps
                    # the silent previs and reports why — never the reverse.
                    animatic_video_path = os.path.join(output_dir, "previs_animatic.mp4")
                    mux_result = mux_audio_to_video(
                        video_path,
                        str(job.options["audio_path"]),
                        animatic_video_path,
                    )
                    if getattr(mux_result, "success", False):
                        audio_muxed = True
                    else:
                        animatic_video_path = None
                        job_warnings.append(
                            "音频床混入失败，已输出无声预演："
                            f"{getattr(mux_result, 'error', 'unknown')}"
                        )

            job.progress = 0.8

            # Phase 3: Extract keyframes (optional)
            keyframes_result = []
            if job.options.get("extract_keyframes", True):
                if self._is_cancelled(job_id):
                    return
                keyframes_dir = os.path.join(output_dir, "keyframes")
                shot_keyframes = extract_keyframes(
                    scene_script, frames_dir, keyframes_dir
                )
                for skf in shot_keyframes:
                    keyframes_result.append({
                        "shot_id": skf.shot_id,
                        "frames": skf.frames,
                        "files": skf.files,
                    })

            job.progress = 1.0

            # Set result
            result = RenderJobResult(
                output_dir=output_dir,
                frame_count=render_result.frame_count,
                video_path=video_path,
                animatic_video_path=animatic_video_path,
                audio_muxed=audio_muxed,
                keyframes=keyframes_result,
                warnings=job_warnings,
                duration_seconds=render_result.duration_seconds,
                blender_version=render_result.blender_version,
            )

            with self._lock:
                job = self._jobs.get(job_id)
                if job and job.status != "cancelled":
                    job.status = "completed"
                    job.result = result
                    job.completed_at = time.time()

        except Exception as exc:
            with self._lock:
                job = self._jobs.get(job_id)
                if job and job.status != "cancelled":
                    job.status = "failed"
                    job.error = str(exc)
                    job.completed_at = time.time()

    def _is_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job is not None and job.status == "cancelled"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_manager: RenderJobManager | None = None


def get_render_job_manager() -> RenderJobManager:
    """Get the module-level singleton render job manager."""
    global _default_manager
    if _default_manager is None:
        _default_manager = RenderJobManager()
    return _default_manager
