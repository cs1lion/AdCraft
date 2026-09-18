"""Filter-graph tests for video cross-dissolves (timeline plan 2.4).

These tests never invoke FFmpeg: a fake runner records argv and a fake probe
supplies media metadata. Assertions target the -filter_complex script the
production renderer builds for cut vs xfade boundaries.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.config import Settings
from app.schemas.agent_canvas import ProjectAssetSummaryV2
from app.schemas.agent_canvas_editing import (
    EditingOutputSettingsV2,
    EditingVideoEntryV2,
)
from app.schemas.workflow_v2 import V2MediaToolchainCapabilities
from app.services.agent_canvas_composition_renderer import AgentCanvasCompositionRenderer
from app.services.agent_canvas_editing import ResolvedEditingInputs, ResolvedEditingMedia
from app.services.v2_final_composition_renderer import V2MediaProbeResult

_FPS = 12.0


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


def _video(
    asset_id: str,
    *,
    start: float,
    duration: float,
    transition: str = "cut",
    transition_duration: float = 0.0,
) -> ResolvedEditingMedia:
    path = Path(f"{asset_id}.mp4")
    return ResolvedEditingMedia(
        asset=_asset(asset_id),
        path=path,
        # Sources without native audio: the renderer synthesises silence pieces.
        video_entry=EditingVideoEntryV2(
            asset_id=asset_id,
            timeline_start_seconds=start,
            trim_end_seconds=duration,
            transition=transition,  # type: ignore[arg-type]
            transition_duration_seconds=transition_duration,
        ),
    )


def _render(
    videos: tuple[ResolvedEditingMedia, ...],
    *,
    tmp_path: Path,
    timeline_duration: float,
) -> str:
    output = tmp_path / "final.mp4"

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake")
        return subprocess.CompletedProcess(command, 0, "", "")

    def probe(path: Path, _kind: str) -> V2MediaProbeResult:
        if path == output:
            return V2MediaProbeResult(
                path=path,
                media_type="video",
                width=64,
                height=64,
                fps=_FPS,
                duration_seconds=timeline_duration,
                has_audio=False,
            )
        # Source probe duration is derived from the clip start for these tests;
        # callers pass entries whose trim fits the fake 10 s source.
        return V2MediaProbeResult(
            path=path,
            media_type="video",
            width=64,
            height=64,
            fps=_FPS,
            duration_seconds=10.0,
            has_audio=False,
        )

    renderer = AgentCanvasCompositionRenderer(
        Settings(agent_runtime_mode="fake", media_data_dir=tmp_path / "data"),
        runner=runner,
        probe=probe,
        encoder="libx264",
        capability_snapshot=V2MediaToolchainCapabilities(
            status="ready",
            ffmpeg_fingerprint="ff",
            ffprobe_fingerprint="fp",
            selected_video_encoder="libx264",
            audio_encoder="aac",
            feature_flags={"visual_composition": True, "source_audio": True},
        ),
    )
    inputs = ResolvedEditingInputs(
        videos=videos,
        bgm=None,
        audios=(),
        skipped=(),
        timeline_duration_seconds=timeline_duration,
    )
    result = renderer.render(inputs, EditingOutputSettingsV2(), staging_path=output)
    command = list(result.ffmpeg_command)
    return command[command.index("-filter_complex") + 1]


class TestVideoChainGraph:
    def test_adjacent_clips_with_dissolve_emit_xfade(self, tmp_path: Path) -> None:
        script = _render(
            (
                _video("v1", start=0.0, duration=2.0),
                _video(
                    "v2",
                    start=2.0,
                    duration=2.0,
                    transition="dissolve",
                    transition_duration=1.0,
                ),
            ),
            tmp_path=tmp_path,
            timeline_duration=4.0,
        )

        # 2 s chain - 1 s dissolve: offset lands at 1.0 s on the first stream.
        assert "xfade=transition=fade:duration=1.000000:offset=1.000000[vx1]" in script
        # Audio pieces are concatenated independently and stay timeline-length.
        assert "concat=n=2:v=0:a=1[acat]" in script
        # The shortened video chain is padded back to the fixed timeline length.
        assert "[vx1]tpad=stop_mode=add:stop_duration=4.000000" in script
        # No legacy av-interleaved concat label survives.
        assert "[vcat]" not in script

    def test_cut_boundaries_use_video_only_concat(self, tmp_path: Path) -> None:
        script = _render(
            (
                _video("v1", start=0.0, duration=2.0),
                _video("v2", start=3.0, duration=2.0),
                _video("v3", start=5.0, duration=1.0),
            ),
            tmp_path=tmp_path,
            timeline_duration=6.0,
        )

        # Pieces: clip (0-2), black gap (2-3), clip (3-5), clip (5-6): 3 joins.
        assert "[v0][vgap1]concat=n=2:v=1:a=0[vc1]" in script
        assert "xfade" not in script
        assert script.count("concat=n=2:v=1:a=0") == 3
        assert "concat=n=4:v=0:a=1[acat]" in script

    def test_dissolve_duration_is_frame_quantised_and_capped(self, tmp_path: Path) -> None:
        script = _render(
            (
                _video("v1", start=0.0, duration=2.0),
                _video(
                    "v2",
                    start=2.0,
                    duration=2.0,
                    transition="dissolve",
                    transition_duration=2.0,
                ),
            ),
            tmp_path=tmp_path,
            timeline_duration=4.0,
        )

        # Capped to a frame short of each clip: 23/12 s, offset = 2 - 23/12.
        assert "duration=1.916667:offset=0.083333" in script

    def test_single_clip_feeds_tpad_directly(self, tmp_path: Path) -> None:
        script = _render(
            (_video("v1", start=0.0, duration=3.0),),
            tmp_path=tmp_path,
            timeline_duration=3.0,
        )

        assert "xfade" not in script
        assert "[v0]tpad=stop_mode=add:stop_duration=3.000000" in script
        assert "concat=n=1:v=0:a=1[acat]" in script

    def test_dissolve_after_a_black_gap_fades_in_from_black(self, tmp_path: Path) -> None:
        # A dissolve whose previous chain piece is a black gap renders as a
        # fade-in from black; the offset is measured on the running chain
        # (2 s clip + 1 s gap = 3 s), so 3 - 0.5 = 2.5 s.
        script = _render(
            (
                _video("v1", start=0.0, duration=2.0),
                _video(
                    "v2",
                    start=3.0,
                    duration=2.0,
                    transition="dissolve",
                    transition_duration=0.5,
                ),
            ),
            tmp_path=tmp_path,
            timeline_duration=5.0,
        )

        # First join is clip→black gap (cut); second is gap→clip (xfade).
        assert "[v0][vgap1]concat=n=2:v=1:a=0[vc1]" in script
        assert (
            "[vc1][v2]xfade=transition=fade:duration=0.500000:offset=2.500000[vx2]"
            in script
        )
