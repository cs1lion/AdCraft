"""Real-FFmpeg acceptance test for clip volume envelopes (plan 3.4).

Marked ``media``: renders a sine tone with a 1 → 0 keyframed ramp through the
production renderer and samples the mean level of the head/middle/tail of the
export to prove the envelope expression attenuates the signal while the output
duration stays pinned to the timeline.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.schemas.agent_canvas import ProjectAssetSummaryV2
from app.schemas.agent_canvas_editing import (
    EditingAudioEntryV2,
    EditingOutputSettingsV2,
    EditingVideoEntryV2,
    EditingVolumeKeyframeV2,
)
from app.services.agent_canvas_composition_renderer import AgentCanvasCompositionRenderer
from app.services.agent_canvas_editing import ResolvedEditingInputs, ResolvedEditingMedia

pytestmark = [
    pytest.mark.media,
    pytest.mark.skipif(
        shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
        reason="ffmpeg/ffprobe not available for media tests",
    ),
]

_TIMELINE_SECONDS = 6.0


def _run(args: list[str]) -> None:
    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {completed.stderr[-800:]}")


def _video_asset() -> ProjectAssetSummaryV2:
    return ProjectAssetSummaryV2(
        asset_id="v1",
        media_type="video",
        source_type="generated",
        display_name="v1",
        mime_type="video/mp4",
        status="ready",
        checksum="sha256-v1",
    )


def _audio_asset() -> ProjectAssetSummaryV2:
    return ProjectAssetSummaryV2(
        asset_id="a1",
        media_type="audio",
        source_type="generated",
        display_name="a1",
        mime_type="audio/wav",
        status="ready",
        checksum="sha256-a1",
    )


def _rendered(
    tmp_path: Path,
    *,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    keyframes: tuple[EditingVolumeKeyframeV2, ...] | None = None,
) -> Path:
    if keyframes is None:
        keyframes = (
            EditingVolumeKeyframeV2(time_seconds=0.0, value=1.0),
            EditingVolumeKeyframeV2(time_seconds=6.0, value=0.0),
        )
    video = tmp_path / "silent.mp4"
    _run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=navy:s=160x120:r=12:d=7",
            "-c:v", "mpeg4", "-pix_fmt", "yuv420p", video.as_posix(),
        ]
    )
    tone = tmp_path / "tone.wav"
    _run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=7",
            "-c:a", "pcm_s16le", tone.as_posix(),
        ]
    )

    inputs = ResolvedEditingInputs(
        videos=(
            ResolvedEditingMedia(
                asset=_video_asset(),
                path=video,
                video_entry=EditingVideoEntryV2(
                    asset_id="v1",
                    timeline_start_seconds=0.0,
                    trim_end_seconds=_TIMELINE_SECONDS,
                ),
            ),
        ),
        audios=(
            ResolvedEditingMedia(
                asset=_audio_asset(),
                path=tone,
                audio_entry=EditingAudioEntryV2(
                    asset_id="a1",
                    role="voice",
                    timeline_start_seconds=0.0,
                    trim_end_seconds=_TIMELINE_SECONDS,
                    volume=1.0,
                    fade_in_seconds=fade_in,
                    fade_out_seconds=fade_out,
                    volume_keyframes=keyframes,
                ),
            ),
        ),
        bgm=None,
        skipped=(),
        timeline_duration_seconds=_TIMELINE_SECONDS,
    )

    settings = Settings(agent_runtime_mode="fake", media_data_dir=tmp_path / "data")
    output = tmp_path / "envelope.mp4"
    AgentCanvasCompositionRenderer(settings).render(
        inputs,
        EditingOutputSettingsV2(),
        staging_path=output,
    )
    return output


def _mean_gain_db(path: Path, start: float, end: float) -> float:
    """Mean volume of a time window.

    The window is trimmed *inside* ffmpeg (PTS-based ``atrim``) before a fresh
    volumedetect pass. A single full-file ``astats`` scan reports phantom
    smoothing across concat discontinuities, and output ``-ss`` seeks are
    unreliable for PCM on some Windows builds.
    """
    completed = subprocess.run(
        [
            "ffmpeg", "-hide_banner",
            "-i", path.as_posix(),
            "-af", f"atrim=start={start}:end={end},volumedetect",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", completed.stderr)
    assert match is not None, f"no mean_volume for [{start}, {end})"
    return float(match.group(1))


class TestRealFfmpegVolumeEnvelope:
    def test_ramp_fades_tone_down_over_clip_duration(self, tmp_path: Path) -> None:
        output = _rendered(tmp_path)

        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", output.as_posix(),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert abs(float(probe.stdout.strip()) - _TIMELINE_SECONDS) < 0.2

        # Average level per sampled window on the 0 -> 6 s ramp. The export
        # bus runs a final alimiter(0.95), so the full-scale sine reference
        # sits around -24 dB; expected gains ~= 0.94 / 0.48 / 0.06.
        head_db = _mean_gain_db(output, 0.0, 0.75)
        middle_db = _mean_gain_db(output, 2.75, 3.5)
        tail_db = _mean_gain_db(output, 5.25, 6.0)

        assert head_db > -25.0
        # Strictly decreasing levels down the ramp (allow small slack).
        assert head_db > middle_db + 4.0
        assert middle_db > tail_db + 10.0
        assert head_db - tail_db > 18.0

    def test_fade_in_and_fade_out_duck_only_the_edges(self, tmp_path: Path) -> None:
        # No keyframes; 1 s fades on both edges must be audible end-to-end.
        # (Earlier afade-based builds silently failed to move the level at all.)
        output = _rendered(
            tmp_path,
            fade_in=1.0,
            fade_out=1.0,
            keyframes=(),
        )

        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", output.as_posix(),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert abs(float(probe.stdout.strip()) - _TIMELINE_SECONDS) < 0.2

        head_db = _mean_gain_db(output, 0.0, 0.75)
        middle_db = _mean_gain_db(output, 2.75, 3.5)
        tail_db = _mean_gain_db(output, 5.25, 6.0)

        # Mean fade gain over the first/last 0.75 s of a 1 s fade is ~= 0.375.
        assert middle_db > -26.0
        assert head_db < middle_db - 6.0
        assert tail_db < middle_db - 6.0
        assert abs(head_db - tail_db) < 4.0
