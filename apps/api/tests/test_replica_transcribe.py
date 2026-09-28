"""Unit tests for the reference-video word-level transcription (词级转录).

Covers: the opt-in engine gate (disabled by default), honest degradation with
structured reasons (engineering-standards §4 — never silent), word/line
normalization against untrusted engine output, and the real ffmpeg audio
extraction (media-marked, skipped without ffmpeg).

Design rationale: hypit 的 WhisperX "时间脊柱"（docs/plans/hypit-replica-research.md
§6.3）；降级契约对齐 scene3d/speech_alignment.py。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest

from app.services.replica import transcribe as tr


@pytest.fixture
def whisperx_settings():
    return SimpleNamespace(speech_alignment_engine="whisperx", whisperx_model="large-v3")


@pytest.fixture
def default_settings():
    return SimpleNamespace(speech_alignment_engine="estimated", whisperx_model="large-v3")


class _FakeEngine:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.transcribed: list[str] = []

    def transcribe(self, audio_path: str):
        self.transcribed.append(audio_path)
        if self.fail:
            raise RuntimeError("model exploded")
        return {
            "language": "zh",
            "segments": [
                {
                    "text": " 别再这样洗脸了 ",
                    "start": 0.2,
                    "end": 1.6,
                    "words": [
                        {"text": "别再", "start": 0.2, "end": 0.5, "score": 0.9},
                        {"text": "", "start": 0.5, "end": 0.6, "score": 0.9},  # 空词丢弃
                        {"text": "这样", "start": "bad", "end": 0.9},  # 非法时间丢弃
                        {"text": "洗脸", "start": 0.9, "end": 1.4, "score": 0.8},
                        {"text": "了", "start": 1.4, "end": -0.1, "score": 0.7},  # 负值钳制
                    ],
                }
            ],
        }


def _install_fake_whisperx(monkeypatch, aligned: dict) -> None:
    fake = types.ModuleType("whisperx")

    def load_align_model(language_code, device):  # noqa: ANN001
        return object(), object()

    fake.load_align_model = load_align_model
    fake.align = lambda segments, model, metadata, audio, device, **kw: aligned
    monkeypatch.setitem(sys.modules, "whisperx", fake)


# ---------------------------------------------------------------------------
# 降级路径（每一条都显式可查询）
# ---------------------------------------------------------------------------


def test_engine_disabled_by_default(default_settings, tmp_path):
    transcript = tr.transcribe_reference_video(tmp_path / "v.mp4", default_settings)
    assert transcript.source == tr.TRANSCRIBE_SOURCE_UNAVAILABLE
    assert transcript.reason == tr.REASON_ENGINE_DISABLED
    assert transcript.words == ()


def test_no_audio_track_degrades(whisperx_settings, tmp_path):
    transcript = tr.transcribe_reference_video(
        tmp_path / "v.mp4",
        whisperx_settings,
        extract_audio=lambda video, wav: False,
    )
    assert transcript.reason == tr.REASON_NO_AUDIO_TRACK


def test_engine_import_failure_degrades(whisperx_settings, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "whisperx", None)  # import whisperx → ImportError
    transcript = tr.transcribe_reference_video(
        tmp_path / "v.mp4",
        whisperx_settings,
        extract_audio=lambda video, wav: True,
    )
    assert transcript.reason == tr.REASON_ENGINE_UNAVAILABLE


def test_engine_runtime_failure_degrades(whisperx_settings, tmp_path, monkeypatch):
    engine = _FakeEngine(fail=True)
    _install_fake_whisperx(monkeypatch, {"segments": []})
    transcript = tr.transcribe_reference_video(
        tmp_path / "v.mp4",
        whisperx_settings,
        extract_audio=lambda video, wav: True,
        load_engine=lambda: engine,
    )
    assert transcript.reason == tr.REASON_FAILED


# ---------------------------------------------------------------------------
# 正常路径：词流/句流规范化（模型输出不可信）
# ---------------------------------------------------------------------------


def test_transcription_normalizes_words_and_lines(whisperx_settings, tmp_path, monkeypatch):
    aligned = {
        "segments": [
            {
                "text": " 别再这样洗脸了 ",
                "start": 0.2,
                "end": 1.6,
                "words": [
                    {"text": "别再", "start": 0.2, "end": 0.5},
                    {"text": "", "start": 0.5, "end": 0.6},  # 空词丢弃
                    {"text": "这样", "start": "bad", "end": 0.9},  # 非法时间丢弃
                    {"text": "洗脸", "start": 0.9, "end": 1.4},
                    {"text": "了", "start": 1.4, "end": -0.1},  # 负 end 钳到 start
                ],
            }
        ]
    }
    engine = _FakeEngine()
    _install_fake_whisperx(monkeypatch, aligned)
    transcript = tr.transcribe_reference_video(
        tmp_path / "v.mp4",
        whisperx_settings,
        extract_audio=lambda video, wav: True,
        load_engine=lambda: engine,
    )
    assert transcript.available is True
    assert transcript.language == "zh"
    assert [(w.text, w.start_seconds, w.end_seconds) for w in transcript.words] == [
        ("别再", 0.2, 0.5),
        ("洗脸", 0.9, 1.4),
        ("了", 1.4, 1.4),  # -0.1 钳到 start
    ]
    assert [line.text for line in transcript.lines] == ["别再这样洗脸了"]


def test_report_dict_carries_compact_payload(whisperx_settings, tmp_path, monkeypatch):
    aligned = {
        "segments": [
            {"text": "别再", "start": 0.2, "end": 0.5,
             "words": [{"text": "别再", "start": 0.2, "end": 0.5}]}
        ]
    }
    _install_fake_whisperx(monkeypatch, aligned)
    transcript = tr.transcribe_reference_video(
        tmp_path / "v.mp4",
        whisperx_settings,
        extract_audio=lambda video, wav: True,
        load_engine=lambda: _FakeEngine(),
    )
    payload = transcript.to_report_dict()
    assert payload["source"] == "whisperx"
    assert payload["words"][0] == {"text": "别再", "start_seconds": 0.2, "end_seconds": 0.5}
    # 不可用时 reason 必须进 payload（可查询的降级）
    unavailable = tr.TeardownTranscript(
        source=tr.TRANSCRIBE_SOURCE_UNAVAILABLE, reason=tr.REASON_FAILED
    )
    assert unavailable.to_report_dict()["reason"] == tr.REASON_FAILED


# ---------------------------------------------------------------------------
# 真实 ffmpeg 抽音轨（media 标记：语义 mock 锁不住编解码行为）
# ---------------------------------------------------------------------------


@pytest.mark.media
def test_extract_audio_track_real_ffmpeg(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    video_path = tmp_path / "with_audio.mp4"
    wav_path = tmp_path / "audio.wav"
    # lavfi 合成带音轨的短视频（测试源必须有音频流，否则抽轨失败是正确语义）
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-shortest", "-c:v", "libx264", "-c:a", "aac",
            str(video_path),
        ],
        capture_output=True, text=True, check=True, timeout=60,
    )
    assert tr.extract_audio_track(video_path, wav_path) is True
    assert wav_path.exists() and wav_path.stat().st_size > 44


@pytest.mark.media
def test_extract_audio_track_without_audio_stream_is_false(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    pytest.importorskip("cv2")
    import cv2
    import numpy as np

    video_path = tmp_path / "silent.mp4"
    frame = np.full((16, 16, 3), 128, dtype="uint8")
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (16, 16)
    )
    for _ in range(10):
        writer.write(frame)
    writer.release()
    # 无音轨视频 → 抽轨失败（调用方降级为 no_audio_track，不崩溃）
    assert tr.extract_audio_track(video_path, tmp_path / "a.wav") is False


@pytest.mark.media
def test_extract_audio_track_rejects_missing_file(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    assert tr.extract_audio_track(tmp_path / "missing.mp4", tmp_path / "a.wav") is False
