"""FFmpeg filter-graph tests for ASS subtitle burn-in (ADR 0007 Phase 3.3).

FFmpeg is never invoked: a fake runner records argv and a fake probe supplies
media metadata. These tests verify the ``ass`` filter wiring, the staged ASS
sidecar, and the observable degradation when libass is unavailable.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.config import Settings
from app.schemas.agent_canvas_editing import (
    EditingOutputSettingsV2,
    EditingSubtitleEntryV2,
    EditingVideoEntryV2,
)
from app.schemas.timeline import TimelineSubtitleStyleV1
from app.schemas.workflow_v2 import V2MediaToolchainCapabilities
from app.services.agent_canvas_composition_renderer import (
    DEGRADATION_SUBTITLE_BURN_UNAVAILABLE,
    AgentCanvasCompositionRenderer,
)
from app.services.agent_canvas_editing import ResolvedEditingInputs, ResolvedEditingMedia
from app.services.v2_final_composition_renderer import V2MediaProbeResult


def _video_media() -> ResolvedEditingMedia:
    from app.schemas.agent_canvas import ProjectAssetSummaryV2

    return ResolvedEditingMedia(
        asset=ProjectAssetSummaryV2(
            asset_id="v1",
            media_type="video",
            source_type="generated",
            display_name="v1",
            mime_type="video/mp4",
            status="ready",
            checksum="sha256-v1",
        ),
        path=Path("v1.mp4"),
        video_entry=EditingVideoEntryV2(asset_id="v1", timeline_start_seconds=0.0),
    )


def _cue(
    text: str = "Hello subtitles",
    *,
    start: float = 0.5,
    end: float = 1.5,
    style: TimelineSubtitleStyleV1 | None = None,
) -> EditingSubtitleEntryV2:
    return EditingSubtitleEntryV2(
        start_seconds=start,
        end_seconds=end,
        text=text,
        style=style,
    )


def _capabilities(*, burn_in: bool) -> V2MediaToolchainCapabilities:
    return V2MediaToolchainCapabilities(
        status="ready",
        ffmpeg_fingerprint="ff",
        ffprobe_fingerprint="fp",
        selected_video_encoder="libx264",
        audio_encoder="aac",
        feature_flags={
            "visual_composition": True,
            "source_audio": True,
            "audio_ducking": True,
            "subtitle_burn_in": burn_in,
        },
    )


def _render(
    inputs: ResolvedEditingInputs,
    *,
    tmp_path: Path,
    burn_in_capability: bool = True,
    font_path: Path | None = None,
) -> tuple[object, list[str], str, Path]:
    output = tmp_path / "staging" / "final.mp4"
    duration = inputs.timeline_duration_seconds or 2.0

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake")
        return subprocess.CompletedProcess(command, 0, "", "")

    def probe(path: Path, _kind: str) -> V2MediaProbeResult:
        if path == output:
            probed_duration = duration
        else:
            probed_duration = 2.0
        return V2MediaProbeResult(
            path=path,
            media_type="video",
            width=64,
            height=64,
            fps=12.0,
            duration_seconds=probed_duration,
            has_audio=True,
        )

    settings = Settings(
        agent_runtime_mode="fake",
        media_data_dir=tmp_path / "data",
        final_composition_subtitle_font_path=str(font_path) if font_path else None,
    )
    renderer = AgentCanvasCompositionRenderer(
        settings,
        runner=runner,
        probe=probe,
        encoder="libx264",
        capability_snapshot=_capabilities(burn_in=burn_in_capability),
    )
    result = renderer.render(inputs, EditingOutputSettingsV2(), staging_path=output)
    command = list(result.ffmpeg_command)
    filter_script = command[command.index("-filter_complex") + 1]
    return result, command, filter_script, output


def _inputs(
    *,
    subtitles: tuple[EditingSubtitleEntryV2, ...] = (),
    burn_in: bool = True,
) -> ResolvedEditingInputs:
    return ResolvedEditingInputs(
        videos=(_video_media(),),
        bgm=None,
        skipped=(),
        timeline_duration_seconds=2.0,
        subtitles=subtitles,
        subtitle_burn_in=burn_in,
    )


class TestSubtitleBurnIn:
    def test_cues_stage_ass_sidecar_and_mount_ass_filter(self, tmp_path: Path) -> None:
        result, _command, script, output = _render(
            _inputs(subtitles=(_cue(), _cue("Second", start=1.5, end=2.0))),
            tmp_path=tmp_path,
        )

        vout_chain = next(chain for chain in script.split(";") if chain.endswith("[vout]"))
        assert "ass=" in vout_chain
        # The burn filter runs after the final timestamp reset.
        assert "setpts=PTS-STARTPTS,ass=" in vout_chain
        assert result.degradations == ()

        ass_path = output.parent / "subtitles.ass"
        assert ass_path.is_file()
        document = ass_path.read_text(encoding="utf-8")
        assert "[Script Info]" in document
        assert "Hello subtitles" in document
        assert "Second" in document

    def test_styled_cues_emit_per_cue_ass_styles(self, tmp_path: Path) -> None:
        style = TimelineSubtitleStyleV1(
            font_family="Verdana",
            font_size=48,
            primary_color="#ff0000",
            position="top",
            bold=True,
        )
        _result, _command, _script, output = _render(
            _inputs(subtitles=(_cue("Styled", style=style),)),
            tmp_path=tmp_path,
        )

        document = (output.parent / "subtitles.ass").read_text(encoding="utf-8")
        assert "Style: Subtitle1,Verdana,48," in document
        # #ff0000 -> ASS &H000000FF; top alignment is numpad 8.
        assert "&H000000FF" in document
        assert ",8,40,40,60,1" in document

    def test_configured_font_dir_is_passed_to_ass_filter(self, tmp_path: Path) -> None:
        font_dir = tmp_path / "fonts"
        font_dir.mkdir()
        font_file = font_dir / "Arial.ttf"
        font_file.write_bytes(b"fake-font")
        _result, _command, script, _output = _render(
            _inputs(subtitles=(_cue(),)),
            tmp_path=tmp_path,
            font_path=font_file,
        )

        vout_chain = next(chain for chain in script.split(";") if chain.endswith("[vout]"))
        assert ":fontsdir=" in vout_chain
        assert "fonts" in vout_chain

    def test_missing_libass_is_observable_degradation_without_filter(self, tmp_path: Path) -> None:
        result, _command, script, output = _render(
            _inputs(subtitles=(_cue(),)),
            tmp_path=tmp_path,
            burn_in_capability=False,
        )

        assert "ass=" not in script
        assert result.degradations == (DEGRADATION_SUBTITLE_BURN_UNAVAILABLE,)
        assert not (output.parent / "subtitles.ass").exists()

    def test_burn_in_disabled_skips_filter_silently(self, tmp_path: Path) -> None:
        result, _command, script, output = _render(
            _inputs(subtitles=(_cue(),), burn_in=False),
            tmp_path=tmp_path,
        )

        assert "ass=" not in script
        assert result.degradations == ()
        assert not (output.parent / "subtitles.ass").exists()

    def test_no_cues_skips_filter_silently(self, tmp_path: Path) -> None:
        result, _command, script, output = _render(_inputs(), tmp_path=tmp_path)

        assert "ass=" not in script
        assert result.degradations == ()
        assert not (output.parent / "subtitles.ass").exists()
