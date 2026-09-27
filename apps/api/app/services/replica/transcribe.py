"""拉片复刻 · 参考片转录（词级时间戳，hypit 的"时间脊柱"）。

hypit 流水线里 WhisperX 承担"词 → 秒"的映射：B-roll/字幕/音效锚点绑定在
台词的**词**上，改台词时整条片子自动重排。teardown 在抽帧读片之外抽取
音轨做词级转录，供蓝图把锚点事件从段落级升级到词级：

    参考视频 → ffmpeg 抽音轨（16kHz mono wav）→ whisperX transcribe + align
             → 词流 [{text, start, end}] → 锚点词解析（blueprint.resolve_word_anchors）

依赖策略与 scene3d 的 speech_alignment 同款（engineering-standards §4）：
whisperX 是可选重依赖（懒加载，模块导入不需要 torch）；不可用时**显式
降级**——``source="unavailable"`` + 结构化原因（engine_disabled /
no_audio_track / engine_unavailable / failed），调用方据此在报告约束里
告知用户，绝不静默吞掉。

与 ``WhisperXAligner`` 的分工：那边是**已知台词的强制对齐**（生成的 bed
对着脚本对时间）；这边是**先转录拿词流**（拆解时还不知道台词，是转录的
消费方而非校准方）。模型加载参数共用 ``whisperx_model`` 配置。
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.core.config import Settings, get_settings

TRANSCRIBE_SOURCE_WHISPERX = "whisperx"
TRANSCRIBE_SOURCE_UNAVAILABLE = "unavailable"

#: 不可用的结构化原因（observable degradation，进入报告约束）
REASON_ENGINE_DISABLED = "engine_disabled"
REASON_NO_AUDIO_TRACK = "no_audio_track"
REASON_ENGINE_UNAVAILABLE = "engine_unavailable"
REASON_FAILED = "failed"

_FFMPEG_TIMEOUT_SECONDS = 120


class TranscriptionEngineError(RuntimeError):
    """whisperX 引擎不可用/加载失败（code 供降级标注）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TranscriptLine:
    """一句转录台词及其时间跨度。"""

    text: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class TranscriptWord:
    """一个转录词及其时间跨度（锚点绑定的最小单位）。"""

    text: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class TeardownTranscript:
    """参考片的词级转录结果。

    ``source="unavailable"`` 时 ``reason`` 必填——降级必须可查询。
    """

    source: str
    language: str = ""
    reason: str = ""
    lines: tuple[TranscriptLine, ...] = ()
    words: tuple[TranscriptWord, ...] = ()

    @property
    def available(self) -> bool:
        return self.source == TRANSCRIBE_SOURCE_WHISPERX

    def to_report_dict(self) -> dict[str, Any]:
        """进 TeardownReport 的紧凑形态（words 供蓝图解析词锚点）。"""
        return {
            "source": self.source,
            "language": self.language,
            "reason": self.reason,
            "lines": [
                {
                    "text": line.text,
                    "start_seconds": round(line.start_seconds, 3),
                    "end_seconds": round(line.end_seconds, 3),
                }
                for line in self.lines
            ],
            "words": [
                {
                    "text": word.text,
                    "start_seconds": round(word.start_seconds, 3),
                    "end_seconds": round(word.end_seconds, 3),
                }
                for word in self.words
            ],
        }


def extract_audio_track(video_path: Path, output_wav: Path) -> bool:
    """从视频抽 16kHz 单声道 wav 音轨（成功 True；无音轨/ffmpeg 失败 False）。"""
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output_wav),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, check=False,
            timeout=_FFMPEG_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and output_wav.exists()


