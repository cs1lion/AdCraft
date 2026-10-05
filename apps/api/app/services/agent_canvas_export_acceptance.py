"""导出后置验收（playbook §4 验收脚本化的媒体半场）。

成片渲染完成后、资产提交前，对 staging 产物跑一组只读 ffmpeg 检查，把
"切点/字幕烧录/台词窗口有声/音画时长"从人眼验收变成可查询报告。报告随
``last_successful_export.acceptance`` 落节点，**只记录不阻断**——任何一项
失败都不改变导出结果（工程标准 §4：降级可查询，never block）。

与前端 ``projectCheckup.ts``（结构半场）互补：那边管缺口与对账，这边管
媒体本身的物理事实。全部命令可注入，单测不需要真 ffmpeg（真机行为由
media 标记测试覆盖）。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.schemas.agent_canvas_editing import (
    EditingExportAcceptanceCheckV2,
    EditingExportAcceptanceV2,
    EditingManifestV2,
)

#: 字幕 cue 抽验上限：cue 可能很多，抽前 6 个足够发现"没烧上/整段静音"。
_MAX_CUE_SAMPLES = 6

#: 底部字幕带的亮像素阈值：灰度 > 225 视为文字像素；cue 帧至少要有这么多。
_MIN_BRIGHT_PIXELS = 40

#: cue 帧亮像素需显著高于无字幕基线（运动画面自带高光）。
_BRIGHT_BASELINE_FACTOR = 3.0

#: 切点匹配容差（秒）：scene detect 的分数阈值与帧率取整都会带来抖动。
_CUT_MATCH_TOLERANCE_SECONDS = 0.35

#: 音画时长差容忍（秒）。
_DURATION_TOLERANCE_SECONDS = 1.0

#: cue 窗口静音线（mean volume dB）：低于它视为该窗口没有语音。
_SILENCE_MEAN_DB = -50.0

RunCommand = Callable[[tuple[str, ...]], "subprocess.CompletedProcess[str]"]
RunBinary = Callable[[tuple[str, ...]], "subprocess.CompletedProcess[bytes]"]


@dataclass(frozen=True)
class _Probe:
    video_duration: float | None = None
    audio_duration: float | None = None
    has_video: bool = False
    has_audio: bool = False


def _default_run(args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _default_run_binary(args: tuple[str, ...]) -> subprocess.CompletedProcess[bytes]:
    # 二进制通道（rawvideo 抽帧）：text=True 会按 locale 解码像素字节，
    # Windows cp936 下长度对不上——抽帧必须走 bytes。
    return subprocess.run(args, capture_output=True, check=False)


def _probe_streams(
    video_path: Path,
    *,
    ffprobe_path: str,
    run: RunCommand,
) -> _Probe | None:
    completed = run((
        ffprobe_path, "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", video_path.as_posix(),
    ))
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    format_section = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    format_duration = format_section.get("duration")

    def _duration(source: object) -> float | None:
        record = source if isinstance(source, dict) else {}
        value = record.get("duration")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass
        # 流级 duration 常缺失（mp4/mov 常见）：回退容器时长。
        if isinstance(format_duration, (int, float)):
            return float(format_duration)
        if isinstance(format_duration, str):
            try:
                return float(format_duration)
            except ValueError:
                return None
        return None

    return _Probe(
        video_duration=_duration(video),
        audio_duration=_duration(audio),
        has_video=video is not None,
        has_audio=audio is not None,
    )


def _scene_cuts(
    video_path: Path,
    *,
    ffmpeg_path: str,
    run: RunCommand,
) -> list[float] | None:
    """视觉切点时刻列表；检测失败返回 None（调用方降级为 skipped）。"""
    completed = run((
        ffmpeg_path, "-hide_banner", "-nostats", "-i", video_path.as_posix(),
        "-vf", "select='gt(scene,0.25)',metadata=print:file=-", "-an",
        "-f", "null", "-",
    ))
    if completed.returncode != 0:
        return None
    cuts: list[float] = []
    for line in (completed.stderr or "").splitlines() + (completed.stdout or "").splitlines():
        marker = "pts_time:"
        if marker not in line:
            continue
        raw = line.split(marker, 1)[1].split()[0]
        try:
            cuts.append(round(float(raw), 3))
        except ValueError:
            continue
    return cuts


def _window_mean_volume(
    video_path: Path,
    *,
    start: float,
    duration: float,
    ffmpeg_path: str,
    run: RunCommand,
) -> float | None:
    completed = run((
        ffmpeg_path, "-hide_banner", "-nostats",
        "-ss", f"{max(start, 0.0):.3f}", "-t", f"{max(duration, 0.1):.3f}",
        "-i", video_path.as_posix(), "-vn", "-af", "volumedetect", "-f", "null", "-",
    ))
    if completed.returncode != 0:
        return None
    for line in (completed.stderr or "").splitlines():
        if "mean_volume:" not in line:
            continue
        try:
            return float(line.split("mean_volume:")[1].split("dB")[0].strip())
        except (IndexError, ValueError):
            return None
    return None


def _bright_pixel_count(
    video_path: Path,
    *,
    at_seconds: float,
    width: int,
    height: int,
    band_height: int,
    ffmpeg_path: str,
    run_binary: RunBinary,
) -> int | None:
    """底部横带内灰度 > 225 的像素数；抽帧失败返回 None。"""
    crop = f"crop={width}:{band_height}:0:{max(height - band_height, 0)},format=gray"
    completed = run_binary((
        ffmpeg_path, "-hide_banner", "-nostats",
        "-ss", f"{max(at_seconds, 0.0):.3f}", "-i", video_path.as_posix(),
        "-frames:v", "1", "-vf", crop, "-f", "rawvideo", "-",
    ))
    if completed.returncode != 0:
        return None
    payload = completed.stdout or b""
    if len(payload) < width * band_height:
        return None
    return sum(1 for byte in payload[: width * band_height] if byte > 225)


def _cue_samples(manifest: EditingManifestV2) -> list[tuple[float, float, str]]:
    cues = [
        (float(entry.start_seconds), float(entry.end_seconds), entry.text)
        for entry in manifest.subtitle_entries
        if float(entry.end_seconds) > float(entry.start_seconds)
    ]
    return cues[:_MAX_CUE_SAMPLES]


def run_export_acceptance(
    video_path: Path,
    manifest: EditingManifestV2,
    *,
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
    frame_width: int = 1280,
    frame_height: int = 720,
    run: RunCommand = _default_run,
    run_binary: RunBinary = _default_run_binary,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> EditingExportAcceptanceV2:
    """对成片跑四组只读检查；任何异常都收敛成一条 warn，绝不抛出。"""
    checks: list[EditingExportAcceptanceCheckV2] = []
    try:
        checks.extend(_check_streams(video_path, ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path, run=run))
        checks.extend(_check_subtitles_burned(
            video_path, manifest,
            ffmpeg_path=ffmpeg_path, run_binary=run_binary,
            frame_width=frame_width, frame_height=frame_height,
        ))
        checks.extend(_check_cue_windows_audible(video_path, manifest, ffmpeg_path=ffmpeg_path, run=run))
        checks.extend(_check_cuts(video_path, manifest, ffmpeg_path=ffmpeg_path, run=run))
        checks.extend(_check_duration(video_path, manifest, ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path, run=run))
    except Exception as error:  # noqa: BLE001 - 验收绝不阻断导出。
        checks.append(EditingExportAcceptanceCheckV2(
            check="acceptance_unavailable",
            status="warn",
            detail=f"验收自身异常（导出不受影响）：{error}",
        ))
    return EditingExportAcceptanceV2(checks=tuple(checks), ran_at=clock())


def _check_streams(
    video_path: Path,
    *,
    ffmpeg_path: str,
    ffprobe_path: str,
    run: RunCommand,
) -> tuple[EditingExportAcceptanceCheckV2, ...]:
    probe = _probe_streams(video_path, ffprobe_path=ffprobe_path, run=run)
    if probe is None:
        return (EditingExportAcceptanceCheckV2(
            check="streams", status="skipped", detail="ffprobe 不可用，跳过流检查。",
        ),)
    if not probe.has_video:
        return (EditingExportAcceptanceCheckV2(
            check="streams", status="fail", detail="成片没有视频流。",
        ),)
    if not probe.has_audio:
        return (EditingExportAcceptanceCheckV2(
            check="streams", status="warn", detail="成片没有音频流。",
        ),)
    return (EditingExportAcceptanceCheckV2(
        check="streams", status="pass",
        detail=f"视频 {probe.video_duration or 0:.2f}s / 音频 {probe.audio_duration or 0:.2f}s。",
    ),)


def _check_subtitles_burned(
    video_path: Path,
    manifest: EditingManifestV2,
    *,
    ffmpeg_path: str,
    run_binary: RunBinary,
    frame_width: int,
    frame_height: int,
) -> tuple[EditingExportAcceptanceCheckV2, ...]:
    if not manifest.subtitle_burn_in or not manifest.subtitle_entries:
        return (EditingExportAcceptanceCheckV2(
            check="subtitles_burned", status="skipped", detail="未开启字幕烧录或没有字幕 cue。",
        ),)
    cues = _cue_samples(manifest)
    band_height = max(64, frame_height // 6)
    baseline_at = 0.2
    baseline = _bright_pixel_count(
        video_path, at_seconds=baseline_at, width=frame_width, height=frame_height,
        band_height=band_height, ffmpeg_path=ffmpeg_path, run_binary=run_binary,
    )
    if baseline is None:
        return (EditingExportAcceptanceCheckV2(
            check="subtitles_burned", status="skipped", detail="无法抽帧（ffmpeg 不可用或输出异常）。",
        ),)
    threshold = max(_MIN_BRIGHT_PIXELS, baseline * _BRIGHT_BASELINE_FACTOR)
    failed_cues: list[str] = []
    sampled = 0
    for start, _end, text in cues:
        count = _bright_pixel_count(
            video_path, at_seconds=(start + min(_end, start + 0.8)) / 2,
            width=frame_width, height=frame_height,
            band_height=band_height, ffmpeg_path=ffmpeg_path, run_binary=run_binary,
        )
        if count is None:
            continue
        sampled += 1
        if count < threshold:
            failed_cues.append(f"{start:.1f}s「{text[:18]}」亮像素 {count}<{threshold:.0f}")
    if sampled == 0:
        return (EditingExportAcceptanceCheckV2(
            check="subtitles_burned", status="skipped", detail="cue 抽帧全部失败。",
        ),)
    if failed_cues:
        return (EditingExportAcceptanceCheckV2(
            check="subtitles_burned", status="fail",
            detail=f"{len(failed_cues)}/{sampled} 个抽验 cue 底部没有文字（基线 {baseline}px）："
            + "；".join(failed_cues),
        ),)
    return (EditingExportAcceptanceCheckV2(
        check="subtitles_burned", status="pass",
        detail=f"{sampled} 个抽验 cue 底部均有文字（基线 {baseline}px）。",
    ),)


def _check_cue_windows_audible(
    video_path: Path,
    manifest: EditingManifestV2,
    *,
    ffmpeg_path: str,
    run: RunCommand,
) -> tuple[EditingExportAcceptanceCheckV2, ...]:
    cues = _cue_samples(manifest)
    if not cues:
        return (EditingExportAcceptanceCheckV2(
            check="cue_windows_audible", status="skipped", detail="没有字幕 cue（无台词可对轴）。",
        ),)
    silent: list[str] = []
    sampled = 0
    for start, end, text in cues:
        mean = _window_mean_volume(
            video_path, start=start, duration=max(end - start, 0.2),
            ffmpeg_path=ffmpeg_path, run=run,
        )
        if mean is None:
            continue
        sampled += 1
        if mean < _SILENCE_MEAN_DB:
            silent.append(f"{start:.1f}-{end:.1f}s「{text[:18]}」{mean:.1f}dB")
    if sampled == 0:
        return (EditingExportAcceptanceCheckV2(
            check="cue_windows_audible", status="skipped", detail="音量检测全部失败。",
        ),)
    if silent:
        return (EditingExportAcceptanceCheckV2(
            check="cue_windows_audible", status="warn",
            detail=f"{len(silent)}/{sampled} 个 cue 窗口接近静音（字幕出现但没听见声音）："
            + "；".join(silent),
        ),)
    return (EditingExportAcceptanceCheckV2(
        check="cue_windows_audible", status="pass",
        detail=f"{sampled} 个 cue 窗口均有声音。",
    ),)


def _check_cuts(
    video_path: Path,
    manifest: EditingManifestV2,
    *,
    ffmpeg_path: str,
    run: RunCommand,
) -> tuple[EditingExportAcceptanceCheckV2, ...]:
    expected = sorted(
        round(float(entry.timeline_start_seconds), 3)
        for entry in manifest.video_entries
        if entry.timeline_start_seconds is not None
    )[1:]
    if not expected:
        return (EditingExportAcceptanceCheckV2(
            check="cuts_vs_entries", status="skipped", detail="清单没有时间线起止，无法对账切点。",
        ),)
    cuts = _scene_cuts(video_path, ffmpeg_path=ffmpeg_path, run=run)
    if cuts is None:
        return (EditingExportAcceptanceCheckV2(
            check="cuts_vs_entries", status="skipped", detail="scene 检测失败（ffmpeg 不可用或输出异常）。",
        ),)
    missing = [
        f"{expected_cut:.2f}s"
        for expected_cut in expected
        if not any(abs(cut - expected_cut) <= _CUT_MATCH_TOLERANCE_SECONDS for cut in cuts)
    ]
    extra = [
        f"{cut:.2f}s"
        for cut in cuts
        if not any(abs(cut - expected_cut) <= _CUT_MATCH_TOLERANCE_SECONDS for expected_cut in expected)
    ]
    if missing:
        return (EditingExportAcceptanceCheckV2(
            check="cuts_vs_entries", status="warn",
            detail=f"{len(missing)}/{len(expected)} 个设计切点未见视觉切换（相邻镜头画面可能过于相似）："
            + "、".join(missing)
            + (f"；额外切点：{'、'.join(extra)}" if extra else ""),
        ),)
    detail = f"{len(expected)} 个设计切点全部命中"
    if extra:
        detail += f"（另有 {len(extra)} 个额外切点：{'、'.join(extra[:4])}）"
    return (EditingExportAcceptanceCheckV2(check="cuts_vs_entries", status="pass", detail=detail),)


def _check_duration(
    video_path: Path,
    manifest: EditingManifestV2,
    *,
    ffmpeg_path: str,
    ffprobe_path: str,
    run: RunCommand,
) -> tuple[EditingExportAcceptanceCheckV2, ...]:
    del ffmpeg_path
    probe = _probe_streams(video_path, ffprobe_path=ffprobe_path, run=run)
    if probe is None or probe.video_duration is None:
        return (EditingExportAcceptanceCheckV2(
            check="duration_alignment", status="skipped", detail="ffprobe 不可用，跳过时长对齐。",
        ),)
    details = [f"视频 {probe.video_duration:.2f}s"]
    if probe.audio_duration is not None:
        details.append(f"音频 {probe.audio_duration:.2f}s")
        if abs(probe.video_duration - probe.audio_duration) > _DURATION_TOLERANCE_SECONDS:
            return (EditingExportAcceptanceCheckV2(
                check="duration_alignment", status="warn",
                detail="；".join(details) + f"——音画时长差超过 {_DURATION_TOLERANCE_SECONDS}s。",
            ),)
    if manifest.timeline_duration_seconds is not None:
        timeline = float(manifest.timeline_duration_seconds)
        details.append(f"时间线 {timeline:.2f}s")
        if abs(probe.video_duration - timeline) > max(_DURATION_TOLERANCE_SECONDS, timeline * 0.05):
            return (EditingExportAcceptanceCheckV2(
                check="duration_alignment", status="warn",
                detail="；".join(details) + "——成片与时间线设计时长偏差过大。",
            ),)
    return (EditingExportAcceptanceCheckV2(
        check="duration_alignment", status="pass", detail="；".join(details) + "，对齐。",
    ),)
