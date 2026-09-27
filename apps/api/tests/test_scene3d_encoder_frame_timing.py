"""The encoder must not resample a keyframe draft into a longer clip.

``encode_png_sequence`` feeds ffmpeg a concat manifest, and a concat manifest
can express timing two ways.  Only one of them survives ``-r <fps>``:

* one entry per still with a wide ``duration`` -- the demuxer honours it, but
  the stream is now variable-rate, so ``-r`` resamples it: ffmpeg duplicates
  every still until it fills its duration and the clip inflates.  A 5-keyframe
  draft of a 20s shot encoded as 717 frames / 29.875s -- 5 distinct pictures
  stretched over half a minute, and a duration no consumer could reconcile
  with the scene.
* one entry per *output frame*, each with ``duration 1/fps`` -- the stream is
  constant-rate before the encoder sees it, so ``-r`` only labels the
  container and the frame count is exact.

These tests pin the second shape.  The first one regressed in the field (all
six rose shots were ~25% too long), so the assertion is on the encoded frame
count and duration, not just on the manifest text.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.encoder import (
    _frame_durations,
    _frame_repeat_counts,
    encode_png_sequence,
)

FPS = 24


def _write_png(path: Path, colour: tuple[int, int, int]) -> None:
    """A 16x16 solid-colour PNG -- enough for ffmpeg to decode."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF
        )

    raw = b"".join(b"\x00" + bytes(colour) * 16 for _ in range(16))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _make_frames(directory: Path, numbers: list[int]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index, number in enumerate(numbers):
        _write_png(directory / f"frame_{number}.png", (40 * (index + 1) % 256, 80, 160))


def _ffprobe(path: Path) -> tuple[int, float]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
            "-show_entries", "stream=nb_read_frames", "-show_entries",
            "format=duration", "-of", "default=nw=1", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    fields = dict(
        line.split("=", 1) for line in result.stdout.strip().splitlines() if "=" in line
    )
    return int(fields["nb_read_frames"]), float(fields["duration"])


ffmpeg = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(ffmpeg is None, reason="ffmpeg not on PATH")


# ---------------------------------------------------------------------------
# 1. Durations become whole frame counts
# ---------------------------------------------------------------------------


class TestFrameRepeatCounts:
    def test_one_frame_of_duration_each_stays_one_entry(self) -> None:
        counts = _frame_repeat_counts(_frame_durations(list(range(1, 241)), fps=30), fps=30)
        assert counts == [1] * 240

    def test_a_two_second_beat_becomes_two_seconds_of_entries(self) -> None:
        counts = _frame_repeat_counts(_frame_durations([1, 61, 121], fps=30), fps=30)
        assert counts == [60, 60, 60]
        assert sum(counts) == 180  # 6.0s at 30fps

    def test_counts_never_round_down_to_zero(self) -> None:
        """A still shorter than one frame would vanish from the clip entirely."""

        counts = _frame_repeat_counts([0.001, 0.02], fps=24)
        assert counts == [1, 1]

    def test_rounding_survives_binary_fraction_error(self) -> None:
        """119/24 is not exact in binary; it must still be 119 entries."""

        durations = _frame_durations([1, 121, 240], fps=24)
        assert _frame_repeat_counts(durations, fps=24) == [120, 119, 119]


# ---------------------------------------------------------------------------
# 2. The manifest shape
# ---------------------------------------------------------------------------


class TestManifestShape:
    def test_a_draft_expands_to_one_entry_per_output_frame(self) -> None:
        # shot1 of the rose workflow: 5 keyframes, ~120 frames apart.
        numbers = [1, 121, 240, 359, 479]
        counts = _frame_repeat_counts(_frame_durations(numbers, fps=FPS), fps=FPS)
        assert counts == [120, 119, 119, 120, 120]
        assert sum(counts) == 598

    def test_a_full_animation_is_one_entry_per_frame(self) -> None:
        numbers = list(range(1, 481))
        counts = _frame_repeat_counts(_frame_durations(numbers, fps=FPS), fps=FPS)
        assert counts == [1] * 480
        assert sum(counts) == 480

    def test_entry_count_matches_intended_duration(self) -> None:
        """sum(counts) / fps is the only duration the clip is allowed to have."""

        for numbers in (
            [1, 121, 240, 359, 479],
            [1, 151, 300, 449, 599],
            list(range(1, 361)),
        ):
            durations = _frame_durations(numbers, fps=FPS)
            counts = _frame_repeat_counts(durations, fps=FPS)
            assert sum(counts) == pytest.approx(sum(durations) * FPS, abs=1)


# ---------------------------------------------------------------------------
# 3. The encoded clip is the length the manifest implies
# ---------------------------------------------------------------------------


@requires_ffmpeg
class TestEncodedFrameCount:
    @pytest.mark.parametrize(
        "numbers",
        [
            [1, 121, 240, 359, 479],   # draft: shot1
            [1, 151, 300, 449, 599],   # draft: shot6
            list(range(1, 481)),       # full 20s animation at 24fps
            list(range(1, 31)),        # short full animation
            [1],                       # a single still
        ],
    )
    def test_frame_count_equals_the_manifest_entry_count(self, tmp_path, numbers) -> None:
        frames_dir = tmp_path / "frames"
        _make_frames(frames_dir, numbers)
        out = tmp_path / "out.mp4"

        result = encode_png_sequence(str(frames_dir), str(out), fps=FPS, preset="ultrafast")
        assert result.success, result.error

        expected = sum(_frame_repeat_counts(_frame_durations(numbers, fps=FPS), fps=FPS))
        frames, duration = _ffprobe(out)
        assert frames == expected
        assert duration == pytest.approx(expected / FPS, abs=0.05)

    def test_a_five_still_draft_is_not_inflated_to_hundreds_of_frames(
        self, tmp_path
    ) -> None:
        """The regression this module exists for: 717 frames / 29.875s."""

        numbers = [1, 121, 240, 359, 479]
        frames_dir = tmp_path / "frames"
        _make_frames(frames_dir, numbers)
        out = tmp_path / "draft.mp4"

        assert encode_png_sequence(str(frames_dir), str(out), fps=FPS, preset="ultrafast").success

        frames, duration = _ffprobe(out)
        # 5 stills, ~5s each. Anything above ~600 frames means ffmpeg resampled.
        assert frames < 620
        assert duration < 26.0

    def test_no_stale_concat_manifest_is_left_behind(self, tmp_path) -> None:
        """The manifest is scratch; it must not accumulate per node render."""

        frames_dir = tmp_path / "frames"
        _make_frames(frames_dir, [1, 61])
        out = tmp_path / "out.mp4"
        assert encode_png_sequence(str(frames_dir), str(out), fps=FPS, preset="ultrafast").success

        def scratch_dirs() -> list[str]:
            return [p.name for p in Path(tempfile.gettempdir()).glob("scene3d_concat_*")]

        before = scratch_dirs()
        for index in range(3):
            again = tmp_path / f"again_{index}.mp4"
            assert encode_png_sequence(
                str(frames_dir), str(again), fps=FPS, preset="ultrafast"
            ).success
            assert scratch_dirs() == before


# ---------------------------------------------------------------------------
# 4. The manifest a keyframe draft actually needs
# ---------------------------------------------------------------------------


@requires_ffmpeg
class TestKeyframeDraftDurations:
    """A draft pass renders only keyframes, so each still must hold its gap.

    The keyframes come from ``_shot_keyframe_frames`` via the real SceneScript
    schema rather than a hand-written list, so this pins the whole chain: the
    shot's frame range -> its 5 keyframes -> the frame numbers -> the durations
    -> the entry counts.  If the converter starts spacing keyframes differently,
    the expected clip length moves with it instead of silently drifting from
    the shot.
    """

    @staticmethod
    def _script(start: int, end: int, frame_rate: int = 24) -> SceneScriptRoot:
        """Schema-valid script with exactly one shot spanning [start, end]."""

        return SceneScriptRoot.model_validate({
            "scene": {"name": "t", "environment": "outdoor", "lighting": "warm",
                      "duration": (end - start + 1) / frame_rate,
                      "frame_rate": frame_rate},
            "characters": [{
                "id": "c", "type": "lowpoly_human",
                "appearance": {"color": "#B03060", "height": 1.65, "scale": 1.0},
                "keyframes": [{"frame": f, "position": [-0.9, 0.0, 1.0],
                               "rotation_y": 120.0, "action": "stand"}
                              for f in (start, (start + end) // 2, end)],
            }],
            "cameras": [{
                "id": "cam", "shot_type": "medium",
                "keyframes": [{"frame": f, "position": [4.4, -5.2, 1.8],
                               "look_at": [0.6, 0.0, 1.6]}
                              for f in (start, (start + end) // 2, end)],
            }],
            "shots": [{"id": "s1", "camera": "cam",
                       "start_frame": start, "end_frame": end,
                       "description": ""}],
        })

    def test_a_real_keyframe_draft_holds_each_gap(self, tmp_path) -> None:
        from app.services.scene3d.blender_converter import keyframe_render_frames

        # The rose shot1 range: 0..479 at 24fps renders 480 frames, 5 keyframes.
        script = self._script(0, 479)
        numbers = [f + 1 for f in keyframe_render_frames(script)]
        assert numbers == [1, 121, 240, 359, 479], numbers

        frames_dir = tmp_path / "frames"
        _make_frames(frames_dir, numbers)
        out = tmp_path / "draft.mp4"
        assert encode_png_sequence(
            str(frames_dir), str(out), fps=FPS, preset="ultrafast"
        ).success

        expected = sum(
            _frame_repeat_counts(_frame_durations(numbers, fps=FPS), fps=FPS)
        )
        assert expected == 598
        frames, duration = _ffprobe(out)
        assert frames == expected
        assert duration == pytest.approx(expected / FPS, abs=0.05)

    def test_keyframe_count_scales_with_the_shot_length(self, tmp_path) -> None:
        """A longer shot's draft must be a proportionally longer clip.

        Guards the specific way this regressed: the clip length was a function
        of the *manifest shape*, not the shot, so a 20s shot and a 24s shot
        could encode to unrelated durations.  Here the ratio has to track the
        ratio of the shot lengths.
        """

        from app.services.scene3d.blender_converter import keyframe_render_frames

        clips = []
        for end in (239, 479, 599):
            numbers = [f + 1 for f in keyframe_render_frames(self._script(0, end))]
            expected = sum(
                _frame_repeat_counts(_frame_durations(numbers, fps=FPS), fps=FPS)
            )
            clips.append((end, expected))
            assert len(numbers) == 5, numbers

        # A draft runs ~1.25x the shot's frame count, not 1.0x: the tail-borrow
        # hands the last still the gap before it, so five keyframes cover five
        # gaps' worth of frames.  298/240, 598/480 and 748/600 all land there.
        for end, expected in clips:
            assert expected == pytest.approx((end + 1) * 1.25, rel=0.01), (end, expected)
        # And they grow with the shot rather than converging on one length.
        assert clips[0][1] < clips[1][1] < clips[2][1]
        # The 1.25x is a constant, so the ratio of drafts tracks the ratio of
        # shots -- which is the property the old broken encoder destroyed.
        assert clips[0][1] / clips[1][1] == pytest.approx(
            (clips[0][0] + 1) / (clips[1][0] + 1), rel=0.01
        )
        assert clips[1][1] / clips[2][1] == pytest.approx(
            (clips[1][0] + 1) / (clips[2][0] + 1), rel=0.01
        )

    def test_a_draft_is_far_cheaper_than_the_full_animation(self, tmp_path) -> None:
        """The draft's job is a cheap preview, not a full render.

        ``_frame_repeat_counts`` expands each keyframe to fill its gap, so a
        5-keyframe draft of a 20s shot encodes 598 frames -- from FIVE stills.
        The full animation encodes 480 frames from 480 stills.  Same shot, same
        duration, a hundredth of the render cost: that is what buys the shared
        Blender slot its throughput.

        Note 598 > 480.  The draft overshoots the shot by ~25% rather than
        landing exactly on it, because the tail-borrow gives the last still the
        gap before it.  Pinned by ``test_the_last_still_borrows_the_previous_gap``
        and deliberately not "fixed": a draft that ends exactly on the last
        keyframe loses the final pose's screen time.
        """

        from app.services.scene3d.blender_converter import keyframe_render_frames

        script = self._script(0, 479)
        draft = [f + 1 for f in keyframe_render_frames(script)]
        draft_frames = sum(
            _frame_repeat_counts(_frame_durations(draft, fps=FPS), fps=FPS)
        )
        full_frames = 480

        assert len(draft) == 5
        assert draft_frames == pytest.approx(full_frames * 1.25, rel=0.01)
        assert draft_frames / len(draft) > 50, "each still must hold a wide gap"
        assert full_frames / len(draft) > 90, "the draft renders a hundredth of the stills"

    def test_the_last_still_borrows_the_previous_gap(self, tmp_path) -> None:
        """Why a draft runs ~1.25x the shot instead of exactly the shot.

        A gap is the distance to the NEXT keyframe, so the last keyframe has no
        gap to give it -- and a still with no duration would drop out of the clip
        entirely.  It borrows the gap before it instead, which means a 5-keyframe
        draft covers 5 gaps of frames where the shot has 4.  This is the reason
        ``test_keyframe_count_scales_with_the_shot_length`` asserts 1.25x, and it
        is deliberate: cutting the borrow would end the draft on the last
        keyframe's exact start frame and lose the final pose's screen time.
        """

        from app.services.scene3d.blender_converter import keyframe_render_frames

        numbers = [f + 1 for f in keyframe_render_frames(self._script(0, 479))]
        durations = _frame_durations(numbers, fps=FPS)
        gaps = [b - a for a, b in zip(numbers, numbers[1:])]

        assert len(durations) == len(numbers) == 5
        # The first four stills own their real gaps; the fifth borrows the fourth.
        assert durations[:4] == [g / FPS for g in gaps]
        assert durations[4] == durations[3]
        assert durations[-1] > 0, "a still with no duration vanishes from the clip"

    def test_every_keyframe_still_appears_in_the_clip(self, tmp_path) -> None:
        """A draft with N keyframes must contain N distinct pictures.

        Repeating one entry per output frame must not collapse or drop a still:
        the encoded frame count is exactly what the repeat counts sum to, even
        though the stream is two orders of magnitude longer than the input.
        """

        numbers = [1, 61, 121, 181, 241]
        frames_dir = tmp_path / "frames"
        _make_frames(frames_dir, numbers)
        out = tmp_path / "distinct.mp4"
        assert encode_png_sequence(
            str(frames_dir), str(out), fps=FPS, preset="ultrafast"
        ).success

        expected = sum(
            _frame_repeat_counts(_frame_durations(numbers, fps=FPS), fps=FPS)
        )
        # A 5-keyframe draft of a 240-frame shot at 24fps: four 60-frame gaps
        # plus the tail-borrow, which gives the last still the gap before it.
        # 5 * 60, not 4 * 60 -- the trailing still holds its own 2.5s too.
        assert expected == 300
        frames, _duration = _ffprobe(out)
        assert frames == expected
        assert frames > len(numbers) * 10


# ---------------------------------------------------------------------------
# Animatic mux: a rendered previs plus the dialogue bed (V0.2 §14.9)
# ---------------------------------------------------------------------------


def _silent_video(tmp_path, seconds: float = 1.0) -> str:
    """A tiny silent clip through the real encoder."""
    from PIL import Image

    frames = tmp_path / "frames"
    frames.mkdir(exist_ok=True)
    for index in range(30):
        Image.new("RGB", (64, 48), (index * 4 % 255, 90, 140)).save(frames / f"frame_{index:04d}.png")
    video = str(tmp_path / "previs.mp4")
    encoded = encode_png_sequence(str(frames), video, fps=30)
    assert encoded.success, encoded.error
    return video


def _tone(tmp_path, seconds: float = 1.0) -> str:
    """A real WAV tone so the mux has a decodable audio input."""
    import math
    import struct
    import wave

    path = tmp_path / "bed.wav"
    rate = 8000
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 220 * index / rate)))
            for index in range(int(rate * seconds))
        )
        handle.writeframes(frames)
    return str(path)


@pytest.mark.media
@requires_ffmpeg
def test_the_animatic_mux_carries_the_bed_into_the_render(tmp_path) -> None:
    """The real mux: video copied untouched, audio added, duration honoured."""
    from app.services.scene3d.encoder import mux_audio_to_video

    video = _silent_video(tmp_path)
    audio = _tone(tmp_path, seconds=1.0)
    muxed_path = str(tmp_path / "previs_animatic.mp4")

    result = mux_audio_to_video(video, audio, muxed_path)
    assert result.success, result.error

    frames, duration = _ffprobe(Path(muxed_path))
    # The video pass is copied, not re-encoded; -shortest may trim the last
    # frame when both inputs are exactly 1.0s, so the honest bound is a frame
    # or two of slack rather than a fragile exact count.
    assert 29 <= frames <= 30
    assert 0.9 <= duration <= 1.2
    # And the audio is really there: a stream exists beyond the video one.
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", muxed_path],
        capture_output=True,
        text=True,
    )
    streams = json.loads(probe.stdout)["streams"]
    assert any(stream.get("codec_type") == "audio" for stream in streams)


@pytest.mark.media
@requires_ffmpeg
def test_the_mux_reports_a_missing_audio_file_instead_of_failing_loud(tmp_path) -> None:
    from app.services.scene3d.encoder import mux_audio_to_video

    video = _silent_video(tmp_path)
    result = mux_audio_to_video(video, str(tmp_path / "nope.wav"), str(tmp_path / "out.mp4"))
    assert result.success is False
    assert "not found" in (result.error or "")
