"""FFmpeg renderer for ordered Agent Canvas Editing inputs."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
import subprocess

from app.core.config import Settings
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas_editing import (
    EditingAudioEntryV2,
    EditingBgmEntryV2,
    EditingOutputSettingsV2,
    EditingVideoEntryV2,
)
from app.services.agent_canvas_editing import ResolvedEditingInputs, ResolvedEditingMedia
from app.services.agent_canvas_editing_timeline import TIMELINE_EPSILON
from app.services.timeline_subtitle_writer import SubtitleCue, cues_to_ass
from app.services.v2_final_composition_renderer import (
    V2MediaProbe,
    V2MediaProbeResult,
)
from app.services.v2_media_toolchain_capabilities import (
    V2MediaToolchainCapabilities,
    V2MediaToolchainCapabilityService,
)


Runner = Callable[..., subprocess.CompletedProcess[str]]
Probe = Callable[[Path, str], V2MediaProbeResult]

# Observable degradation markers surfaced on EditingRenderResult and export events.
DEGRADATION_DUCKING_UNAVAILABLE = "audio_ducking_unavailable"
DEGRADATION_SUBTITLE_BURN_UNAVAILABLE = "subtitle_burn_in_unavailable"


@dataclass(frozen=True, slots=True)
class EditingRenderResult:
    output_path: Path
    width: int
    height: int
    duration_seconds: float
    ffmpeg_command: tuple[str, ...]
    video_encoder: str
    degradations: tuple[str, ...] = ()


class AgentCanvasCompositionRenderer:
    """Normalize ordered clips, preserve native audio, and mix timeline audio."""

    def __init__(
        self,
        settings: Settings,
        *,
        runner: Runner | None = None,
        probe: Probe | None = None,
        encoder: str | None = None,
        capability_snapshot: V2MediaToolchainCapabilities | None = None,
    ) -> None:
        self._settings = settings
        self._runner = runner or subprocess.run
        self._probe = probe or V2MediaProbe(ffprobe_path=settings.ffprobe_path)
        self._encoder = encoder
        self._capability_snapshot = capability_snapshot

    def render(
        self,
        inputs: ResolvedEditingInputs,
        output: EditingOutputSettingsV2,
        *,
        staging_path: Path,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> EditingRenderResult:
        probes = tuple(self._require_video(item.path) for item in inputs.videos)
        width, height = _output_geometry(output, probes[0])
        fps = output.fps or probes[0].fps or 30.0
        encoder = self._encoder or self._configured_encoder()
        timeline_duration = _timeline_duration(inputs, probes)
        if cancelled():
            raise _error("editing_export_cancelled", "Editing Export was cancelled.")
        staging_path.parent.mkdir(parents=True, exist_ok=True)
        subtitle_ass_path, subtitle_degradations = self._prepare_subtitles(inputs, staging_path)
        command, degradations = self._command(
            inputs,
            probes,
            width=width,
            height=height,
            fps=fps,
            encoder=encoder,
            timeline_duration=timeline_duration,
            staging_path=staging_path,
            subtitle_ass_path=subtitle_ass_path,
        )
        degradations = (*subtitle_degradations, *degradations)
        try:
            completed = self._runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=3600,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise _error(
                "editing_ffmpeg_failed",
                "Editing Export could not run the configured FFmpeg toolchain.",
            ) from error
        if completed.returncode != 0:
            raise _error(
                "editing_ffmpeg_failed",
                _safe_ffmpeg_error(completed.stderr or completed.stdout),
            )
        if cancelled():
            staging_path.unlink(missing_ok=True)
            raise _error("editing_export_cancelled", "Editing Export was cancelled.")
        rendered = self._probe(staging_path, "video")
        if (
            rendered.error
            or rendered.width != width
            or rendered.height != height
            or not staging_path.is_file()
            or not _duration_matches(rendered.duration_seconds, timeline_duration)
        ):
            raise _error(
                "editing_output_invalid",
                "Editing Export output failed media validation.",
            )
        return EditingRenderResult(
            output_path=staging_path,
            width=width,
            height=height,
            duration_seconds=rendered.duration_seconds or timeline_duration,
            ffmpeg_command=tuple(command),
            video_encoder=encoder,
            degradations=degradations,
        )

    def recover(
        self,
        inputs: ResolvedEditingInputs,
        output: EditingOutputSettingsV2,
        *,
        staging_path: Path,
    ) -> EditingRenderResult:
        """Validate and reuse a completed staging file after process restart."""

        first = self._require_video(inputs.videos[0].path)
        width, height = _output_geometry(output, first)
        timeline_duration = _timeline_duration(
            inputs,
            tuple(self._require_video(item.path) for item in inputs.videos),
        )
        rendered = self._probe(staging_path, "video")
        if (
            rendered.error
            or rendered.width != width
            or rendered.height != height
            or not staging_path.is_file()
            or not _duration_matches(rendered.duration_seconds, timeline_duration)
        ):
            raise _error(
                "editing_output_invalid",
                "Recovered Editing output failed media validation.",
            )
        return EditingRenderResult(
            output_path=staging_path,
            width=width,
            height=height,
            duration_seconds=rendered.duration_seconds or timeline_duration,
            ffmpeg_command=(),
            video_encoder=self._encoder or self._configured_encoder(),
        )

    def fingerprint_payload(self) -> dict[str, object]:
        """Return non-secret renderer identity used by export idempotency."""

        snapshot = V2MediaToolchainCapabilityService(self._settings).snapshot()
        return {
            "contract": "agent-canvas-composition-renderer-v2",
            "ffmpeg_fingerprint": snapshot.ffmpeg_fingerprint,
            "ffprobe_fingerprint": snapshot.ffprobe_fingerprint,
            "video_encoder": self._encoder or snapshot.selected_video_encoder,
            "audio_encoder": snapshot.audio_encoder,
        }

    def _command(
        self,
        inputs: ResolvedEditingInputs,
        probes: tuple[V2MediaProbeResult, ...],
        *,
        width: int,
        height: int,
        fps: float,
        encoder: str,
        timeline_duration: float,
        staging_path: Path,
        subtitle_ass_path: Path | None = None,
    ) -> tuple[list[str], tuple[str, ...]]:
        command = [self._settings.ffmpeg_path, "-y"]
        for item in inputs.videos:
            command.extend(["-i", item.path.as_posix()])
        for item in inputs.audios:
            command.extend(["-i", item.path.as_posix()])
        if inputs.bgm is not None:
            command.extend(["-stream_loop", "-1", "-i", inputs.bgm.path.as_posix()])
        filters: list[str] = []
        audio_concat_labels: list[str] = []
        # (video label, piece duration, owning entry; None for black gap pieces)
        video_pieces: list[tuple[str, float, EditingVideoEntryV2 | None]] = []
        render_items = sorted(
            zip(range(len(inputs.videos)), inputs.videos, probes, strict=True),
            key=lambda item: (
                _video_entry(item[1]).timeline_start_seconds
                if _video_entry(item[1]).timeline_start_seconds is not None
                else 0.0,
                _video_entry(item[1]).source_key,
                item[0],
            ),
        )
        cursor = 0.0
        piece_index = 0
        for input_index, media, probe in render_items:
            entry = _video_entry(media)
            duration = _effective_duration(entry, probe)
            start = entry.timeline_start_seconds
            if start is None:
                start = cursor
            if start < cursor - TIMELINE_EPSILON:
                raise _error(
                    "editing_timeline_overlap",
                    "Editing video inputs overlap on the fixed timeline.",
                )
            if start > cursor + TIMELINE_EPSILON:
                gap_duration = start - cursor
                filters.extend(
                    _gap_filters(
                        piece_index,
                        gap_duration,
                        width=width,
                        height=height,
                        fps=fps,
                    )
                )
                audio_concat_labels.append(f"[agap{piece_index}]")
                video_pieces.append(
                    (f"[vgap{piece_index}]", gap_duration, None)
                )
                piece_index += 1
            trim = _trim_filter(
                entry.trim_start_seconds,
                entry.trim_end_seconds,
            )
            geometry = _geometry_filter(entry.fit_mode, width=width, height=height)
            # Ordering matters for xfade inputs: settle the timebase and reset
            # timestamps before the fps filter so the link advertises CFR
            # (xfade rejects inputs whose frame rate reports as 1/0).
            video_filters = [
                trim,
                geometry,
                "setsar=1",
                "settb=AVTB",
                "setpts=PTS-STARTPTS",
                f"fps={fps:.6f}",
                "format=yuv420p",
            ]
            if entry.transition == "fade" and entry.transition_duration_seconds > 0:
                fade_start = max(duration - entry.transition_duration_seconds, 0.0)
                video_filters.append(
                    f"fade=t=out:st={fade_start:.6f}:d={entry.transition_duration_seconds:.6f}"
                )
            filters.append(f"[{input_index}:v:0]" + ",".join(video_filters) + f"[v{piece_index}]")
            if probe.has_audio and entry.preserve_native_audio:
                audio_filters = [
                    _trim_filter(
                        entry.trim_start_seconds,
                        entry.trim_end_seconds,
                        audio=True,
                    ),
                    f"volume={entry.volume:.6f}",
                ]
                if entry.transition == "fade" and entry.transition_duration_seconds > 0:
                    fade_start = max(duration - entry.transition_duration_seconds, 0.0)
                    audio_filters.append(
                        f"afade=t=out:st={fade_start:.6f}:d={entry.transition_duration_seconds:.6f}"
                    )
                audio_filters.extend(
                    (
                        "aresample=48000",
                        "aformat=sample_fmts=fltp:channel_layouts=stereo",
                        "asetpts=PTS-STARTPTS",
                    )
                )
                filters.append(
                    f"[{input_index}:a:0]" + ",".join(audio_filters) + f"[a{piece_index}]"
                )
            else:
                filters.append(
                    "anullsrc=r=48000:cl=stereo,"
                    f"atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[a{piece_index}]"
                )
            audio_concat_labels.append(f"[a{piece_index}]")
            video_pieces.append((f"[v{piece_index}]", duration, entry))
            piece_index += 1
            cursor = start + duration
            if cursor > timeline_duration + TIMELINE_EPSILON:
                raise _error(
                    "editing_timeline_out_of_bounds",
                    "Editing video inputs exceed the fixed timeline duration.",
                )
        if cursor < timeline_duration - TIMELINE_EPSILON:
            gap_duration = timeline_duration - cursor
            filters.extend(
                _gap_filters(
                    piece_index,
                    gap_duration,
                    width=width,
                    height=height,
                    fps=fps,
                )
            )
            audio_concat_labels.append(f"[agap{piece_index}]")
            video_pieces.append(
                (f"[vgap{piece_index}]", gap_duration, None)
            )
            piece_index += 1
        filters.append(
            "".join(audio_concat_labels)
            + f"concat=n={len(audio_concat_labels)}:v=0:a=1[acat]"
        )
        chain_filters, video_chain_label = _video_chain_filters(
            video_pieces,
            fps=fps,
        )
        filters.extend(chain_filters)
        audio_filters, audio_label, degradations = self._audio_mix_filters(
            inputs,
            timeline_duration,
        )
        filters.extend(audio_filters)
        video_chain = (
            f"{video_chain_label}tpad=stop_mode=add:stop_duration={timeline_duration:.6f},"
            f"trim=duration={timeline_duration:.6f},setpts=PTS-STARTPTS"
        )
        if subtitle_ass_path is not None:
            video_chain += f",{_ass_filter(subtitle_ass_path, settings=self._settings)}"
        filters.append(video_chain + "[vout]")
        filters.append(
            f"{audio_label}apad=pad_dur={timeline_duration:.6f},"
            f"atrim=duration={timeline_duration:.6f},asetpts=PTS-STARTPTS[aout]"
        )
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                encoder,
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                staging_path.as_posix(),
            ]
        )
        return command, degradations

    def _audio_mix_filters(
        self,
        inputs: ResolvedEditingInputs,
        timeline_duration: float,
    ) -> tuple[list[str], str, tuple[str, ...]]:
        """Build the timeline-positioned multi-role audio graph.

        Voice clips drive a sidechain bus that ducks BGM; SFX and voice are
        mixed at full scale (normalize=0). Every clip is delayed to its
        timeline position and padded to the fixed timeline duration.
        """

        filters: list[str] = []
        degradations: list[str] = []
        video_count = len(inputs.videos)

        voice_labels: list[str] = []
        sfx_labels: list[str] = []
        bgm_labels: list[str] = []

        for index, media in enumerate(inputs.audios):
            entry = _audio_entry(media)
            input_index = video_count + index
            label = f"[ad{index}]"
            filters.append(
                f"[{input_index}:a:0]"
                + ",".join(
                    _timeline_audio_chain(
                        entry,
                        start_seconds=entry.timeline_start_seconds,
                        timeline_duration=timeline_duration,
                    )
                )
                + label
            )
            if entry.role == "voice":
                voice_labels.append(label)
            elif entry.role == "sfx":
                sfx_labels.append(label)
            else:
                bgm_labels.append(label)

        if inputs.bgm is not None:
            bgm_entry = _bgm_entry(inputs.bgm)
            bgm_input_index = video_count + len(inputs.audios)
            filters.append(
                f"[{bgm_input_index}:a:0]"
                + ",".join(
                    _timeline_audio_chain(
                        bgm_entry,
                        start_seconds=0.0,
                        timeline_duration=timeline_duration,
                    )
                )
                + "[bgmlegacy]"
            )
            bgm_labels.append("[bgmlegacy]")

        voice_bus = _mix_bus(filters, voice_labels, "voicebus")
        sfx_bus = _mix_bus(filters, sfx_labels, "sfxbus")
        bgm_bus = _mix_bus(filters, bgm_labels, "bgmbase")

        voice_mix_label = voice_bus
        if (
            voice_bus is not None
            and bgm_bus is not None
            and inputs.ducking is not None
            and inputs.ducking.enabled
        ):
            if self._audio_ducking_supported():
                ducking = inputs.ducking
                # One sidechain copy drives the compressor; the other stays audible.
                filters.append(f"{voice_bus}asplit=2[voice_sc][voice_mix]")
                voice_mix_label = "[voice_mix]"
                filters.append(
                    f"{bgm_bus}[voice_sc]sidechaincompress="
                    f"threshold={_db_to_linear(ducking.threshold_db):.6f}:"
                    f"ratio={ducking.ratio:.6f}:"
                    f"attack={ducking.attack_ms}:release={ducking.release_ms}:"
                    f"makeup={_db_to_linear(ducking.makeup_gain_db):.6f}[bgmducked]"
                )
                bgm_bus = "[bgmducked]"
            else:
                # Observable fallback: static-volume mix without auto-ducking.
                degradations.append(DEGRADATION_DUCKING_UNAVAILABLE)

        final_inputs = ["[acat]"]
        if voice_mix_label is not None:
            final_inputs.append(voice_mix_label)
        if sfx_bus is not None:
            final_inputs.append(sfx_bus)
        if bgm_bus is not None:
            final_inputs.append(bgm_bus)

        if len(final_inputs) == 1:
            return filters, "[acat]", tuple(degradations)
        filters.append(
            "".join(final_inputs)
            + f"amix=inputs={len(final_inputs)}:duration=first:"
            "dropout_transition=0:normalize=0,alimiter=limit=0.95[amixed]"
        )
        return filters, "[amixed]", tuple(degradations)

    def _require_video(self, path: Path) -> V2MediaProbeResult:
        result = self._probe(path, "video")
        if result.error or not result.width or not result.height:
            raise _error(
                "editing_source_media_invalid",
                "An Editing video input failed media validation.",
            )
        return result

    def _configured_encoder(self) -> str:
        capabilities = self._capabilities()
        if (
            not capabilities.selected_video_encoder
            or not capabilities.feature_flags.get("visual_composition", False)
            or not capabilities.feature_flags.get("source_audio", False)
        ):
            raise _error(
                "editing_ffmpeg_unsupported",
                "Required Editing FFmpeg capabilities are unavailable.",
            )
        return capabilities.selected_video_encoder

    def _capabilities(self) -> V2MediaToolchainCapabilities:
        if self._capability_snapshot is not None:
            return self._capability_snapshot
        return V2MediaToolchainCapabilityService(self._settings).snapshot()

    def _audio_ducking_supported(self) -> bool:
        return bool(self._capabilities().feature_flags.get("audio_ducking", False))

    def _subtitle_burn_supported(self) -> bool:
        return bool(self._capabilities().feature_flags.get("subtitle_burn_in", False))

    def _prepare_subtitles(
        self,
        inputs: ResolvedEditingInputs,
        staging_path: Path,
    ) -> tuple[Path | None, tuple[str, ...]]:
        """Stage the ASS sidecar when burn-in is requested and renderable.

        Returns the ASS path for the ``ass`` filter plus an observable
        degradation marker when cues exist but the toolchain cannot burn them.
        """
        if not inputs.subtitle_burn_in or not inputs.subtitles:
            return None, ()
        if not self._subtitle_burn_supported():
            return None, (DEGRADATION_SUBTITLE_BURN_UNAVAILABLE,)
        ass_path = staging_path.parent / "subtitles.ass"
        cues = tuple(
            SubtitleCue(
                text=entry.text,
                start_seconds=entry.start_seconds,
                end_seconds=entry.end_seconds,
                style=entry.style,
            )
            for entry in inputs.subtitles
        )
        ass_path.write_text(cues_to_ass(cues), encoding="utf-8")
        return ass_path, ()


def _video_entry(media: ResolvedEditingMedia) -> EditingVideoEntryV2:
    if media.video_entry is not None:
        return media.video_entry
    if media.binding_id is not None:
        return EditingVideoEntryV2(binding_id=media.binding_id)
    return EditingVideoEntryV2(asset_id=media.asset.asset_id)


def _bgm_entry(media: ResolvedEditingMedia) -> EditingBgmEntryV2:
    if media.bgm_entry is not None:
        return media.bgm_entry
    if media.binding_id is not None:
        return EditingBgmEntryV2(binding_id=media.binding_id)
    return EditingBgmEntryV2(asset_id=media.asset.asset_id)


def _audio_entry(media: ResolvedEditingMedia) -> EditingAudioEntryV2:
    if media.audio_entry is not None:
        return media.audio_entry
    if media.binding_id is not None:
        return EditingAudioEntryV2(binding_id=media.binding_id, role="voice")
    return EditingAudioEntryV2(asset_id=media.asset.asset_id, role="voice")


def _timeline_audio_chain(
    entry: EditingAudioEntryV2 | EditingBgmEntryV2,
    *,
    start_seconds: float,
    timeline_duration: float,
) -> list[str]:
    """Trim/level/fade one audio source, place it, and pad to timeline length."""

    chain = [_trim_filter(entry.trim_start_seconds, entry.trim_end_seconds, audio=True)]
    chain.append(f"volume={entry.volume:.6f}")
    if entry.trim_end_seconds is not None:
        clip_duration = entry.trim_end_seconds - entry.trim_start_seconds
    else:
        # Looped legacy BGM is expected to cover the rest of the timeline.
        clip_duration = max(timeline_duration - entry.trim_start_seconds, 0.0)
    if entry.fade_in_seconds > 0:
        chain.append(f"afade=t=in:st=0:d={entry.fade_in_seconds:.6f}")
    if entry.fade_out_seconds > 0 and clip_duration > 0:
        fade_start = max(clip_duration - entry.fade_out_seconds, 0.0)
        chain.append(f"afade=t=out:st={fade_start:.6f}:d={entry.fade_out_seconds:.6f}")
    chain.extend(
        (
            "aresample=48000",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
            f"adelay={max(0, round(start_seconds * 1000))}:all=1",
            f"apad=whole_dur={timeline_duration:.6f}",
            f"atrim=duration={timeline_duration:.6f}",
            "asetpts=PTS-STARTPTS",
        )
    )
    return chain


def _mix_bus(filters: list[str], labels: list[str], name: str) -> str | None:
    """Combine same-role clips into one fixed-length bus (passthrough if one)."""

    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    filters.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0[{name}]"
    )
    return f"[{name}]"


def _db_to_linear(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _effective_duration(
    entry: EditingVideoEntryV2,
    probe: V2MediaProbeResult,
) -> float:
    if (
        probe.duration_seconds is not None
        and entry.trim_start_seconds >= probe.duration_seconds - TIMELINE_EPSILON
    ):
        raise _error(
            "editing_timeline_duration_invalid",
            "Editing trim start exceeds the source media duration.",
        )
    end = entry.trim_end_seconds
    if end is None:
        end = probe.duration_seconds or entry.trim_start_seconds + 0.001
    if probe.duration_seconds is not None and end > probe.duration_seconds + TIMELINE_EPSILON:
        raise _error(
            "editing_timeline_duration_invalid",
            "Editing trim end exceeds the source media duration.",
        )
    return max(end - entry.trim_start_seconds, 0.001)


def _timeline_duration(
    inputs: ResolvedEditingInputs,
    probes: tuple[V2MediaProbeResult, ...],
) -> float:
    if inputs.timeline_duration_seconds is not None:
        if inputs.timeline_duration_seconds <= TIMELINE_EPSILON:
            raise _error(
                "editing_timeline_duration_invalid",
                "Editing timeline duration must be positive.",
            )
        return inputs.timeline_duration_seconds
    return sum(probe.duration_seconds or 0.0 for probe in probes)


def _duration_matches(actual: float | None, expected: float) -> bool:
    return actual is not None and abs(actual - expected) <= max(0.05, expected * 0.02)


def _gap_filters(
    index: int,
    duration: float,
    *,
    width: int,
    height: int,
    fps: float,
) -> tuple[str, str]:
    return (
        f"color=c=black:s={width}x{height}:r={fps:.6f}:d={duration:.6f},"
        f"setsar=1,settb=AVTB,setpts=PTS-STARTPTS,fps={fps:.6f},"
        f"format=yuv420p[vgap{index}]",
        f"anullsrc=r=48000:cl=stereo,atrim=duration={duration:.6f},"
        f"asetpts=PTS-STARTPTS[agap{index}]",
    )


# Manifest transition types → libavfilter xfade transition names. Dissolve
# renders as a cross-fade; wipe/slide use the canonical left-to-right motion.
_XFADE_FILTER_NAMES: dict[str, str] = {
    "dissolve": "fade",
    "wipe": "wipeleft",
    "slide": "slideleft",
}


def _video_chain_filters(
    pieces: Sequence[tuple[str, float, EditingVideoEntryV2 | None]],
    *,
    fps: float,
) -> tuple[list[str], str]:
    """Join normalized video pieces with cuts or cross-clip transitions.

    Cut boundaries use a video-only concat; transition boundaries (marked on
    the *incoming* piece) chain ``xfade`` — dissolve cross-fades, wipe and
    slide move the boundary across the frame. Transitions overlap the two
    pieces and shorten the chain, so durations are tracked cumulatively to
    compute each xfade offset. The fixed-length audio graph (and the final
    tpad/trim) keeps the exported timeline duration intact.
    """
    if not pieces:
        raise _error(
            "editing_timeline_duration_invalid",
            "No video pieces were produced for the composition.",
        )

    frame = 1.0 / fps
    filters: list[str] = []
    label, current_duration, _ = pieces[0]

    for step, (next_label, piece_duration, entry) in enumerate(pieces[1:], start=1):
        xfade_name = (
            _XFADE_FILTER_NAMES[entry.transition]
            if entry is not None and entry.transition in _XFADE_FILTER_NAMES
            else None
        )
        requested = entry.transition_duration_seconds if xfade_name is not None else 0.0
        overlap_duration = 0.0
        if requested > 0.0:
            capped = min(
                requested,
                current_duration - frame,
                piece_duration - frame,
            )
            quantized = math.floor(capped * fps + 1e-9) / fps
            if quantized >= frame - 1e-9:
                overlap_duration = quantized

        if overlap_duration > 0.0 and xfade_name is not None:
            offset = current_duration - overlap_duration
            output = f"[vx{step}]"
            filters.append(
                f"{label}{next_label}xfade=transition={xfade_name}:"
                f"duration={overlap_duration:.6f}:offset={offset:.6f}{output}"
            )
            label = output
            current_duration += piece_duration - overlap_duration
        else:
            output = f"[vc{step}]"
            filters.append(
                f"{label}{next_label}concat=n=2:v=1:a=0{output}"
            )
            label = output
            current_duration += piece_duration

    return filters, label


def _trim_filter(
    start: float,
    end: float | None,
    *,
    audio: bool = False,
) -> str:
    name = "atrim" if audio else "trim"
    result = f"{name}=start={start:.6f}"
    if end is not None:
        result += f":end={end:.6f}"
    return result


def _geometry_filter(mode: str, *, width: int, height: int) -> str:
    if mode == "fit":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2"
    )


def _output_geometry(
    settings: EditingOutputSettingsV2,
    first: V2MediaProbeResult,
) -> tuple[int, int]:
    if settings.resolution:
        try:
            width_text, height_text = settings.resolution.lower().split("x", 1)
            width, height = int(width_text), int(height_text)
        except (TypeError, ValueError) as error:
            raise _error(
                "editing_output_geometry_invalid",
                "Editing output resolution must use WIDTHxHEIGHT.",
            ) from error
    else:
        width, height = first.width or 0, first.height or 0
    if width < 2 or height < 2:
        raise _error(
            "editing_output_geometry_invalid",
            "Editing output geometry is invalid.",
        )
    return width - (width % 2), height - (height % 2)


def _safe_ffmpeg_error(value: str) -> str:
    line = next((line.strip() for line in value.splitlines() if line.strip()), "")
    return f"Editing FFmpeg failed: {line[:300]}" if line else "Editing FFmpeg failed."


def _escape_filter_path(path: Path) -> str:
    """Escape a filesystem path for use inside a filtergraph argument."""
    return path.resolve().as_posix().replace("\\", "\\\\").replace(":", "\\:")


def _ass_filter(path: Path, *, settings: Settings) -> str:
    """Build the libass ``ass`` filter, exposing the configured font dir."""
    result = f"ass={_escape_filter_path(path)}"
    if settings.final_composition_subtitle_font_path:
        fonts_dir = Path(settings.final_composition_subtitle_font_path).expanduser().parent
        result += f":fontsdir={_escape_filter_path(fonts_dir)}"
    return result


def _error(code: str, message: str) -> V2PersistenceError:
    return V2PersistenceError(code, message, stage="agent_canvas_composition_renderer")
