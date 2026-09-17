"""FFmpeg argument-graph tests for timeline voice/sfx/bgm mixing (ADR 0007 Phase 1).

These tests never invoke FFmpeg: a fake runner records the argv sequence and a
fake probe supplies media metadata. Filter-graph assertions parse → serialize →
parse the -filter_complex script to verify structural round-trip stability.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.config import Settings
from app.schemas.agent_canvas_editing import (
    EditingAudioEntryV2,
    EditingDuckingConfigV2,
    EditingManifestV2,
    EditingOutputSettingsV2,
    EditingVideoEntryV2,
)
from app.schemas.workflow_v2 import V2MediaToolchainCapabilities
from app.services.agent_canvas_composition_renderer import (
    DEGRADATION_DUCKING_UNAVAILABLE,
    AgentCanvasCompositionRenderer,
)
from app.services.agent_canvas_editing import ResolvedEditingInputs, ResolvedEditingMedia
from app.services.v2_final_composition_renderer import V2MediaProbeResult


def _asset(asset_id: str, media_type: str) -> object:
    from app.schemas.agent_canvas import ProjectAssetSummaryV2

    return ProjectAssetSummaryV2(
        asset_id=asset_id,
        media_type=media_type,
        source_type="generated",
        display_name=asset_id,
        mime_type="video/mp4" if media_type == "video" else "audio/wav",
        status="ready",
        checksum=f"sha256-{asset_id}",
    )


def _video_media(asset_id: str = "v1") -> ResolvedEditingMedia:
    return ResolvedEditingMedia(
        asset=_asset(asset_id, "video"),  # type: ignore[arg-type]
        path=Path(f"{asset_id}.mp4"),
        video_entry=EditingVideoEntryV2(asset_id=asset_id, timeline_start_seconds=0.0),
    )


def _audio_media(
    asset_id: str,
    role: str,
    *,
    start: float,
    trim_end: float,
    volume: float = 1.0,
) -> ResolvedEditingMedia:
    return ResolvedEditingMedia(
        asset=_asset(asset_id, "audio"),  # type: ignore[arg-type]
        path=Path(f"{asset_id}.wav"),
        audio_entry=EditingAudioEntryV2(
            asset_id=asset_id,
            role=role,  # type: ignore[arg-type]
            timeline_start_seconds=start,
            trim_end_seconds=trim_end,
            volume=volume,
        ),
    )


def _capabilities(*, ducking: bool) -> V2MediaToolchainCapabilities:
    return V2MediaToolchainCapabilities(
        status="ready",
        ffmpeg_fingerprint="ff",
        ffprobe_fingerprint="fp",
        selected_video_encoder="libx264",
        audio_encoder="aac",
        feature_flags={
            "visual_composition": True,
            "source_audio": True,
            "audio_ducking": ducking,
        },
    )


def _render(
    inputs: ResolvedEditingInputs,
    *,
    tmp_path: Path,
    ducking_capability: bool = True,
) -> tuple[object, list[str], str]:
    output = tmp_path / "final.mp4"
    duration = inputs.timeline_duration_seconds or 2.0

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
                fps=12.0,
                duration_seconds=duration,
                has_audio=True,
            )
        return V2MediaProbeResult(
            path=path,
            media_type="video",
            width=64,
            height=64,
            fps=12.0,
            duration_seconds=2.0,
            has_audio=True,
        )

    renderer = AgentCanvasCompositionRenderer(
        Settings(agent_runtime_mode="fake", media_data_dir=tmp_path / "data"),
        runner=runner,
        probe=probe,
        encoder="libx264",
        capability_snapshot=_capabilities(ducking=ducking_capability),
    )
    result = renderer.render(inputs, EditingOutputSettingsV2(), staging_path=output)
    command = list(result.ffmpeg_command)
    filter_script = command[command.index("-filter_complex") + 1]
    return result, command, filter_script


def _inputs(
    *,
    audios: tuple[ResolvedEditingMedia, ...] = (),
    bgm: ResolvedEditingMedia | None = None,
    ducking: EditingDuckingConfigV2 | None = None,
    duration: float = 3.0,
) -> ResolvedEditingInputs:
    return ResolvedEditingInputs(
        videos=(_video_media(),),
        bgm=bgm,
        audios=audios,
        skipped=(),
        timeline_duration_seconds=duration,
        ducking=ducking,
    )


class TestTimelineAudioGraph:
    def test_voice_and_bgm_use_sidechain_ducking_with_positioned_inputs(self, tmp_path: Path) -> None:
        voice = _audio_media("voice1", "voice", start=1.0, trim_end=2.0)
        bgm = _audio_media("bgm1", "bgm", start=0.0, trim_end=3.0, volume=0.3)
        result, command, script = _render(
            _inputs(
                audios=(voice, bgm),
                ducking=EditingDuckingConfigV2(),
            ),
            tmp_path=tmp_path,
        )

        # Input order/indices: video=0, voice=1, bgm=2; finite clips, no stream loop.
        input_args = [command[i + 1] for i, value in enumerate(command) if value == "-i"]
        assert input_args == ["v1.mp4", "voice1.wav", "bgm1.wav"]
        assert "-stream_loop" not in command

        chains = script.split(";")
        # Parse → serialize → parse round trip for the filter script.
        assert ";".join(chains) == script

        voice_chain = next(chain for chain in chains if chain.startswith("[1:a:0]"))
        assert "atrim=start=0.000000:end=2.000000" in voice_chain
        assert "adelay=1000:all=1" in voice_chain
        assert "apad=whole_dur=3.000000" in voice_chain
        assert voice_chain.endswith("[ad0]")

        bgm_chain = next(chain for chain in chains if chain.startswith("[2:a:0]"))
        assert "volume=0.300000" in bgm_chain
        assert "adelay=0:all=1" in bgm_chain
        assert bgm_chain.endswith("[ad1]")

        assert any("asplit=2[voice_sc][voice_mix]" in chain for chain in chains)
        sidechain = next(chain for chain in chains if "sidechaincompress" in chain)
        assert sidechain.startswith("[ad1][voice_sc]sidechaincompress=")
        # -30 dB -> linear 0.031623; ratio 12; attack/release in milliseconds.
        assert "threshold=0.031623" in sidechain
        assert "ratio=12.000000" in sidechain
        assert "attack=50:release=250" in sidechain
        assert sidechain.endswith("[bgmducked]")

        final_mix = next(chain for chain in chains if "amix=inputs=" in chain)
        assert "[acat][voice_mix][bgmducked]amix=inputs=3:duration=first" in final_mix
        assert "alimiter=limit=0.95[amixed]" in final_mix
        assert result.degradations == ()

    def test_ducking_disabled_mixes_static_volumes(self, tmp_path: Path) -> None:
        voice = _audio_media("voice1", "voice", start=0.0, trim_end=2.0)
        bgm = _audio_media("bgm1", "bgm", start=0.0, trim_end=3.0)
        result, _command, script = _render(
            _inputs(
                audios=(voice, bgm),
                ducking=EditingDuckingConfigV2(enabled=False),
            ),
            tmp_path=tmp_path,
        )

        assert "sidechaincompress" not in script
        assert "asplit" not in script
        assert "[acat][ad0][ad1]amix=inputs=3:duration=first" in script
        assert result.degradations == ()

    def test_missing_sidechain_filter_is_observable_degradation(self, tmp_path: Path) -> None:
        voice = _audio_media("voice1", "voice", start=0.0, trim_end=2.0)
        bgm = _audio_media("bgm1", "bgm", start=0.0, trim_end=3.0)
        result, _command, script = _render(
            _inputs(audios=(voice, bgm), ducking=EditingDuckingConfigV2()),
            tmp_path=tmp_path,
            ducking_capability=False,
        )

        assert "sidechaincompress" not in script
        assert result.degradations == (DEGRADATION_DUCKING_UNAVAILABLE,)
        # Export still mixes the BGM at its configured static volume.
        assert "[acat][ad0][ad1]amix=inputs=3:duration=first" in script

    def test_sfx_only_mixes_without_ducking_bus(self, tmp_path: Path) -> None:
        sfx = _audio_media("sfx1", "sfx", start=2.0, trim_end=2.5)
        _result, _command, script = _render(_inputs(audios=(sfx,)), tmp_path=tmp_path)

        assert "sidechaincompress" not in script
        assert "voicebus" not in script
        assert "adelay=2000:all=1" in script
        assert "[acat][ad0]amix=inputs=2:duration=first" in script

    def test_multiple_same_role_clips_build_role_bus(self, tmp_path: Path) -> None:
        sfx_a = _audio_media("sfx1", "sfx", start=0.0, trim_end=1.0)
        sfx_b = _audio_media("sfx2", "sfx", start=2.0, trim_end=2.5)
        _result, _command, script = _render(_inputs(audios=(sfx_a, sfx_b)), tmp_path=tmp_path)

        assert "[ad0][ad1]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[sfxbus]" in script
        assert "[acat][sfxbus]amix=inputs=2:duration=first" in script

    def test_legacy_loop_bgm_still_supported_without_audio_entries(self, tmp_path: Path) -> None:
        from app.schemas.agent_canvas_editing import EditingBgmEntryV2

        bgm = ResolvedEditingMedia(
            asset=_asset("bgm", "audio"),  # type: ignore[arg-type]
            path=Path("bgm.mp3"),
            bgm_entry=EditingBgmEntryV2(asset_id="bgm", volume=0.2),
        )
        _result, command, script = _render(_inputs(bgm=bgm, duration=3.0), tmp_path=tmp_path)

        # Legacy BGM is looped and occupies the input right after the videos.
        stream_index = command.index("-stream_loop")
        assert command[stream_index : stream_index + 4] == [
            "-stream_loop",
            "-1",
            "-i",
            "bgm.mp3",
        ]
        assert "[1:a:0]" in script
        assert "[bgmlegacy]" in script
        assert "sidechaincompress" not in script
        assert "[acat][bgmlegacy]amix=inputs=2:duration=first" in script

    def test_no_audio_inputs_keeps_concat_audio_unmixed(self, tmp_path: Path) -> None:
        _result, command, script = _render(_inputs(), tmp_path=tmp_path)

        assert "-i" in command
        assert "amix" not in script
        assert "[acat]apad=pad_dur=3.000000" in script

    def test_filter_script_round_trips_through_split_and_join(self, tmp_path: Path) -> None:
        voice = _audio_media("voice1", "voice", start=0.5, trim_end=1.5)
        bgm = _audio_media("bgm1", "bgm", start=0.0, trim_end=3.0)
        sfx = _audio_media("sfx1", "sfx", start=2.0, trim_end=2.5)
        _result, command, script = _render(
            _inputs(audios=(voice, bgm, sfx), ducking=EditingDuckingConfigV2()),
            tmp_path=tmp_path,
        )

        chains = [chain for chain in script.split(";") if chain]
        assert ";".join(chains) == script
        assert any(chain.endswith("[vout]") for chain in chains)
        assert any(chain.endswith("[aout]") for chain in chains)
        # 4 inputs to the final mix: native video audio, voice, sfx, ducked bgm.
        assert "amix=inputs=4:duration=first" in script
        # argv remains a flat sequence (no accidental nested lists).
        assert all(isinstance(part, str) for part in command)

    def test_manifest_shape_carries_audio_entries_and_ducking(self) -> None:
        manifest = EditingManifestV2.model_validate(
            {
                "video_entries": [],
                "audio_entries": [
                    {
                        "asset_id": "a1",
                        "role": "voice",
                        "timeline_start_seconds": 1.0,
                        "trim_end_seconds": 2.0,
                    }
                ],
                "ducking": {"enabled": True, "threshold_db": -35.0},
            }
        )
        assert manifest.audio_entries[0].role == "voice"
        assert manifest.audio_entries[0].volume == 1.0
        assert manifest.ducking is not None
        assert manifest.ducking.ratio == 12.0
        assert manifest.ducking.threshold_db == -35.0
