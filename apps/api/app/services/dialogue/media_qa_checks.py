"""The image/video track's QA checks (ADR 0003 §5's second half).

The registry was built for speech, and the speech path wired it first — which
left exactly the gap the ADR predicted: "QA registry" existed, but the rest of
the v2 production chain (image, video) had ad-hoc gates (a mime check, a size
floor) and no *pre-commit* checks that answer "what was checked, what did it
find". A provider that answers a 5-second slot with 1.5 seconds of video, or a
"generated" image that is one flat colour, passes both of those gates.

These entries are deliberately the *content* checks the existing gates cannot
make, and they follow the same contract as the speech ones:

* every entry degrades WITH a reason when it cannot run (PIL missing, ffmpeg
  missing, the payload undecodable) — never a ``pass`` it did not measure;
* a ``fail`` is reserved for a positive identification of a broken artifact: a
  flat image is not a picture, and a video well under its requested slot is a
  truncated render. Everything else warns with a remedy, because an
  advisory-only gate whose only loud case is genuinely broken is the one the
  doc asks for (§14.13 / engineering standard §4: warn with remedies, block
  only what is certainly broken).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from app.services.dialogue.v2_qa_registry import (
    QA_FAIL,
    QA_PASS,
    QA_WARN,
    QaCheck,
    QaOutcome,
    QaRegistry,
    QaSubject,
)

#: An image whose short side is below this is a placeholder (a provider
#: thumbnail or a failed upscale), not an ad frame.
IMAGE_MIN_SHORT_SIDE_PX = 512

#: A video below this is not the 480P previs the product promises.
VIDEO_MIN_SHORT_SIDE_PX = 480

#: Pixel spread below this is not "a dark image" — it is NO image: a solid
#: colour, a blank canvas, a failed decode that PIL happened to accept.
FLATNESS_STDDEV_FLOOR = 1.5

#: Measured video duration below this fraction of the requested slot is a
#: truncated render (the provider gave up part-way).
VIDEO_MIN_DURATION_RATIO = 0.5

#: Beyond this fraction the take and the slot disagree enough to look at.
VIDEO_DURATION_TOLERANCE_RATIO = 0.25


def _image_facts(path: str) -> tuple[dict[str, Any] | None, str | None]:
    """(facts, skip_reason). Facts are width/height/stddev over the pixels.

    PIL is imported lazily: the module must import (and degrade) on a box
    without it, exactly like the ffmpeg-dependent checks.
    """

    try:
        from PIL import Image, ImageStat  # noqa: PLC0415 - deliberate lazy import
    except Exception as error:  # noqa: BLE001 - any import failure degrades.
        return None, f"PIL 不可用，跳过图像内容检查（未检查 ≠ 通过）：{error}"
    try:
        with Image.open(path) as handle:
            handle.load()
            width, height = handle.size
            grayscale = handle.convert("L")
            statistics = ImageStat.Stat(grayscale)
    except Exception as error:  # noqa: BLE001 - undecodable payload.
        return None, f"无法解码图像（{error}），跳过内容检查（未检查 ≠ 通过）。"
    spread = statistics.stddev[0] if statistics.stddev else 0.0
    return (
        {
            "width": width,
            "height": height,
            "short_side": min(width, height),
            "stddev": round(float(spread), 3),
        },
        None,
    )


def _video_facts(path: str) -> tuple[dict[str, Any] | None, str | None]:
    """(facts, skip_reason) via ffprobe: duration and the stream geometry."""

    if shutil.which("ffprobe") is None:
        return None, "ffprobe 不在 PATH 上，跳过视频检查（未测量 ≠ 通过）。"
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, f"ffprobe 调用失败：{error}"
    if result.returncode != 0:
        return None, "ffprobe 无法读取该视频（未测量 ≠ 通过）。"
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None, "ffprobe 输出无法解析（未测量 ≠ 通过）。"
    duration: float | None = None
    try:
        duration = float((payload.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    video_stream = next(
        (
            stream
            for stream in payload.get("streams") or []
            if stream.get("codec_type") == "video"
        ),
        None,
    )
    if video_stream is None:
        return None, "该文件没有视频流（未测量 ≠ 通过）。"
    try:
        width = int(video_stream["width"])
        height = int(video_stream["height"])
    except (KeyError, TypeError, ValueError):
        return None, "视频流没有可读的宽高（未测量 ≠ 通过）。"
    return (
        {
            "width": width,
            "height": height,
            "short_side": min(width, height),
            "duration_seconds": duration,
        },
        None,
    )


class ImageResolutionFloorCheck(QaCheck):
    """A placeholder image must not become an ad frame."""

    name = "image_resolution_floor"
    version = "1"

    def run(self, subject: QaSubject) -> QaOutcome:
        if not subject.image_path:
            return QaOutcome(
                check=self.name,
                status=QA_PASS,
                reason="没有图像可检查，不适用。",
                details={"image_path": None},
            )
        facts, skip = _image_facts(subject.image_path)
        if facts is None:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason=skip or "无法检查。",
                details={"image_path": subject.image_path},
            )
        short_side = facts["short_side"]
        if short_side < IMAGE_MIN_SHORT_SIDE_PX:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason=(
                    f"图像短边仅 {short_side}px，低于 {IMAGE_MIN_SHORT_SIDE_PX}px："
                    "这更像一次失败的放大或一张缩略图，不是可用的广告帧。"
                ),
                details={"image_path": subject.image_path, **facts},
            )
        return QaOutcome(
            check=self.name,
            status=QA_PASS,
            reason=f"图像 {facts['width']}×{facts['height']}，短边 {short_side}px 达到下限。",
            details={"image_path": subject.image_path, **facts},
        )


class ImageFlatnessCheck(QaCheck):
    """A solid-colour image is not a picture (the silence floor's sibling).

    A provider can answer with a valid PNG that is one flat colour: the mime
    gate and the size floor both pass, and the edit then carries a blank frame
    for the whole shot. That is the same failure as a speech bed measuring as
    silence, so it gets the same verdict — a ``fail``.
    """

    name = "image_flatness"
    version = "1"

    def run(self, subject: QaSubject) -> QaOutcome:
        if not subject.image_path:
            return QaOutcome(
                check=self.name,
                status=QA_PASS,
                reason="没有图像可检查，不适用。",
                details={"image_path": None},
            )
        facts, skip = _image_facts(subject.image_path)
        if facts is None:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason=skip or "无法检查。",
                details={"image_path": subject.image_path},
            )
        if facts["stddev"] < FLATNESS_STDDEV_FLOOR:
            return QaOutcome(
                check=self.name,
                status=QA_FAIL,
                reason=(
                    f"图像几乎没有内容（灰度标准差 {facts['stddev']}）："
                    "整帧接近一个纯色，不是一次可以提交的生成结果。"
                ),
                details={
                    "image_path": subject.image_path,
                    "stddev": facts["stddev"],
                    "stddev_floor": FLATNESS_STDDEV_FLOOR,
                    "remedy": "重新生成该镜头；连续出现时检查提供方的参考输入。",
                },
            )
        return QaOutcome(
            check=self.name,
            status=QA_PASS,
            reason=f"图像有实际内容（灰度标准差 {facts['stddev']}）。",
            details={"image_path": subject.image_path, **facts},
        )


class VideoResolutionFloorCheck(QaCheck):
    """The 480P previs is the product's promise; below it, it is a thumbnail."""

    name = "video_resolution_floor"
    version = "1"

    def run(self, subject: QaSubject) -> QaOutcome:
        if not subject.video_path:
            return QaOutcome(
                check=self.name,
                status=QA_PASS,
                reason="没有视频可检查，不适用。",
                details={"video_path": None},
            )
        facts, skip = _video_facts(subject.video_path)
        if facts is None:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason=skip or "无法检查。",
                details={"video_path": subject.video_path},
            )
        short_side = facts["short_side"]
        if short_side < VIDEO_MIN_SHORT_SIDE_PX:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason=(
                    f"视频短边仅 {short_side}px，低于 {VIDEO_MIN_SHORT_SIDE_PX}px："
                    "低于 480P 预演的承诺下限。"
                ),
                details={"video_path": subject.video_path, **facts},
            )
        return QaOutcome(
            check=self.name,
            status=QA_PASS,
            reason=f"视频 {facts['width']}×{facts['height']}，短边 {short_side}px 达到下限。",
            details={"video_path": subject.video_path, **facts},
        )


