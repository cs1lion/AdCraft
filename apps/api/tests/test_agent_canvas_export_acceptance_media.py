"""导出后置验收真机测试（media 标记）：合成片源端到端跑一遍。

用 lavfi 合成"黑白两段 + 前半有正弦音"，验证：
- 切点对账能命中 5s 处的真实视觉切换；
- 无字幕 cue 时烧录检查 skipped；
- 后半段（静音）若有 cue 会被判"窗口接近静音"。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.schemas.agent_canvas_editing import (
    EditingManifestV2,
    EditingSubtitleEntryV2,
    EditingVideoEntryV2,
)
from app.services.agent_canvas_export_acceptance import run_export_acceptance

pytestmark = pytest.mark.media


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture()
def synthetic_video(tmp_path: Path) -> Path:
    """黑白各 5 秒（5s 处一个硬切），前 5 秒正弦音、后 5 秒静音。"""
    out = tmp_path / "synthetic.mp4"
    command = (
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=black:size=320x180:rate=24:duration=5",
        "-f", "lavfi", "-i", "color=c=white:size=320x180:rate=24:duration=5",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:duration=5",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a][3:a]concat=n=2:v=0:a=1[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
        out.as_posix(),
    )
    subprocess.run(command, check=True, capture_output=True)
    return out


def _manifest_with(starts: tuple[float, ...], cues: tuple[tuple[float, float, str], ...]):
    return EditingManifestV2(
        video_entries=tuple(
            EditingVideoEntryV2(asset_id=f"asset_{i}", timeline_start_seconds=start)
            for i, start in enumerate(starts)
        ),
        subtitle_entries=tuple(
            EditingSubtitleEntryV2(start_seconds=s, end_seconds=e, text=t) for s, e, t in cues
        ),
        subtitle_burn_in=False,  # 合成片没有烧字幕，烧录检查应 skipped
        timeline_duration_seconds=10.0,
    )


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg/ffprobe not installed")
def test_synthetic_video_cuts_and_silence(synthetic_video: Path):
    # cue 落在静音段（7-8.5s）→ 应报"窗口接近静音"
    manifest = _manifest_with((0.0, 5.0), ((7.0, 8.5, "静音段的字幕"),))
    report = run_export_acceptance(synthetic_video, manifest)

    by_check = {check.check: check for check in report.checks}
    assert by_check["streams"].status == "pass"
    assert by_check["subtitles_burned"].status == "skipped"
    assert by_check["cuts_vs_entries"].status == "pass", by_check["cuts_vs_entries"].detail
    assert by_check["cue_windows_audible"].status == "warn"
    assert "接近静音" in by_check["cue_windows_audible"].detail
    assert by_check["duration_alignment"].status == "pass"


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg/ffprobe not installed")
def test_synthetic_video_loud_cue_passes(synthetic_video: Path):
    # cue 落在有声段（1-2.5s）→ 窗口有声音，全部 pass
    manifest = _manifest_with((0.0, 5.0), ((1.0, 2.5, "有声段的字幕"),))
    report = run_export_acceptance(synthetic_video, manifest)
    by_check = {check.check: check for check in report.checks}
    assert by_check["cue_windows_audible"].status == "pass", by_check["cue_windows_audible"].detail
