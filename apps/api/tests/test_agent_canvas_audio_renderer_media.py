"""Real-FFmpeg acceptance tests for timeline audio mixing and auto-ducking.

Marked ``media``: generates sine/color lavfi sources and runs the production
renderer end to end, then measures band-isolated loudness to prove that BGM is
attenuated while voice is active and that clips land at their timeline offsets.
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
    EditingDuckingConfigV2,
    EditingOutputSettingsV2,
    EditingVideoEntryV2,
)
from app.services.agent_canvas_composition_renderer import AgentCanvasCompositionRenderer
from app.services.agent_canvas_editing import ResolvedEditingInputs, ResolvedEditingMedia
from app.services.v2_media_toolchain_capabilities import V2MediaToolchainCapabilityService

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


def _create_sources(data_dir: Path) -> tuple[Path, Path, Path]:
    video = data_dir / "video.mp4"
    voice = data_dir / "voice.wav"
    bgm = data_dir / "bgm.wav"
    _run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=navy:s=160x120:r=12:d=6",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=6",
            "-c:v", "mpeg4", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", video.as_posix(),
        ]
    )
    # The lavfi sine source emits at ~-18 dBFS by design; normalize to full scale
    # so ducking threshold/ratio semantics exercise the deep-gain-reduction path.
    _run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=2,volume=7.5",
            "-c:a", "pcm_s16le", voice.as_posix(),
        ]
    )
    _run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=6,volume=7.5",
            "-c:a", "pcm_s16le", bgm.as_posix(),
        ]
    )
    return video, voice, bgm


def _asset(asset_id: str, media_type: str) -> ProjectAssetSummaryV2:
    return ProjectAssetSummaryV2(
        asset_id=asset_id,
        media_type=media_type,
        source_type="generated",
        display_name=asset_id,
        mime_type="video/mp4" if media_type == "video" else "audio/wav",
        status="ready",
        checksum=f"sha256-{asset_id}",
    )


def _inputs(video: Path, voice: Path, bgm: Path, *, ducking_enabled: bool) -> ResolvedEditingInputs:
    return ResolvedEditingInputs(
        videos=(
            ResolvedEditingMedia(
                asset=_asset("v1", "video"),
                path=video,
                video_entry=EditingVideoEntryV2(asset_id="v1", timeline_start_seconds=0.0),
            ),
        ),
        bgm=None,
        audios=(
            ResolvedEditingMedia(
                asset=_asset("voice", "audio"),
                path=voice,
                audio_entry=EditingAudioEntryV2(
                    asset_id="voice",
                    role="voice",
                    timeline_start_seconds=2.0,
                    trim_end_seconds=2.0,
                    volume=1.0,
                ),
            ),
            ResolvedEditingMedia(
                asset=_asset("bgm", "audio"),
                path=bgm,
                audio_entry=EditingAudioEntryV2(
                    asset_id="bgm",
                    role="bgm",
                    timeline_start_seconds=0.0,
                    trim_end_seconds=6.0,
                    volume=0.8,
                ),
            ),
        ),
        skipped=(),
        timeline_duration_seconds=_TIMELINE_SECONDS,
        ducking=EditingDuckingConfigV2(enabled=ducking_enabled),
    )


# Cascaded 2-pole Butterworth sections for steep, predictable band isolation
# without the large passband insertion loss of a single narrow bandpass.
_BAND_ISOLATION = {
    220: "lowpass=f=300,lowpass=f=300,lowpass=f=300,volumedetect",
    880: "highpass=f=600,highpass=f=600,highpass=f=600,volumedetect",
}


def _band_mean_volume(path: Path, *, start: float, duration: float, frequency: int) -> float:
    completed = subprocess.run(
        [
            "ffmpeg", "-hide_banner",
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", path.as_posix(),
            "-map", "0:a",
            "-af", _BAND_ISOLATION[frequency],
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", completed.stderr)
    if match is None:
        raise RuntimeError(f"volumedetect produced no mean_volume: {completed.stderr[-800:]}")
    return float(match.group(1))


@pytest.fixture
def rendered_outputs(tmp_path: Path) -> tuple[Path, Path]:
    settings = Settings(agent_runtime_mode="fake", media_data_dir=tmp_path / "data")
    capabilities = V2MediaToolchainCapabilityService(settings).snapshot()
    if not capabilities.feature_flags.get("audio_ducking", False):
        pytest.skip("Configured FFmpeg lacks the sidechaincompress filter")

    video, voice, bgm = _create_sources(tmp_path)
    ducked_path = tmp_path / "ducked.mp4"
    static_path = tmp_path / "static.mp4"
    renderer = AgentCanvasCompositionRenderer(settings)
    ducked = renderer.render(
        _inputs(video, voice, bgm, ducking_enabled=True),
        EditingOutputSettingsV2(),
        staging_path=ducked_path,
    )
    static = renderer.render(
        _inputs(video, voice, bgm, ducking_enabled=False),
        EditingOutputSettingsV2(),
        staging_path=static_path,
    )
    assert ducked.degradations == ()
    assert static.degradations == ()
    return ducked_path, static_path


class TestRealFfmpegAudioDucking:
    def test_output_duration_matches_timeline(self, rendered_outputs: tuple[Path, Path]) -> None:
        ducked, _static = rendered_outputs
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", ducked.as_posix(),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert abs(float(probe.stdout.strip()) - _TIMELINE_SECONDS) < 0.2

    def test_bgm_is_ducked_while_voice_is_active(self, rendered_outputs: tuple[Path, Path]) -> None:
        ducked, _static = rendered_outputs
        clean = _band_mean_volume(ducked, start=0.75, duration=1.0, frequency=220)
        during_voice = _band_mean_volume(ducked, start=2.75, duration=1.0, frequency=220)

        assert clean > -12.0
        assert during_voice < clean - 10.0

    def test_bgm_level_stays_constant_without_ducking(
        self, rendered_outputs: tuple[Path, Path]
    ) -> None:
        _ducked, static = rendered_outputs
        clean = _band_mean_volume(static, start=0.75, duration=1.0, frequency=220)
        during_voice = _band_mean_volume(static, start=2.75, duration=1.0, frequency=220)

        assert abs(clean - during_voice) < 3.0

    def test_voice_clip_is_silenced_before_its_timeline_offset(
        self, rendered_outputs: tuple[Path, Path]
    ) -> None:
        ducked, _static = rendered_outputs
        before = _band_mean_volume(ducked, start=0.75, duration=1.0, frequency=880)
        during = _band_mean_volume(ducked, start=2.75, duration=1.0, frequency=880)

        assert before < -50.0
        assert during > -12.0
