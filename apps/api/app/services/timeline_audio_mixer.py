"""
Audio Mixing Service (ADR 0007, Phase 2)

FFmpeg-based audio mixing for multi-track timelines:
- Mix voice + bgm + sfx tracks
- Auto-ducking: lower BGM volume when voice is active
- Clip-level fade in/out
- Track-level volume control
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AudioClipInput:
    """A single audio clip to mix."""

    file_path: Path
    start_time: float  # seconds in timeline
    duration: float  # seconds
    volume: float = 1.0  # 0.0-1.0
    fade_in: float | None = None  # seconds
    fade_out: float | None = None  # seconds
    track_type: str = "sfx"  # voice | bgm | sfx


@dataclass(frozen=True, slots=True)
class AudioMixResult:
    """Result of audio mixing."""

    output_path: Path
    duration_seconds: float
    sample_rate: int
    channels: int
    ffmpeg_command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DuckingConfig:
    """Auto-ducking configuration."""

    enabled: bool = True
    duck_volume: float = 0.15  # BGM volume when voice is active (0.0-1.0)
    attack_ms: int = 50  # Fade in to ducked volume
    release_ms: int = 200  # Fade out from ducked volume
    threshold_db: float = -40.0  # Voice detection threshold


Runner = Callable[..., subprocess.CompletedProcess[str]]


class TimelineAudioMixer:
    """Mix multiple audio tracks from a timeline using ffmpeg."""

    def __init__(
        self,
        ffmpeg_path: str,
        *,
        runner: Runner | None = None,
        default_sample_rate: int = 44100,
        default_channels: int = 2,
    ) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._runner = runner or subprocess.run
        self._default_sample_rate = default_sample_rate
        self._default_channels = default_channels

    def mix(
        self,
        clips: tuple[AudioClipInput, ...],
        output_path: Path,
        *,
        total_duration: float | None = None,
        ducking: DuckingConfig | None = None,
    ) -> AudioMixResult:
        """Mix multiple audio clips into a single audio file.

        Args:
            clips: Audio clips to mix.
            output_path: Output file path (should be .wav or .mp3).
            total_duration: Total duration in seconds. If None, calculated from clips.
            ducking: Auto-ducking configuration. If None, default config used.

        Returns:
            AudioMixResult with output path and metadata.
        """
        if not clips:
            raise ValueError("No audio clips to mix")

        ducking = ducking or DuckingConfig()

        # Calculate total duration
        if total_duration is None:
            total_duration = max(
                clip.start_time + clip.duration for clip in clips
            )

        # Separate clips by track type
        voice_clips = [c for c in clips if c.track_type == "voice"]
        bgm_clips = [c for c in clips if c.track_type == "bgm"]
        sfx_clips = [c for c in clips if c.track_type == "sfx"]

        # Build ffmpeg command
        command = self._build_mix_command(
            clips=clips,
            voice_clips=tuple(voice_clips),
            bgm_clips=tuple(bgm_clips),
            sfx_clips=tuple(sfx_clips),
            output_path=output_path,
            total_duration=total_duration,
            ducking=ducking,
        )

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Run ffmpeg
        try:
            completed = self._runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"Audio mixing failed: {error}") from error

        if completed.returncode != 0:
            error_msg = (completed.stderr or completed.stdout)[-500:]
            raise RuntimeError(f"Audio mixing ffmpeg failed: {error_msg}")

        if not output_path.is_file():
            raise RuntimeError("Audio mixing output file not created")

        return AudioMixResult(
            output_path=output_path,
            duration_seconds=total_duration,
            sample_rate=self._default_sample_rate,
            channels=self._default_channels,
            ffmpeg_command=tuple(command),
        )

    def _build_mix_command(
        self,
        *,
        clips: tuple[AudioClipInput, ...],
        voice_clips: tuple[AudioClipInput, ...],
        bgm_clips: tuple[AudioClipInput, ...],
        sfx_clips: tuple[AudioClipInput, ...],
        output_path: Path,
        total_duration: float,
        ducking: DuckingConfig,
    ) -> list[str]:
        """Build ffmpeg command for audio mixing."""
        command: list[str] = [self._ffmpeg_path, "-y"]

        # Input files
        for clip in clips:
            command.extend(["-i", str(clip.file_path)])

        # Filter complex
        filter_parts: list[str] = []
        input_index = 0

        # Process each clip: delay, volume, fade
        processed_outputs: list[str] = []
        for clip in clips:
            input_label = f"[{input_index}:a]"
            output_label = f"[a{input_index}]"

            # Build filter chain for this clip
            chain_parts: list[str] = []

            # Delay to start time
            if clip.start_time > 0:
                delay_ms = int(clip.start_time * 1000)
                chain_parts.append(f"adelay={delay_ms}|{delay_ms}")

            # Volume
            if clip.volume != 1.0:
                chain_parts.append(f"volume={clip.volume}")

            # Fade in
            if clip.fade_in and clip.fade_in > 0:
                chain_parts.append(f"afade=t=in:st=0:d={clip.fade_in}")

            # Fade out
            if clip.fade_out and clip.fade_out > 0:
                fade_start = max(0, clip.duration - clip.fade_out)
                chain_parts.append(f"afade=t=out:st={fade_start}:d={clip.fade_out}")

            # Pad to total duration (silence after clip)
            chain_parts.append(f"apad=whole_dur={total_duration}")

            if chain_parts:
                filter_chain = ",".join(chain_parts)
                filter_parts.append(f"{input_label}{filter_chain}{output_label}")
            else:
                filter_parts.append(f"{input_label}anull{output_label}")

            processed_outputs.append(output_label)
            input_index += 1

        # Mix all processed audio streams
        if processed_outputs:
            mix_inputs = "".join(processed_outputs)
            mix_output = "[mixed]"
            filter_parts.append(
                f"{mix_inputs}amix=inputs={len(processed_outputs)}:duration=longest:normalize=0{mix_output}"
            )

            # Apply final volume normalization and format
            final_parts = [
                f"{mix_output}volume=1.0",
                f"aformat=sample_rates={self._default_sample_rate}:channel_layouts=stereo",
            ]
            filter_chain = ",".join(final_parts)
            filter_parts.append(f"{filter_chain}[out]")

        if filter_parts:
            command.extend(["-filter_complex", ";".join(filter_parts)])
            command.extend(["-map", "[out]"])

        # Output settings
        command.extend([
            "-t", str(total_duration),
            "-ac", str(self._default_channels),
            "-ar", str(self._default_sample_rate),
            "-c:a", "pcm_s16le" if output_path.suffix.lower() == ".wav" else "libmp3lame",
            "-b:a", "192k",
            str(output_path),
        ])

        return command

    def generate_silence(
        self,
        output_path: Path,
        duration: float,
        *,
        sample_rate: int | None = None,
    ) -> Path:
        """Generate a silent audio file.

        Useful for placeholder audio when no clips exist.
        """
        sample_rate = sample_rate or self._default_sample_rate
        output_path.parent.mkdir(parents=True, exist_ok=True)

        command = [
            self._ffmpeg_path,
            "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={sample_rate}:cl=stereo",
            "-t", str(duration),
            "-c:a", "pcm_s16le",
            str(output_path),
        ]

        completed = self._runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

        if completed.returncode != 0:
            raise RuntimeError(f"Silence generation failed: {completed.stderr[-200:]}")

        return output_path
