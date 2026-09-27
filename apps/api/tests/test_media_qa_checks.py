"""Tests for the image/video QA checks (ADR 0003 §5's second half).

Two properties are load-bearing:

1. **A skipped check never reports itself as a pass.** The registry's own
   design rule — every check that cannot run (no PIL, no ffprobe, an
   undecodable payload) degrades to ``warn`` WITH a reason. The fixtures below
   include a synthetic PNG that PIL cannot decode, and the expectation is
   ``warn``, never ``pass``.
2. **``fail`` is reserved for a positive identification**: a flat image, and a
   video far under its requested slot. Everything else warns, because an
   advisory gate whose only loud case is genuinely broken is what the doc
   asks for.
"""

from __future__ import annotations

import os
import struct

import pytest

from app.services.dialogue.media_qa_checks import (
    FLATNESS_STDDEV_FLOOR,
    IMAGE_MIN_SHORT_SIDE_PX,
    VIDEO_MIN_SHORT_SIDE_PX,
    build_media_qa_registry,
)
from app.services.dialogue.v2_qa_registry import QaSubject



# Engineering standard §1: these build real media through ffmpeg.
pytestmark = pytest.mark.media

def _real_png(path: str, *, width: int, height: int, flat: bool) -> str:
    """A genuinely decodable PNG written by PIL itself."""

    from PIL import Image

    colour = (17, 17, 17) if flat else None
    if flat:
        image = Image.new("RGB", (width, height), colour)
    else:
        # A gradient: real content, stddev far above the floor.
        image = Image.new("RGB", (width, height))
        for x in range(width):
            for y in range(height):
                image.putpixel((x, y), (x * 7 % 256, y * 5 % 256, (x + y) % 256))
    image.save(path)
    return path


def _synthetic_png(path: str) -> str:
    """A header-only PNG (signature + IHDR + padding): NOT decodable."""

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = b"IHDR" + struct.pack(">IIBBBBB", 64, 48, 8, 2, 0, 0, 0)
    body = signature + struct.pack(">I", len(ihdr)) + ihdr
    text = b"tEXt" + b"Comment\x00" + b"fixture"
    body += struct.pack(">I", len(text)) + text
    body += b"\x00" * 800
    with open(path, "wb") as handle:
        handle.write(body)
    return path


def _run(subject: QaSubject) -> dict[str, dict]:
    """check name → outcome dict, for the whole registry."""

    registry = build_media_qa_registry()
    return {
        outcome["check"]: outcome for outcome in registry.report(subject)["outcomes"]
    }


class TestImageChecks:
    def test_a_flat_image_fails_the_commit(self, tmp_path) -> None:
        """The silence floor's sibling: a solid colour is not a picture."""

        path = _real_png(os.path.join(tmp_path, "flat.png"), width=320, height=240, flat=True)
        outcomes = _run(QaSubject(image_path=path))
        flatness = outcomes["image_flatness"]
        assert flatness["status"] == "fail"
        assert flatness["details"]["remedy"]

    def test_a_real_image_passes(self, tmp_path) -> None:
        path = _real_png(
            os.path.join(tmp_path, "content.png"), width=800, height=600, flat=False
        )
        outcomes = _run(QaSubject(image_path=path))
        assert outcomes["image_flatness"]["status"] == "pass"
        assert outcomes["image_resolution_floor"]["status"] == "pass"

    def test_a_small_image_warns_without_blocking(self, tmp_path) -> None:
        """Legitimately small is not broken — it is a placeholder worth a look."""

        path = _real_png(
            os.path.join(tmp_path, "small.png"), width=240, height=180, flat=False
        )
        outcomes = _run(QaSubject(image_path=path))
        assert outcomes["image_resolution_floor"]["status"] == "warn"
        assert str(IMAGE_MIN_SHORT_SIDE_PX) in outcomes["image_resolution_floor"]["reason"]

    def test_an_undecodable_image_warns_and_never_claims_a_pass(self, tmp_path) -> None:
        """The registry's own rule: not checked ≠ passed."""

        path = _synthetic_png(os.path.join(tmp_path, "header-only.png"))
        outcomes = _run(QaSubject(image_path=path))
        for name in ("image_flatness", "image_resolution_floor"):
            assert outcomes[name]["status"] == "warn", name
            assert "跳过" in outcomes[name]["reason"]

    def test_no_image_is_not_applicable(self) -> None:
        outcomes = _run(QaSubject())
        assert outcomes["image_flatness"]["status"] == "pass"
        assert "不适用" in outcomes["image_flatness"]["reason"]


