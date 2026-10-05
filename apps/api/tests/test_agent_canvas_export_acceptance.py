"""导出后置验收单测：注入 fake ffmpeg/ffprobe，不需要真二进制。

锁四个行为（playbook §4 媒体半场）：
1. 字幕烧录检查按"亮像素 vs 基线"判 pass/fail，没有字幕 cue 时 skipped；
2. cue 窗口静音报 warn（字幕出现但没声音）；
3. 切点对账按容差匹配，缺切点 warn、全命中 pass；
4. 验收自身异常收敛成一条 warn，绝不抛出、绝不阻断导出。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.schemas.agent_canvas_editing import (
    EditingManifestV2,
    EditingSubtitleEntryV2,
    EditingVideoEntryV2,
)
from app.services.agent_canvas_export_acceptance import run_export_acceptance


def _probe_payload(video: float = 15.0, audio: float | None = 15.0, streams: str = "va") -> str:
    stream_list = []
    if "v" in streams:
        stream_list.append({"codec_type": "video", "duration": video})
    if audio is not None and "a" in streams:
        stream_list.append({"codec_type": "audio", "duration": audio})
    return json.dumps({"streams": stream_list, "format": {"duration": video}})


def _manifest(
    *,
    subs: bool = True,
    burn_in: bool = True,
    starts: tuple[float, ...] = (0.0, 5.0, 10.0),
    timeline: float | None = 15.0,
) -> EditingManifestV2:
    return EditingManifestV2(
        video_entries=tuple(
            EditingVideoEntryV2(asset_id=f"asset_{i}", timeline_start_seconds=start)
            for i, start in enumerate(starts)
        ),
        subtitle_entries=(
            (
                EditingSubtitleEntryV2(start_seconds=3.0, end_seconds=4.5, text="你好。"),
                EditingSubtitleEntryV2(start_seconds=6.0, end_seconds=7.5, text="开火。"),
            )
            if subs
            else ()
        ),
        subtitle_burn_in=burn_in,
        timeline_duration_seconds=timeline,
    )


class FakeFfmpeg:
    """按参数形状分流的 fake：ffprobe/scene 检测/抽帧/音量各自可控。"""

    def __init__(
        self,
        *,
        probe_payload: str | None = _probe_payload(),
        cuts: list[float] | None = None,
        scene_fails: bool = False,
        bright_counts: dict[float, int] | None = None,
        frame_fails: bool = False,
        volumes: dict[float, float] | None = None,
        volume_fails: bool = False,
    ) -> None:
        self.probe_payload = probe_payload
        self.cuts = cuts
        self.scene_fails = scene_fails
        self.bright_counts = bright_counts or {}
        self.frame_fails = frame_fails
        self.volumes = volumes or {}
        self.volume_fails = volume_fails

    def __call__(self, args: tuple[str, ...]):
        if args[0].endswith("ffprobe"):
            if self.probe_payload is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="no ffprobe")
            return SimpleNamespace(returncode=0, stdout=self.probe_payload, stderr="")
        joined = " ".join(args)
        if "metadata=print" in joined:
            if self.scene_fails:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            lines = "".join(
                f"[Parsed_scene]\npts_time:{t}\nlavfi.scene_score=0.9\n" for t in (self.cuts or [])
            )
            return SimpleNamespace(returncode=0, stdout=lines, stderr="")
        if "rawvideo" in joined:
            if self.frame_fails:
                return SimpleNamespace(returncode=1, stdout=b"", stderr="boom")
            ss = float(args[args.index("-ss") + 1])
            count = self.bright_counts.get(round(ss, 2), 0)
            width, band = 1280, 120  # 与服务默认帧尺寸/底部横带一致
            payload = bytes([10]) * (width * band - count) + bytes([255]) * count
            return SimpleNamespace(returncode=0, stdout=payload, stderr="")
        if "volumedetect" in joined:
            if self.volume_fails:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            ss = float(args[args.index("-ss") + 1])
            volume = self.volumes.get(round(ss, 2), -20.0)
            return SimpleNamespace(
                returncode=0, stdout="", stderr=f"[volumedetect] mean_volume: {volume} dB",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _by_check(report):
    return {check.check: check for check in report.checks}


@pytest.fixture()
def video_path(tmp_path: Path) -> Path:
    video = tmp_path / "final.mp4"
    video.write_bytes(b"fake")
    return video


def _acceptance(video_path: Path, *, ffmpeg, manifest=None):
    return run_export_acceptance(
        video_path,
        manifest or _manifest(),
        run=ffmpeg,
        run_binary=ffmpeg,
        clock=lambda: datetime(2026, 10, 5, tzinfo=timezone.utc),
    )


def test_all_green_report(video_path: Path):
    ffmpeg = FakeFfmpeg(
        cuts=[5.0, 10.0],
        bright_counts={3.4: 400, 6.4: 400},
        volumes={3.0: -18.0, 6.0: -17.0},
    )
    report = _acceptance(video_path, ffmpeg=ffmpeg)
    checks = _by_check(report)
    assert checks["streams"].status == "pass"
    assert checks["subtitles_burned"].status == "pass"
    assert checks["cue_windows_audible"].status == "pass"
    assert checks["cuts_vs_entries"].status == "pass"
    assert checks["duration_alignment"].status == "pass"
    assert report.ran_at is not None


def test_subtitle_not_burned_fails(video_path: Path):
    ffmpeg = FakeFfmpeg(cuts=[5.0, 10.0], bright_counts={3.4: 5, 6.4: 6})
    report = _acceptance(video_path, ffmpeg=ffmpeg)
    check = _by_check(report)["subtitles_burned"]
    assert check.status == "fail"
    assert "没有文字" in check.detail


def test_silent_cue_window_warns(video_path: Path):
    ffmpeg = FakeFfmpeg(
        cuts=[5.0, 10.0],
        bright_counts={3.4: 400, 6.4: 400},
        volumes={3.0: -65.0, 6.0: -18.0},
    )
    report = _acceptance(video_path, ffmpeg=ffmpeg)
    check = _by_check(report)["cue_windows_audible"]
    assert check.status == "warn"
    assert "接近静音" in check.detail


def test_missing_cut_warns(video_path: Path):
    ffmpeg = FakeFfmpeg(cuts=[5.0], bright_counts={3.4: 400, 6.4: 400})
    report = _acceptance(video_path, ffmpeg=ffmpeg)
    check = _by_check(report)["cuts_vs_entries"]
    assert check.status == "warn"
    assert "未见视觉切换" in check.detail


def test_scene_detection_failure_degrades_to_skipped(video_path: Path):
    ffmpeg = FakeFfmpeg(scene_fails=True, bright_counts={3.4: 400, 6.4: 400})
    report = _acceptance(video_path, ffmpeg=ffmpeg)
    assert _by_check(report)["cuts_vs_entries"].status == "skipped"


def test_no_subtitles_skips_burn_check(video_path: Path):
    ffmpeg = FakeFfmpeg(cuts=[5.0, 10.0])
    report = _acceptance(video_path, ffmpeg=ffmpeg, manifest=_manifest(subs=False))
    assert _by_check(report)["subtitles_burned"].status == "skipped"


def test_acceptance_exception_never_raises(video_path: Path):
    class Exploding(FakeFfmpeg):
        def __call__(self, args):
            raise RuntimeError("ffmpeg exploded")

    report = _acceptance(video_path, ffmpeg=Exploding())
    checks = _by_check(report)
    assert "acceptance_unavailable" in checks
    assert checks["acceptance_unavailable"].status == "warn"


def test_duration_mismatch_warns(video_path: Path):
    ffmpeg = FakeFfmpeg(
        probe_payload=_probe_payload(video=18.0, audio=15.0),
        cuts=[5.0, 10.0],
        bright_counts={3.4: 400, 6.4: 400},
    )
    report = _acceptance(video_path, ffmpeg=ffmpeg)
    check = _by_check(report)["duration_alignment"]
    assert check.status == "warn"
    assert "音画时长差" in check.detail


def test_no_audio_stream_warns_and_cue_audio_skips(video_path: Path):
    ffmpeg = FakeFfmpeg(
        probe_payload=_probe_payload(video=15.0, audio=None, streams="v"),
        cuts=[5.0, 10.0],
        bright_counts={3.4: 400, 6.4: 400},
        volume_fails=True,
    )
    report = _acceptance(video_path, ffmpeg=ffmpeg)
    checks = _by_check(report)
    assert checks["streams"].status == "warn"
    assert checks["cue_windows_audible"].status == "skipped"


def test_ffprobe_unavailable_degrades(video_path: Path):
    ffmpeg = FakeFfmpeg(probe_payload=None, cuts=[5.0, 10.0], bright_counts={3.4: 400, 6.4: 400})
    report = _acceptance(video_path, ffmpeg=ffmpeg)
    checks = _by_check(report)
    assert checks["streams"].status == "skipped"
    assert checks["duration_alignment"].status == "skipped"