class VideoDurationVsRequestCheck(QaCheck):
    """The take must actually be the slot that was asked for.

    Two different failures wear the same clothes and only the numbers tell
    them apart: a provider that stopped early (a truncated render — FAIL, the
    shot is missing) and one that ran long (an over-run — WARN, the edit can
    trim it). A take nobody can measure warns rather than passes.
    """

    name = "video_duration_vs_request"
    version = "1"

    def run(self, subject: QaSubject) -> QaOutcome:
        if not subject.video_path:
            return QaOutcome(
                check=self.name,
                status=QA_PASS,
                reason="没有视频可检查，不适用。",
                details={"video_path": None},
            )
        facts, skip = _video_facts(subject.video_path)
        if facts is None:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason=skip or "无法检查。",
                details={"video_path": subject.video_path},
            )
        measured = facts["duration_seconds"]
        requested = subject.requested_duration_seconds
        if measured is None:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason="该视频没有可读时长，无法与请求时长比较（未测量 ≠ 通过）。",
                details={"video_path": subject.video_path},
            )
        if not requested or requested <= 0:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason=(
                    f"本次成片 {measured:.2f}s，但节点没有声明请求时长，"
                    "无法判断是否被截断（未比较 ≠ 通过）。"
                ),
                details={"video_path": subject.video_path, "measured_seconds": measured},
            )
        ratio = measured / requested
        details = {
            "video_path": subject.video_path,
            "measured_seconds": round(measured, 3),
            "requested_seconds": round(float(requested), 3),
            "ratio": round(ratio, 3),
        }
        if ratio < VIDEO_MIN_DURATION_RATIO:
            return QaOutcome(
                check=self.name,
                status=QA_FAIL,
                reason=(
                    f"成片仅 {measured:.2f}s，不到请求 {requested:.2f}s 的一半："
                    "这是一次被截断的渲染，镜头内容不完整。"
                ),
                details=details,
            )
        if abs(ratio - 1.0) > VIDEO_DURATION_TOLERANCE_RATIO:
            return QaOutcome(
                check=self.name,
                status=QA_WARN,
                reason=(
                    f"成片 {measured:.2f}s 与请求 {requested:.2f}s 相差 "
                    f"{(ratio - 1.0) * 100:+.0f}%：剪辑时可以修剪，但值得先看一眼。"
                ),
                details=details,
            )
        return QaOutcome(
            check=self.name,
            status=QA_PASS,
            reason=f"成片 {measured:.2f}s 与请求 {requested:.2f}s 一致。",
            details=details,
        )


def build_media_qa_registry() -> QaRegistry:
    """The image/video registry in its documented order."""

    registry = QaRegistry()
    registry.register(ImageResolutionFloorCheck())
    registry.register(ImageFlatnessCheck())
    registry.register(VideoResolutionFloorCheck())
    registry.register(VideoDurationVsRequestCheck())
    return registry
