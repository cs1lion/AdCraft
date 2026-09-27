"""Tests for joining and measuring per-line speech takes.

Both operations shell out to ffmpeg, so the seam is the seam: the executor
injects fakes and never spawns a process in a unit test. What these tests lock
is the CONTRACT around the seam — a partial join (one line's file missing) is a
failure, never a half-length take; and a duration that cannot be measured is
reported as unknown rather than guessed or raised.
"""

from __future__ import annotations

import os

import pytest

from app.services.dialogue.audio_concat import (
    concat_audio_files,
    probe_audio_duration_seconds,
)



# Engineering standard §1: these build real media through ffmpeg.
pytestmark = pytest.mark.media

def _tone(path: str, *, frequency: int, duration: str) -> str:
    """A real (short) MP3 — placeholder bytes are not decodable input."""

    import subprocess

    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"sine=frequency={frequency}:duration={duration}",
            "-q:a", "9", path,
        ],
        capture_output=True,
        timeout=120,
    )
    return path


class TestConcatAudioFiles:
    def _files(self, tmp_path, names, *, fill: bool = True) -> list[str]:
        """Name → path. ``fill`` writes an EMPTY file (a missing body)."""

        paths = []
        for name in names:
            path = os.path.join(tmp_path, name)
            if fill:
                with open(path, "wb") as handle:
                    handle.write(b"")
            paths.append(path)
        return paths

    def _tones(self, tmp_path) -> list[str]:
        return [
            _tone(os.path.join(tmp_path, "a.mp3"), frequency=440, duration="0.4"),
            _tone(os.path.join(tmp_path, "b.mp3"), frequency=660, duration="0.3"),
        ]

    def test_no_usable_input_is_a_failure_not_an_empty_take(self, tmp_path) -> None:
        result = concat_audio_files([], os.path.join(tmp_path, "take.mp3"))
        assert result.success is False
        assert result.error

    def test_a_missing_line_fails_rather_than_joining_half_a_take(self, tmp_path) -> None:
        paths = self._files(tmp_path, ["a.mp3"], fill=True)
        paths.append(os.path.join(tmp_path, "missing.mp3"))
        assert os.path.isfile(paths[0])
        result = concat_audio_files(paths, os.path.join(tmp_path, "take.mp3"))
        assert result.success is False
        assert "缺失" in (result.error or "")

    def test_a_real_join_writes_the_take(self, tmp_path) -> None:
        """Uses ffmpeg when present; skips (never fails) when the box has none."""

        import shutil

        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not installed on this machine")
        paths = self._tones(tmp_path)
        output = os.path.join(tmp_path, "take.mp3")
        result = concat_audio_files(paths, output)
        assert result.success is True, result.error
        assert os.path.isfile(output)
        assert os.path.getsize(output) > 0
        # Two tones joined must be measurably longer than either alone.
        joined = probe_audio_duration_seconds(output)
        assert joined is not None and joined >= 0.5

    def test_the_temp_list_is_cleaned_up(self, tmp_path) -> None:
        import shutil

        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not installed on this machine")
        output = os.path.join(tmp_path, "take.mp3")
        concat_audio_files(self._tones(tmp_path), output)
        assert not os.path.exists(f"{output}.txt")


class TestProbeAudioDuration:
    def test_a_missing_file_is_unknown_not_zero(self, tmp_path) -> None:
        assert probe_audio_duration_seconds(os.path.join(tmp_path, "nope.mp3")) is None

    def test_a_real_file_is_measured(self, tmp_path) -> None:
        import shutil

        if shutil.which("ffprobe") is None:
            pytest.skip("ffprobe not installed on this machine")
        path = os.path.join(tmp_path, "tone.mp3")
        import subprocess

        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                "-q:a", "9", path,
            ],
            capture_output=True,
            timeout=60,
        )
        duration = probe_audio_duration_seconds(path)
        assert duration is not None
        assert 0.8 <= duration <= 1.4

    def test_a_non_audio_file_is_unknown(self, tmp_path) -> None:
        path = os.path.join(tmp_path, "junk.mp3")
        with open(path, "wb") as handle:
            handle.write(b"not audio at all")
        assert probe_audio_duration_seconds(path) is None