class TestVideoChecks:
    def _ffmpeg_video(self, tmp_path, name: str, *, duration: str, height: int) -> str:
        import shutil

        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not installed on this machine")
        path = os.path.join(tmp_path, name)
        import subprocess

        width = height * 16 // 9
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"testsrc=size={width}x{height}:rate=24:duration={duration}",
                "-pix_fmt", "yuv420p", path,
            ],
            capture_output=True,
            timeout=180,
        )
        return path

    def test_a_matching_duration_and_resolution_pass(self, tmp_path) -> None:
        path = self._ffmpeg_video(tmp_path, "ok.mp4", duration="3", height=540)
        outcomes = _run(QaSubject(video_path=path, requested_duration_seconds=3.0))
        assert outcomes["video_duration_vs_request"]["status"] == "pass"
        assert outcomes["video_resolution_floor"]["status"] == "pass"

    def test_a_truncated_take_fails_the_commit(self, tmp_path) -> None:
        """Half the slot asked for is a missing shot, not a short one."""

        path = self._ffmpeg_video(tmp_path, "short.mp4", duration="1", height=540)
        outcomes = _run(QaSubject(video_path=path, requested_duration_seconds=5.0))
        duration_check = outcomes["video_duration_vs_request"]
        assert duration_check["status"] == "fail"
        assert "截断" in duration_check["reason"]

    def test_an_overrun_warns_but_publishes(self, tmp_path) -> None:
        """The edit can trim a long take; it cannot invent the missing half."""

        path = self._ffmpeg_video(tmp_path, "long.mp4", duration="7", height=540)
        outcomes = _run(QaSubject(video_path=path, requested_duration_seconds=5.0))
        assert outcomes["video_duration_vs_request"]["status"] == "warn"

    def test_a_video_below_the_previs_floor_warns(self, tmp_path) -> None:
        path = self._ffmpeg_video(tmp_path, "tiny.mp4", duration="2", height=240)
        outcomes = _run(QaSubject(video_path=path, requested_duration_seconds=2.0))
        assert outcomes["video_resolution_floor"]["status"] == "warn"
        assert str(VIDEO_MIN_SHORT_SIDE_PX) in outcomes["video_resolution_floor"]["reason"]

    def test_an_unmeasurable_video_warns_rather_than_passing(self, tmp_path) -> None:
        path = os.path.join(tmp_path, "junk.mp4")
        with open(path, "wb") as handle:
            handle.write(b"not a video at all")
        outcomes = _run(QaSubject(video_path=path, requested_duration_seconds=5.0))
        assert outcomes["video_duration_vs_request"]["status"] == "warn"

    def test_no_requested_duration_is_said_not_assumed(self, tmp_path) -> None:
        """Comparing against nothing is not passing — it is not comparing."""

        import shutil

        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not installed on this machine")
        path = self._ffmpeg_video(tmp_path, "noslot.mp4", duration="2", height=540)
        outcomes = _run(QaSubject(video_path=path, requested_duration_seconds=None))
        assert outcomes["video_duration_vs_request"]["status"] == "warn"
        assert "没有声明请求时长" in outcomes["video_duration_vs_request"]["reason"]

    def test_no_video_is_not_applicable(self) -> None:
        outcomes = _run(QaSubject())
        assert outcomes["video_duration_vs_request"]["status"] == "pass"


class TestMediaRegistryShape:
    def test_the_names_are_unique_and_ordered(self) -> None:
        registry = build_media_qa_registry()
        names = registry.names
        assert len(names) == len(set(names))
        assert names == (
            "image_resolution_floor",
            "image_flatness",
            "video_resolution_floor",
            "video_duration_vs_request",
        )

    def test_every_entry_reports_a_structured_reason(self) -> None:
        for outcome in build_media_qa_registry().run_all(QaSubject()):
            assert outcome["reason"] if isinstance(outcome, dict) else outcome.reason

    def test_the_flatness_floor_is_not_a_dark_image(self) -> None:
        """A dark but real image must not trip the flat check."""

        from PIL import Image

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dark.png")
            image = Image.new("RGB", (400, 300))
            for x in range(400):
                for y in range(300):
                    # Dark overall (mean in the 20s-40s), but with real
                    # spread: a night shot, not a black rectangle.
                    image.putpixel((x, y), (20 + (x + y) % 48, 18 + x % 24, 22))
            image.save(path)
            from app.services.dialogue.media_qa_checks import _image_facts

            facts, skip = _image_facts(path)
            assert skip is None
            assert facts["stddev"] >= FLATNESS_STDDEV_FLOOR
