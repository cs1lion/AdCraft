"""Slice delivered references to a video node's timeline window (ADR 0008 P1).

The timeline is the shot schedule: a video node's clip says "you are the
3.0s–5.0s shot". The references that node consumes (the 3D previs rehearsal
video, the speech audio) arrive as whole assets — without slicing, the model
receives a 9-second rehearsal film for a 2-second shot and the temporal
alignment the timeline exists to provide is lost.

This module performs the cut at the delivery boundary: given the node's
window, each delivered video/audio reference whose local source is longer
than the window is replaced by a frame-accurate slice (see
``timeline_media_slice``), carried to the provider as a data URL — the same
local-file representation the delivery layer already uses. Images are never
sliced (a single-frame reference has no window semantics).

Degradation is queryable, never silent (engineering standard §4):
- no window (the node has no timeline clip) → nothing is sliced, reported;
- a source already within the window → skipped, reported;
- a slice failure → the ORIGINAL reference is kept and the warning says the
  alignment is weaker, rather than silently sending the wrong length.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.schemas.seedance_inputs import SeedanceDeliveredMediaInputV1
from app.services.timeline_media_slice import (
    MediaSliceResult,
    slice_media_to_window,
)

SLICEABLE_MEDIA_TYPES = {"video", "audio"}
_MIME_BY_EXTENSION = {
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}


@dataclass
class WindowSlicingReport:
    """What happened to each reference under the window."""

    window: tuple[float, float] | None = None
    sliced: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": list(self.window) if self.window else None,
            "sliced": list(self.sliced),
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
        }


def _data_url(path: Path) -> str:
    import base64

    mime = _MIME_BY_EXTENSION.get(path.suffix.lower(), "application/octet-stream")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def slice_references_to_window(
    references: Sequence[SeedanceDeliveredMediaInputV1],
    *,
    window: tuple[float, float] | None,
    workflow_id: str,
    output_dir: Path,
    resolve_local_path: Callable[[str, str | None], Path | None],
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
    slice_media: Callable[..., MediaSliceResult] | None = None,
) -> tuple[list[SeedanceDeliveredMediaInputV1], WindowSlicingReport]:
    """Return (possibly rewritten references, report).

    The returned list has the same length and order as the input; only
    references whose slice succeeded are replaced.
    """

    # Resolved at call time (not as a default argument): a default-argument
    # binding would capture the real slicer at import and defeat injection.
    slicer = slice_media or slice_media_to_window
    report = WindowSlicingReport(window=window)
    if window is None:
        report.skipped.append(
            {"reason": "no_timeline_window", "binding_ids": [r.binding_id for r in references]}
        )
        return list(references), report

    start_time, duration = window
    rewritten: list[SeedanceDeliveredMediaInputV1] = []
    for reference in references:
        if reference.media_type not in SLICEABLE_MEDIA_TYPES:
            report.skipped.append(
                {"binding_id": reference.binding_id, "reason": "not_sliceable_media_type"}
            )
            rewritten.append(reference)
            continue

        source = resolve_local_path(reference.asset_id, reference.version_id)
        if source is None:
            report.skipped.append(
                {"binding_id": reference.binding_id, "reason": "source_unresolved"}
            )
            report.warnings.append(
                f"timeline_slice_source_unresolved: {reference.asset_id}"
            )
            rewritten.append(reference)
            continue

        result = slicer(
            source,
            start_time=start_time,
            duration=duration,
            output_dir=output_dir,
            workflow_id=workflow_id,
            kind=reference.media_type,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
        )
        if not result.sliced or result.path is None:
            report.skipped.append(
                {
                    "binding_id": reference.binding_id,
                    "reason": "slice_failed",
                    "warnings": result.warnings,
                }
            )
            report.warnings.extend(result.warnings)
            # Degrade honestly: keep the whole asset.
            rewritten.append(reference)
            continue

        report.sliced.append(
            {
                "binding_id": reference.binding_id,
                "asset_id": reference.asset_id,
                "window_start": start_time,
                "window_duration": result.duration,
            }
        )
        report.warnings.extend(result.warnings)
        rewritten.append(
            reference.model_copy(
                update={
                    "provider_input_type": (
                        "video_url" if reference.media_type == "video" else "audio_url"
                    ),
                    "provider_input_value": _data_url(result.path),
                    "byte_count": result.path.stat().st_size,
                }
            )
        )
    return rewritten, report
