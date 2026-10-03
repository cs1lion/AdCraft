"""Previs clip media cuts: per-shot trim and keyframe extraction (ADR 0017).

The scene-3d node publishes one full-scene animatic; the previs clip node is
the per-shot cut of that animatic. Both operations are real ffmpeg runs --
a trim that silently returned the whole scene, or keyframes that missed the
action, would poison the downstream video reference and nobody could tell
from the bytes.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TrimResult:
    success: bool
    output_path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class Keyframe:
    offset_seconds: float
    png_bytes: bytes


def trim_previs_clip(
    source_path: str | Path,
    output_path: str | Path,
    *,
    start_seconds: float,
    end_seconds: float,
) -> TrimResult:
    """Cut ``[start_seconds, end_seconds)`` out of an animatic, re-encoding.

    Re-encode (not ``-c copy``) because cut points must land on the shot
    boundary: stream copy snaps to the nearest keyframe, which for a low-fps
    animatic can be seconds away -- the clip would open on the previous
    shot's tail. Audio is re-encoded to AAC alongside so a muxed dialogue bed
    survives the cut in sync.
    """

    duration = end_seconds - start_seconds
    if duration <= 0:
        return TrimResult(success=False, error=f"Non-positive clip duration: {duration:.3f}s")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_seconds:.3f}",
        "-i", str(source_path),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(output),
    ]
    return _run_ffmpeg(cmd, output, "previs clip trim")


def extract_keyframes(
    clip_path: str | Path,
    *,
    duration_seconds: float,
    count: int = 5,
) -> list[Keyframe]:
    """Sample ``count`` stills at even offsets across the clip (0%..100%).

    Offsets are clamped inside the clip: the 100% sample sits a frame before
    the end because ``-ss`` at exactly the duration yields no frames.
    """

    if duration_seconds <= 0:
        return []
    # 100ms safety margin: -ss is seeked against container timestamps, and a
    # seek within rounding distance of the last frame yields no frames at all.
    last_safe = max(duration_seconds - 0.1, 0.0)
    offsets = [
        min(duration_seconds * index / (count - 1), last_safe) for index in range(count)
    ]
    keyframes: list[Keyframe] = []
    with tempfile.TemporaryDirectory(prefix="previs_kf_") as tmp_dir:
        for index, offset in enumerate(offsets):
            out_path = Path(tmp_dir) / f"keyframe_{index}.jpg"
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{offset:.3f}",
                "-i", str(clip_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(out_path),
            ]
            result = _run_ffmpeg(cmd, out_path, f"previs keyframe {index}")
            if not result.success or result.output_path is None:
                continue
            keyframes.append(
                Keyframe(
                    offset_seconds=round(offset, 3),
                    png_bytes=Path(result.output_path).read_bytes(),
                )
            )
    return keyframes


def _run_ffmpeg(cmd: list[str], output_path: Path, label: str) -> TrimResult:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        return TrimResult(success=False, error="ffmpeg not found on PATH")
    except subprocess.TimeoutExpired:
        return TrimResult(success=False, error=f"{label} timed out after 300s")
    if result.returncode != 0:
        error_tail = (result.stderr or "")[-500:]
        return TrimResult(
            success=False,
            error=f"ffmpeg exited with code {result.returncode} ({label}): {error_tail}",
        )
    if not output_path.is_file():
        return TrimResult(success=False, error=f"{label} produced no file")
    return TrimResult(success=True, output_path=str(output_path))
