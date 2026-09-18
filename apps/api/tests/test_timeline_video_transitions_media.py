"""Real-FFmpeg acceptance test for video cross-clip transitions (plan 2.4/3.2).

Marked ``media``: renders solid-color sources with a 1 s xfade through the
production renderer and samples luma before/during/after the transition (and
on the tail padding) to prove the motion blend and the fixed timeline
duration. Runs for each manifest transition type (dissolve / wipe / slide),
plus a three-clip mixed chain.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.schemas.agent_canvas import ProjectAssetSummaryV2
from app.schemas.agent_canvas_editing import EditingOutputSettingsV2, EditingVideoEntryV2
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
_TRANSITION_SECONDS = 1.0


def _run(args: list[str]) -> None:
    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {completed.stderr[-800:]}")


def _solid_source(path: Path, color: str) -> None:
    # Video-only sources; the renderer synthesises silence pieces itself.
    _run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x120:r=12:d=3",
            "-c:v", "mpeg4", "-pix_fmt", "yuv420p", path.as_posix(),
        ]
    )


def _asset(asset_id: str) -> ProjectAssetSummaryV2:
    return ProjectAssetSummaryV2(
        asset_id=asset_id,
        media_type="video",
        source_type="generated",
        display_name=asset_id,
        mime_type="video/mp4",
        status="ready",
        checksum=f"sha256-{asset_id}",
    )


def _rendered(tmp_path: Path, transition: str = "dissolve") -> Path:
    navy = tmp_path / f"navy-{transition}.mp4"
    white = tmp_path / f"white-{transition}.mp4"
    _solid_source(navy, "navy")
    _solid_source(white, "white")

    inputs = ResolvedEditingInputs(
        videos=(
            ResolvedEditingMedia(
                asset=_asset("v1"),
                path=navy,
                video_entry=EditingVideoEntryV2(
                    asset_id="v1",
                    timeline_start_seconds=0.0,
                    trim_end_seconds=3.0,
                ),
            ),
            ResolvedEditingMedia(
                asset=_asset("v2"),
                path=white,
                video_entry=EditingVideoEntryV2(
                    asset_id="v2",
                    timeline_start_seconds=3.0,
                    trim_end_seconds=3.0,
                    transition=transition,  # type: ignore[arg-type]
                    transition_duration_seconds=_TRANSITION_SECONDS,
                ),
            ),
        ),
        bgm=None,
        audios=(),
        skipped=(),
        timeline_duration_seconds=_TIMELINE_SECONDS,
    )

    settings = Settings(agent_runtime_mode="fake", media_data_dir=tmp_path / "data")
    output = tmp_path / f"{transition}.mp4"
    AgentCanvasCompositionRenderer(settings).render(
        inputs,
        EditingOutputSettingsV2(),
        staging_path=output,
    )
    return output


def _luma(path: Path, at_seconds: float, *, fps: int = 12) -> float:
    """Average luma (YAVG) of the frame at ``at_seconds``.

    Frame-number selection is used instead of ``-ss`` because some Windows
    FFmpeg builds deliver the first decoded frame when post-input seeking is
    combined with signalstats metadata output.
    """
    frame_number = round(at_seconds * fps)
    completed = subprocess.run(
        [
            "ffmpeg", "-hide_banner",
            "-i", path.as_posix(),
            "-vf", f"select=eq(n\\,{frame_number}),signalstats,metadata=print",
            "-frames:v", "1",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"YAVG=([0-9.]+)", completed.stderr)
    if match is None:
        raise RuntimeError(f"signalstats produced no YAVG: {completed.stderr[-800:]}")
    return float(match.group(1))


class TestRealFfmpegCrossTransitions:
    @pytest.mark.parametrize("transition", ["dissolve", "wipe", "slide"])
    def test_output_duration_stays_pinned_to_timeline(
        self, tmp_path: Path, transition: str
    ) -> None:
        output = _rendered(tmp_path, transition)
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

    @pytest.mark.parametrize("transition", ["dissolve", "wipe", "slide"])
    def test_transition_blends_the_two_sources_and_pads_black_tail(
        self, tmp_path: Path, transition: str
    ) -> None:
        output = _rendered(tmp_path, transition)

        # Chain timeline after xfade: 0-2 navy, 2-3 blend, 3-5 white, 5-6 pad.
        navy_luma = _luma(output, 0.5)
        blend_luma = _luma(output, 2.5)
        white_luma = _luma(output, 4.0)
        pad_luma = _luma(output, 5.5)

        assert navy_luma < 60.0
        assert white_luma > 200.0
        # Mid-transition frame must be clearly brighter than navy but not yet
        # the full white frame (a dissolve alpha-blends; wipe/slide split the
        # frame between the two sources at the boundary).
        assert navy_luma + 40.0 < blend_luma < white_luma - 20.0
        # The transition shortens the chain by 1 s; tpad restores it as black.
        assert pad_luma < 40.0


_THREE_CLIP_TIMELINE_SECONDS = 9.0


def _three_clips_rendered(tmp_path: Path) -> Path:
    """Three back-to-back 3 s clips: navy, white, navy; dissolve then wipe."""
    sources = []
    for index, color in enumerate(("navy", "white", "navy"), start=1):
        path = tmp_path / f"clip-{index}.mp4"
        _solid_source(path, color)
        sources.append(path)

    inputs = ResolvedEditingInputs(
        videos=(
            ResolvedEditingMedia(
                asset=_asset("v1"),
                path=sources[0],
                video_entry=EditingVideoEntryV2(
                    asset_id="v1",
                    timeline_start_seconds=0.0,
                    trim_end_seconds=3.0,
                ),
            ),
            ResolvedEditingMedia(
                asset=_asset("v2"),
                path=sources[1],
                video_entry=EditingVideoEntryV2(
                    asset_id="v2",
                    timeline_start_seconds=3.0,
                    trim_end_seconds=3.0,
                    transition="dissolve",
                    transition_duration_seconds=1.0,
                ),
            ),
            ResolvedEditingMedia(
                asset=_asset("v3"),
                path=sources[2],
                video_entry=EditingVideoEntryV2(
                    asset_id="v3",
                    timeline_start_seconds=6.0,
                    trim_end_seconds=3.0,
                    transition="wipe",
                    transition_duration_seconds=1.0,
                ),
            ),
        ),
        bgm=None,
        audios=(),
        skipped=(),
        timeline_duration_seconds=_THREE_CLIP_TIMELINE_SECONDS,
    )

    settings = Settings(agent_runtime_mode="fake", media_data_dir=tmp_path / "data")
    output = tmp_path / "three-clips.mp4"
    AgentCanvasCompositionRenderer(settings).render(
        inputs,
        EditingOutputSettingsV2(),
        staging_path=output,
    )
    return output


class TestRealFfmpegThreeClipChain:
    def test_three_clips_export_with_two_transitions_and_pinned_duration(
        self, tmp_path: Path
    ) -> None:
        output = _three_clips_rendered(tmp_path)

        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", output.as_posix(),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert abs(float(probe.stdout.strip()) - _THREE_CLIP_TIMELINE_SECONDS) < 0.2

        # Chain: 0-2 navy, 2-3 dissolve→white, 3-4 full white, 4-5
        # wipe→navy, 5-7 navy; 7-9 is the black tpad tail.
        assert _luma(output, 0.5) < 60.0
        first_blend = _luma(output, 2.5)
        assert 60.0 < first_blend < 200.0
        assert _luma(output, 4.0) > 200.0
        second_blend = _luma(output, 4.5)
        assert 60.0 < second_blend < 200.0
        assert _luma(output, 5.5) < 60.0
        assert _luma(output, 8.0) < 40.0