def _load_engine(settings: Settings) -> Any:
    """懒加载 whisperX 模型（导入失败/加载失败都 fail-coded，不裸抛）。"""
    try:
        import whisperx
    except ImportError as exc:
        raise TranscriptionEngineError(
            REASON_ENGINE_UNAVAILABLE,
            "whisperX is not installed: uv pip install whisperx",
        ) from exc
    try:
        return whisperx.load_model(
            settings.whisperx_model,
            device="cpu",
            compute_type="int8",
        )
    except Exception as exc:  # noqa: BLE001 - coded fail-closed.
        raise TranscriptionEngineError(
            REASON_ENGINE_UNAVAILABLE,
            f"whisperX model load failed: {str(exc)[:200]}",
        ) from exc


def _normalize_words(aligned: dict[str, Any]) -> tuple[TranscriptWord, ...]:
    """whisperX 对齐输出的词流 → 规范词元组（LLM/模型输出不可信）。"""
    words: list[TranscriptWord] = []
    for segment in aligned.get("segments", []) or []:
        for raw in segment.get("words", []) or []:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            try:
                start = float(raw.get("start", 0.0))
                end = float(raw.get("end", start))
            except (TypeError, ValueError):
                continue
            if start != start or end != end:  # NaN
                continue
            words.append(
                TranscriptWord(
                    text=text,
                    start_seconds=max(0.0, start),
                    end_seconds=max(max(0.0, start), end),
                )
            )
    return tuple(words)


def _normalize_lines(aligned: dict[str, Any]) -> tuple[TranscriptLine, ...]:
    lines: list[TranscriptLine] = []
    for raw in aligned.get("segments", []) or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(raw.get("start", 0.0))
            end = float(raw.get("end", start))
        except (TypeError, ValueError):
            continue
        lines.append(
            TranscriptLine(
                text=text,
                start_seconds=max(0.0, start),
                end_seconds=max(max(0.0, start), end),
            )
        )
    return tuple(lines)


def transcribe_reference_video(
    video_path: Path,
    settings: Settings | None = None,
    *,
    extract_audio: Callable[[Path, Path], bool] = extract_audio_track,
    load_engine: Callable[[], Any] | None = None,
) -> TeardownTranscript:
    """参考视频 → 词级转录。

    任何一步不可用都返回 ``source="unavailable"``（带结构化原因），**不抛
    异常**——转录失败不应拖垮整个拆解，但降级必须显式可查询。
    """
    settings = settings or get_settings()
    if settings.speech_alignment_engine != "whisperx":
        return TeardownTranscript(source=TRANSCRIBE_SOURCE_UNAVAILABLE, reason=REASON_ENGINE_DISABLED)

    with tempfile.TemporaryDirectory(prefix="replica_transcribe_") as tmp_dir:
        wav_path = Path(tmp_dir) / "audio.wav"
        if not extract_audio(video_path, wav_path):
            return TeardownTranscript(
                source=TRANSCRIBE_SOURCE_UNAVAILABLE, reason=REASON_NO_AUDIO_TRACK
            )

        try:
            model = load_engine() if load_engine is not None else _load_engine(settings)
            transcription = model.transcribe(str(wav_path))
            import whisperx

            align_model, metadata = whisperx.load_align_model(
                language_code=transcription.get("language", "zh"),
                device="cpu",
            )
            aligned = whisperx.align(
                transcription.get("segments", []) or [],
                align_model,
                metadata,
                str(wav_path),
                "cpu",
                return_char_alignments=False,
            )
        except TranscriptionEngineError as exc:
            return TeardownTranscript(
                source=TRANSCRIBE_SOURCE_UNAVAILABLE, reason=exc.code
            )
        except Exception:  # noqa: BLE001 - 降级为 unavailable，原因可查询
            return TeardownTranscript(
                source=TRANSCRIBE_SOURCE_UNAVAILABLE, reason=REASON_FAILED
            )

        return TeardownTranscript(
            source=TRANSCRIBE_SOURCE_WHISPERX,
            language=str(transcription.get("language") or ""),
            lines=_normalize_lines(aligned if isinstance(aligned, dict) else {}),
            words=_normalize_words(aligned if isinstance(aligned, dict) else {}),
        )
