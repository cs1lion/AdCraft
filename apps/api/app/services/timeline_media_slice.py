"""Slice delivered media to a timeline window (the alignment delivery path).

The timeline is not only the post-generation assembly layer — it is also the
shot schedule that DIRECTS generation. When a video node's timeline clip
says "you are the 3.0s–5.0s shot", the upstream references that node consumes
(the 3D previs rehearsal video, the speech audio for that window) must be
delivered as the SLICE for that window — otherwise the model receives a
whole 9-second rehearsal film for a 2-second shot, and the temporal alignment
the timeline exists to provide is silently lost.

This module performs the slice: ffmpeg trim with frame-accurate re-encode
for video (``-c copy`` would cut on keyframes and drift by up to a GOP),
stored under the workflow's media directory and served like any other
provider input.

Degradation is queryable, never silent (engineering standard §4): a missing
or unreadable source, a window beyond the source's length (clamped with a
warning), or an ffmpeg failure all return ``sliced=False`` with warnings —
the caller then delivers the whole asset and KNOWS the alignment is weaker,
rather than silently sending the wrong thing.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

MAX_SLICE_SECONDS = 30.0
"""Provider-side hard ceiling on a reference slice (video models cap at ~15s)."""


class MediaSliceError(RuntimeError):
    """Raised only for programming errors (invalid arguments); operational
    failures degrade to ``sliced=False`` with warnings instead."""


@dataclass
class MediaSliceResult:
    """Outcome of one slice attempt."""

    path: Path | None
    sliced: bool
    warnings: list[str] = field(default_factory=list)
    start_time: float = 0.0
    duration: float = 0.0


def _run(command: list[str], timeout: float) -> tuple[bool, str]:
    """Run a command; return (ok, stdout-on-success / stderr-on-failure)."""

    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)[:200]
    if completed.returncode != 0:
        return False, (completed.stderr or "")[:200]
    return True, completed.stdout or ""


def probe_media_duration(path: Path, ffprobe_path: str) -> float | None:
    """Duration of a media file (None when ffprobe cannot read it)."""

    import json

    ok, output = _run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            path.as_posix(),
        ],
        timeout=30,
    )
    if not ok:
        return None
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return None
    try:
        return float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        return None


def slice_media_to_window(
    source_path: str | Path,
    *,
    start_time: float,
    duration: float,
    output_dir: str | Path,
    workflow_id: str,
    kind: str = "video",
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
) -> MediaSliceResult:
    """Slice ``source_path`` to ``[start_time, start_time + duration)``.

    Args:
        source_path: The delivered reference (previs video, speech audio).
        start_time: Window start in seconds (>= 0).
        duration: Window length in seconds (> 0).
        output_dir: Where the slice is written (typically the workflow's
            media area under a ``slices`` subdirectory).
        workflow_id: Owner workflow (path scoping + naming).
        kind: "video" (frame-accurate re-encode) or "audio" (mp3 re-encode).

    Returns:
        MediaSliceResult. On any operational problem the result carries
        ``sliced=False`` plus warnings — the caller decides how to degrade.
    """

    if start_time < 0 or duration <= 0:
        raise MediaSliceError("slice window must satisfy start_time >= 0 and duration > 0")
    if duration > MAX_SLICE_SECONDS:
        duration = MAX_SLICE_SECONDS

    source = Path(source_path)
    if not source.is_file():
        return MediaSliceResult(
            path=None, sliced=False,
            warnings=[f"slice_source_missing: {source.name}"],
            start_time=start_time, duration=duration,
        )

    source_duration = probe_media_duration(source, ffprobe_path)
    warnings: list[str] = []
    effective_start = start_time
    effective_duration = duration
    if source_duration is not None:
        if source_duration <= start_time:
            return MediaSliceResult(
                path=None, sliced=False,
                warnings=[
                    f"slice_window_beyond_source: window starts at {start_time:.2f}s "
                    f"but the source is only {source_duration:.2f}s"
                ],
                start_time=start_time, duration=duration,
            )
        if start_time + duration > source_duration:
            effective_duration = source_duration - start_time
            warnings.append(
                f"slice_window_clamped: requested {duration:.2f}s at {start_time:.2f}s, "
                f"source has only {effective_duration:.2f}s left"
            )

    if effective_duration <= 0.05:
        return MediaSliceResult(
            path=None, sliced=False,
            warnings=warnings + ["slice_window_degenerate: effective duration ~0"],
            start_time=effective_start, duration=effective_duration,
        )

    output_dir = Path(output_dir) / "slices" / workflow_id
    output_dir.mkdir(parents=True, exist_ok=True)
    slice_id = f"slice_{uuid4().hex[:12]}"

    if kind == "audio":
        output_path = output_dir / f"{slice_id}.mp3"
        command = [
            ffmpeg_path, "-y",
            "-ss", f"{effective_start:.3f}",
            "-i", source.as_posix(),
            "-t", f"{effective_duration:.3f}",
            "-vn",
            "-c:a", "libmp3lame",
            "-q:a", "4",
            output_path.as_posix(),
        ]
    else:
        output_path = output_dir / f"{slice_id}.mp4"
        command = [
            ffmpeg_path, "-y",
            "-ss", f"{effective_start:.3f}",
            "-i", source.as_posix(),
            "-t", f"{effective_duration:.3f}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            output_path.as_posix(),
        ]

    ok, error = _run(command, timeout=120)
    if not ok or not output_path.is_file() or output_path.stat().st_size == 0:
        return MediaSliceResult(
            path=None, sliced=False,
            warnings=warnings + [f"slice_ffmpeg_failed: {error}"],
            start_time=effective_start, duration=effective_duration,
        )
    return MediaSliceResult(
        path=output_path,
        sliced=True,
        warnings=warnings,
        start_time=effective_start,
        duration=effective_duration,
    )
