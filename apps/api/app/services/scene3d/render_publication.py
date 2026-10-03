"""Publish only a completed job's known MP4 outputs into the static media root."""

from __future__ import annotations

import shutil
from pathlib import Path


def publish_render_video(
    *,
    media_root: str | Path,
    job_id: str,
    output_dir: str | None,
    video_path: str | None,
    filename: str,
) -> str | None:
    if not output_dir or not video_path:
        return None
    if not job_id or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for char in job_id
    ):
        raise ValueError("Invalid render job publication identity")
    if filename not in {"previs.mp4", "animatic.mp4"}:
        raise ValueError("Unsupported render publication filename")
    source = Path(video_path).resolve()
    root = Path(output_dir).resolve()
    if not source.is_relative_to(root) or source.suffix.lower() != ".mp4" or not source.is_file():
        raise ValueError("Render output is missing or outside its job directory")
    destination = Path(media_root).resolve() / "scene3d" / job_id / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.stat().st_size != source.stat().st_size:
        temporary = destination.with_suffix(".publishing")
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    return f"/media/scene3d/{job_id}/{filename}"
