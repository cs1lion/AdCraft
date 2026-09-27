"""Concatenate and measure per-line speech takes (V0.2 §14.7 内容层/表演层).

A voice-cast take built ONE LINE AT A TIME is only useful if the lines can be
joined back into one take and if the join is measurable: "改一句就重新生成整
段" is the failure §14.7 warns about, and a splice nobody can measure cannot
re-compute the timing that follows it.

Both operations shell out to ffmpeg, so both are SEAMS: the executor takes
them as injected callables and tests answer with controlled fakes. A missing
ffmpeg is reported, never raised through the node's error plumbing (the
per-line files survive a failed join, so a retry does not re-pay for the
lines that already succeeded).
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ConcatResult:
    """One join: did it succeed, where is it, why not."""

    success: bool
    output_path: str | None = None
    error: str | None = None


def concat_audio_files(paths: list[str], output_path: str) -> ConcatResult:
    """Join audio files in order into one take.

    The concat demuxer with a re-encode: the lines come from one engine with
    one codec, but an encode (rather than a stream copy) is the honest choice
    anyway — it normalises the gaps between segments instead of trusting them
    to be uniform.
    """

    usable = [path for path in paths if path and os.path.isfile(path)]
    if not usable:
        return ConcatResult(success=False, error="没有可拼接的音频行。")
    if len(usable) != len(paths):
        return ConcatResult(success=False, error="有音频行缺失，拒绝拼接半个音轨。")

    list_path = f"{output_path}.txt"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    # Absolute, forward-slashed paths: the demuxer reads this file verbatim.
    with open(list_path, "w", encoding="utf-8") as handle:
        for path in usable:
            escaped = os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")
            handle.write(f"file '{escaped}'\n")

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_path,
        "-c:a",
        "libmp3lame",
        "-q:a",
        "4",
        output_path,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        return ConcatResult(success=False, error="ffmpeg not found on PATH")
    except subprocess.TimeoutExpired:
        return ConcatResult(success=False, error="ffmpeg concat timed out after 300s")
    finally:
        try:
            os.remove(list_path)
        except OSError:
            pass

    if result.returncode != 0:
        tail = (result.stderr or "")[-400:]
        return ConcatResult(
            success=False,
            error=f"ffmpeg concat exited with code {result.returncode}: {tail}",
        )
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        return ConcatResult(success=False, error="拼接结果为空。")
    return ConcatResult(success=True, output_path=output_path)


def probe_audio_duration_seconds(path: str) -> float | None:
    """Measure one audio file's duration in seconds (None when unmeasurable).

    Deliberately soft: a duration the caller cannot read is a number the
    manifest should omit, not a reason to fail the take. The per-line offsets
    downstream needs are computed from these, so a missing one shifts the
    rest — which is why the manifest records the probe's success, not a guess.
    """

    if not path or not os.path.isfile(path):
        return None
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None
    raw = (payload.get("format") or {}).get("duration")
    try:
        duration = float(raw)
    except (TypeError, ValueError):
        return None
    return duration if duration > 0 else None
