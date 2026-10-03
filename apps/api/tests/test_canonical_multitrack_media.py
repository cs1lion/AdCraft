"""Real FFmpeg proof: canonical drawtext and voice-only BGM sidechain."""

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from app.schemas.workflow_v2 import WorkflowV2TimelineClip
from app.services.v2_final_composition_filters import (
    V2CompositionCanvas,
    V2ResolvedTimelineClip,
    build_audio_filter_graph,
    build_visual_filter_graph,
    validated_ducking_config,
)

from test_replica_direct_execute_render_media import render_env as canonical_env, payload as canonical_payload  # noqa: F401

pytestmark = pytest.mark.media


def run(*args):
    result = subprocess.run(args, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def test_real_bgm_is_ducked_by_delayed_voice(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg absent")
    clips = []
    for i, role in enumerate(("bgm", "voice")):
        clip = WorkflowV2TimelineClip(
            clip_id=role,
            track_id=role,
            clip_type="audio",
            start_time=0 if i == 0 else 2,
            duration=6 if i == 0 else 2,
            source_asset_id=role,
            source_version_id="v1",
            metadata={"audio_role": role},
            audio={"volume": 2 if role == "voice" else 1},
        )
        clips.append(V2ResolvedTimelineClip(i, clip, i, True, 6 if i == 0 else 2))
    powers = []
    for enabled in (False, True):
        graph = build_audio_filter_graph(
            clips, timeline_duration_seconds=6, audio_mode="full", ducking={"enabled": enabled}
        )
        path = tmp_path / f"{enabled}.wav"
        run(
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=2",
            "-filter_complex",
            graph.filter_complex,
            "-map",
            "[aout]",
            "-c:a",
            "pcm_s16le",
            str(path),
        )
        with wave.open(str(path)) as media:
            rate = media.getframerate()
            samples = (
                np.frombuffer(media.readframes(media.getnframes()), dtype="<i2").reshape(-1, 2)[
                    :, 0
                ]
                / 32768
            )

        def tone(start, end):
            data = samples[int(start * rate) : int(end * rate)]
            t = np.arange(len(data)) / rate
            return abs(np.mean(data * np.exp(-2j * np.pi * 220 * t)))

        powers.append((tone(0.5, 1.5), tone(2.8, 3.8), tone(4.8, 5.8)))
    assert 20 * np.log10(powers[1][1] / powers[0][1]) < -8
    assert abs(20 * np.log10(powers[1][0] / powers[0][0])) < 1
    assert abs(20 * np.log10(powers[1][2] / powers[0][2])) < 2


def test_real_subtitle_draws_only_in_visible_window(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    font = next(
        (
            p
            for p in (
                Path("C:/Windows/Fonts/arial.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            )
            if p.exists()
        ),
        None,
    )
    if not ffmpeg or not font:
        pytest.skip("FFmpeg/font absent")
    clip = WorkflowV2TimelineClip(
        clip_id="caption",
        track_id="sub",
        clip_type="subtitle",
        text="HELLO",
        start_time=1,
        duration=1,
    )
    graph = build_visual_filter_graph(
        [V2ResolvedTimelineClip(-1, clip, 1, False)],
        V2CompositionCanvas(320, 180, 24, 3, str(font).replace("\\", "/")),
    )
    raw = run(
        ffmpeg,
        "-loglevel",
        "error",
        "-filter_complex",
        graph.filter_complex,
        "-map",
        "[vout]",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    )
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 180, 320)
    assert frames[12].max() < 10
    assert frames[36].max() > 200
    assert frames[60].max() < 10


def test_renderer_burns_caption_and_skips_disabled_track_assets(request, tmp_path):
    renderer, workflow, item, slot, _settings = request.getfixturevalue("canonical_env")
    request_data, _plan = request.getfixturevalue("canonical_payload")
    timeline = request_data["canonical_timeline"]
    timeline["resolution"] = {"width": 320, "height": 180}
    timeline["tracks"].append(
        {"track_id": "hidden", "track_type": "audio", "order": 99, "enabled": False}
    )
    timeline["clips"].append(
        {
            "clip_id": "missing-hidden",
            "track_id": "hidden",
            "clip_type": "audio",
            "start_time": 0,
            "duration": 1,
            "source_asset_id": "missing",
            "source_version_id": "missing",
        }
    )
    result = renderer.render(workflow, item, slot, request_data)
    assert result.status == "completed", result.metadata
    raw = run(
        shutil.which("ffmpeg"),
        "-loglevel",
        "error",
        "-ss",
        "0.5",
        "-i",
        str(tmp_path / result.local_file_path),
        "-frames:v",
        "1",
        "-pix_fmt",
        "gray",
        "-f",
        "rawvideo",
        "-",
    )
    frame = np.frombuffer(raw, dtype=np.uint8)
    # Placeholder is dark: enabled subtitles must add bright glyph pixels.
    assert np.sum(frame > 200) > 20


@pytest.mark.parametrize(
    "key,value", [("threshold_db", float("nan")), ("ratio", 0), ("attack_ms", -1)]
)
def test_invalid_ducking_never_compiles(key, value):
    # Mutation locks numeric/range validation before interpolation into FFmpeg.
    with pytest.raises(ValueError):
        validated_ducking_config({"enabled": True, key: value})
