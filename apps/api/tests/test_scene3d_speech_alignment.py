"""Unit tests for speech alignment (C-mode foundation).

Locks the engine contract: the deterministic estimated aligner's sequential
layout (scaled to the probed bed, anchors honoured), the confidence contract
(estimated confidence is conservative and flagged), the factory's fallback
when whisperX is absent, and the low-confidence helper. A fake aligner
stands in for WhisperX (the real one needs torch, imported lazily).
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.speech_alignment import (
    AlignedSegment,
    to_dialogue_lines,
    ALIGN_SOURCE_ESTIMATED,
    ESTIMATED_CONFIDENCE,
    EstimatedSpeechAligner,
    SpeechAlignmentError,
    WhisperXAligner,
    build_speech_aligner,
    low_confidence_ids,
    regenerate_low_confidence_segments,
)

LINES = [
    {"segment_id": "seg_0", "character_id": "char_a", "text": "就是这里，信号源在墙后面。"},
    {"segment_id": "seg_1", "character_id": "char_b", "text": "（轻声）你确定要进去吗？"},
    {"segment_id": "seg_2", "character_id": "char_a", "text": "跟紧我。"},
]


def _estimator(durations: dict[str, float]):
    class _E:
        def estimate_duration(self, text: str) -> float:
            return durations.get(text, 1.0)

        __call__ = estimate_duration

    return _E()


def test_estimated_alignment_is_sequential_and_scaled(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "bed.mp3"
    audio.write_bytes(b"fake")

    # Fake ffprobe: the bed is 6s; line estimates are 2/2/2.
    monkeypatch.setattr(
        "app.services.scene3d.speech_alignment.probe_audio_duration_seconds",
        lambda path, ffprobe_path="ffprobe": 6.0,
    )
    aligner = EstimatedSpeechAligner(
        _estimator({"就是这里，信号源在墙后面。": 2.0, "（轻声）你确定要进去吗？": 2.0, "跟紧我。": 2.0})
    )

    segments = aligner.align(audio_path=str(audio), lines=LINES)

    assert [s.segment_id for s in segments] == ["seg_0", "seg_1", "seg_2"]
    assert segments[0].start_time == 0.0
    assert segments[0].end_time == 2.0
    assert segments[1].start_time == 2.0
    assert segments[2].end_time == pytest.approx(6.0)
    # Honest provenance: estimated, never passing as measured alignment.
    assert all(s.align_source == ALIGN_SOURCE_ESTIMATED for s in segments)
    assert all(s.confidence == ESTIMATED_CONFIDENCE for s in segments)


def test_estimated_alignment_honours_explicit_anchors(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "bed.mp3"
    audio.write_bytes(b"fake")
    monkeypatch.setattr(
        "app.services.scene3d.speech_alignment.probe_audio_duration_seconds",
        lambda path, ffprobe_path="ffprobe": 8.0,
    )
    aligner = EstimatedSpeechAligner(_estimator({}))

    lines = [
        {"segment_id": "a", "character_id": "char_a", "text": "第一句"},
        {"segment_id": "b", "character_id": "char_b", "text": "第二句", "start_time": 4.0},
    ]
    segments = aligner.align(audio_path=str(audio), lines=lines)

    assert segments[0].end_time == pytest.approx(4.0)  # fills until the anchor
    assert segments[1].start_time == 4.0  # the anchor is honoured


def test_estimated_alignment_without_probe_uses_estimates(tmp_path) -> None:
    audio = tmp_path / "bed.mp3"
    audio.write_bytes(b"fake")
    # No ffprobe in this environment: probe returns None, estimates rule.
    aligner = EstimatedSpeechAligner(_estimator({"第一句": 1.5, "第二句": 2.5}))

    segments = aligner.align(
        audio_path=str(audio),
        lines=[
            {"segment_id": "a", "character_id": "c", "text": "第一句"},
            {"segment_id": "b", "character_id": "c", "text": "第二句"},
        ],
    )
    assert segments[0].end_time == pytest.approx(1.5)
    assert segments[1].end_time == pytest.approx(4.0)


def test_empty_lines_yield_no_segments(tmp_path) -> None:
    aligner = EstimatedSpeechAligner(_estimator({}))
    assert aligner.align(audio_path=str(tmp_path / "x.mp3"), lines=[]) == []


def test_low_confidence_ids_flags_the_estimated_band() -> None:
    segments = EstimatedSpeechAligner(_estimator({})).align(
        audio_path="x",
        lines=[{"segment_id": "a", "character_id": "c", "text": "hi"}],
    )
    # Estimated confidence sits below the threshold: lip-sync must ask for
    # better alignment first (or explicitly accept the band).
    assert low_confidence_ids(segments) == ["a"]


def test_factory_falls_back_to_estimated_without_whisperx(monkeypatch) -> None:
    settings = Settings(
        agent_runtime_mode="fake", speech_alignment_engine="whisperx"
    )
    # Force the import to fail (whisperX is not a dependency here).
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "whisperx":
            raise ImportError("no whisperx")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    aligner = build_speech_aligner(settings)
    assert aligner.name == ALIGN_SOURCE_ESTIMATED


def test_whisperx_aligner_fails_closed_without_the_dependency() -> None:
    aligner = WhisperXAligner(Settings(agent_runtime_mode="fake"))
    with pytest.raises(SpeechAlignmentError) as exc:
        aligner.align(audio_path="x", lines=LINES)
    assert exc.value.code == "alignment_engine_unavailable"


# ---------------------------------------------------------------------------
# C-mode bridge + endpoint
# ---------------------------------------------------------------------------


def test_to_dialogue_lines_carries_alignment_through() -> None:
    segments = [
        AlignedSegmentFor("a", "char_a", "你好", 0.0, 1.5, 0.9, "whisperx"),
        AlignedSegmentFor("b", "char_b", "好久不见", 1.5, 3.0, 0.9, "whisperx"),
    ]
    lines = to_dialogue_lines(segments)
    assert lines == [
        {"character_id": "char_a", "text": "你好", "start_time": 0.0, "end_time": 1.5},
        {"character_id": "char_b", "text": "好久不见", "start_time": 1.5, "end_time": 3.0},
    ]


def AlignedSegmentFor(segment_id, character_id, text, start, end, conf, source):
    return AlignedSegment(
        segment_id=segment_id,
        character_id=character_id,
        text=text,
        start_time=start,
        end_time=end,
        confidence=conf,
        align_source=source,
    )


def _aligned_audio(tmp_path):
    audio = tmp_path / "bed.mp3"
    audio.write_bytes(b"fake")
    return str(audio)


def test_align_speech_endpoint_reports_the_estimated_engine(tmp_path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    response = client.post(
        "/scene-3d/align-speech",
        json={
            "audio_path": _aligned_audio(tmp_path),
            "lines": [
                {"character_id": "char_a", "text": "就是这里"},
                {"character_id": "char_b", "text": "你确定吗"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["align_source"] == "estimated"
    assert len(body["segments"]) == 2
    # Estimated alignment is honestly flagged, never passed as measured.
    assert body["low_confidence_ids"]
    assert any("estimated" in warning for warning in body["warnings"])


def test_align_speech_endpoint_rejects_missing_audio(tmp_path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)

    response = client.post(
        "/scene-3d/align-speech",
        json={"audio_path": str(tmp_path / "nope.mp3"), "lines": [{"character_id": "c", "text": "hi"}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "alignment_audio_missing"


def test_c_mode_chain_alignment_feeds_lip_sync(tmp_path, monkeypatch) -> None:
    """The C mode end to end without torch: estimated alignment produces
    dialogue lines that drive the lip-sync merge, and the report says which
    engine ran."""

    from app.services.scene3d.dialogue_lipsync_service import apply_dialogue_lip_sync

    monkeypatch.setattr(
        "app.services.scene3d.speech_alignment.probe_audio_duration_seconds",
        lambda path, ffprobe_path="ffprobe": 4.0,
    )
    aligner = EstimatedSpeechAligner(
        _estimator({"你好": 1.0, "好久不见": 3.0})
    )
    segments = aligner.align(
        audio_path=_aligned_audio(tmp_path),
        lines=[
            {"segment_id": "s0", "character_id": "char_a", "text": "你好"},
            {"segment_id": "s1", "character_id": "char_b", "text": "好久不见"},
        ],
    )
    script = SceneScriptRoot.model_validate(
        {
            "scene": {"name": "lab", "environment": "indoor", "lighting": "cool", "duration": 4, "frame_rate": 30},
            "characters": [
                {"id": "char_a", "type": "lowpoly_human", "appearance": {"color": "#E74C3C"}, "keyframes": [{"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}]},
                {"id": "char_b", "type": "lowpoly_human", "appearance": {"color": "#3498DB"}, "keyframes": [{"frame": 0, "position": [1, 0, 0], "rotation_y": 0, "action": "stand"}]},
            ],
            "props": [], "environment": [],
            "cameras": [{"id": "cam1", "shot_type": "wide", "keyframes": [{"frame": 0, "position": [8, -10, 5], "look_at": [0, 0, 1]}]}],
            "shots": [{"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 119}],
            "speech_bindings": [],
        }
    )
    result = apply_dialogue_lip_sync(script, to_dialogue_lines(segments))
    talk_frames = [
        kf.frame
        for kf in result.scene_script.characters[0].keyframes
        if kf.action == "talk"
    ]
    assert talk_frames, "the aligned line drove lip-sync keyframes"
    assert result.summary["duration_source"] == "aligned"
    assert result.summary["pretimed_line_count"] == 2


# ---------------------------------------------------------------------------
# B-mode regeneration: weak lines are re-measured, not silently trusted
# ---------------------------------------------------------------------------


def test_b_mode_regeneration_keeps_the_start_and_resizes_the_duration() -> None:
    segments = [
        AlignedSegmentFor("weak", "char_a", "就是这里", 1.0, 1.4, 0.3, "whisperx"),
        AlignedSegmentFor("strong", "char_a", "后面那句", 2.0, 3.5, 0.9, "whisperx"),
    ]
    result = regenerate_low_confidence_segments(
        segments,
        duration_estimator=_estimator({"就是这里": 0.8}),
        duration_source="measured",
    )
    assert result.regenerated_ids == ["weak"]
    by_id = {segment.segment_id: segment for segment in result.segments}
    # The START is what the aligner actually found; the DURATION is the new
    # measurement (0.8s from 1.0), and it is reported.
    assert by_id["weak"].start_time == 1.0
    assert by_id["weak"].end_time == 1.8
    assert by_id["weak"].regenerated is True
    assert by_id["weak"].duration_source == "measured"
    # The strong segment is untouched.
    assert by_id["strong"].end_time == 3.5
    assert by_id["strong"].regenerated is False
    # The confidence STAYS low: re-measuring the length does not make the
    # start trustworthy.
    assert by_id["weak"].confidence == 0.3
    assert result.warnings == []


def test_b_mode_regeneration_clamps_against_the_next_line_and_says_so() -> None:
    segments = [
        AlignedSegmentFor("weak", "char_a", "長長長的一句", 1.0, 1.4, 0.3, "whisperx"),
        AlignedSegmentFor("strong", "char_a", "下一句", 1.6, 3.0, 0.9, "whisperx"),
    ]
    result = regenerate_low_confidence_segments(
        segments,
        # The measurement says 2.0s but only 0.6s of room remains.
        duration_estimator=_estimator({"長長長的一句": 2.0}),
        duration_source="measured",
    )
    by_id = {segment.segment_id: segment for segment in result.segments}
    # Clamped, never overlapping the next line.
    assert by_id["weak"].end_time == 1.6
    assert by_id["weak"].regenerated is True
    # And the clamp is REPORTED with the segment named.
    assert len(result.warnings) == 1
    assert "長長長的一句" in result.warnings[0]
    assert "钳制" in result.warnings[0]


def test_b_mode_regeneration_reports_the_estimated_source_honestly() -> None:
    segments = [
        AlignedSegmentFor("weak", "char_a", "就是这里", 0.0, 1.0, 0.3, "estimated"),
    ]
    result = regenerate_low_confidence_segments(
        segments,
        duration_estimator=_estimator({}),
        duration_source="estimated",
    )
    assert result.duration_source == "estimated"
    assert result.segments[0].duration_source == "estimated"
    # An estimate must never be dressed up as a measurement.
    assert result.segments[0].regenerated is True


def test_b_mode_regeneration_leaves_a_clean_alignment_alone() -> None:
    segments = [
        AlignedSegmentFor("a", "char_a", "你好", 0.0, 1.5, 0.95, "whisperx"),
        AlignedSegmentFor("b", "char_b", "好久不见", 1.5, 3.0, 0.95, "whisperx"),
    ]
    result = regenerate_low_confidence_segments(
        segments,
        duration_estimator=_estimator({}),
        duration_source="measured",
    )
    assert result.regenerated_ids == []
    assert result.segments == segments
    assert result.warnings == []
    assert result.duration_source == "measured"


def test_b_mode_regeneration_survives_the_last_line_being_weak() -> None:
    segments = [
        AlignedSegmentFor("a", "char_a", "你好", 0.0, 1.5, 0.95, "whisperx"),
        AlignedSegmentFor("last", "char_a", "收尾", 2.0, 2.4, 0.3, "whisperx"),
    ]
    result = regenerate_low_confidence_segments(
        segments,
        duration_estimator=_estimator({"收尾": 1.2}),
        duration_source="measured",
    )
    by_id = {segment.segment_id: segment for segment in result.segments}
    # No next line to clamp against: the measurement simply extends the line.
    assert by_id["last"].end_time == 3.2
    assert result.warnings == []


def test_endpoint_regenerates_low_confidence_lines_by_default(tmp_path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint
    from app.services.scene3d import speech_alignment

    audio = _aligned_audio(tmp_path)

    class _Estimated:
        name = "estimated"

        def align(self, *, audio_path, lines, speech_only=True):
            return [
                AlignedSegmentFor("seg_000", "char_a", "就是这里", 0.0, 1.0, 0.4, "estimated"),
                AlignedSegmentFor("seg_001", "char_a", "下一句", 1.0, 2.0, 0.4, "estimated"),
            ]

    class _Engine:
        def estimate_duration(self, text: str) -> float:
            return 0.75

    monkeypatch.setattr(speech_alignment, "build_speech_aligner", lambda settings: _Estimated())
    monkeypatch.setattr(
        speech_alignment,
        "probe_audio_duration_seconds",
        lambda *args, **kwargs: 2.0,
    )
    monkeypatch.setattr(
        "app.services.scene3d.tts_engine_factory.create_tts_engine_from_settings",
        lambda settings: _Engine(),
    )

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)
    response = client.post(
        "/scene-3d/align-speech",
        json={"audio_path": audio, "lines": [{"character_id": "char_a", "text": "就是这里"}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # Automatic by default: both estimated-confidence lines were re-measured.
    assert body["regenerated_ids"] == ["seg_000", "seg_001"]
    assert body["regeneration_duration_source"] == "measured"
    by_id = {segment["segment_id"]: segment for segment in body["segments"]}
    assert by_id["seg_000"]["regenerated"] is True
    assert by_id["seg_000"]["end_time"] == 0.75
    assert any("B 模式重测" in warning for warning in body["warnings"])


def test_endpoint_regeneration_can_be_opted_out_of(tmp_path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import scene_3d as scene_3d_endpoint
    from app.services.scene3d import speech_alignment

    audio = _aligned_audio(tmp_path)

    class _Estimated:
        name = "estimated"

        def align(self, *, audio_path, lines, speech_only=True):
            return [
                AlignedSegmentFor("seg_000", "char_a", "就是这里", 0.0, 1.0, 0.4, "estimated"),
            ]

    monkeypatch.setattr(speech_alignment, "build_speech_aligner", lambda settings: _Estimated())
    monkeypatch.setattr(
        speech_alignment,
        "probe_audio_duration_seconds",
        lambda *args, **kwargs: 2.0,
    )

    app = FastAPI()
    app.include_router(scene_3d_endpoint.router)
    client = TestClient(app)
    response = client.post(
        "/scene-3d/align-speech",
        json={
            "audio_path": audio,
            "lines": [{"character_id": "char_a", "text": "就是这里"}],
            "regenerate_low_confidence": False,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["regenerated_ids"] == []
    assert body["regeneration_duration_source"] is None
    # The raw alignment boundaries arrive untouched.
    assert body["segments"][0]["end_time"] == 1.0


def test_b_mode_regeneration_clamps_the_last_line_to_the_bed() -> None:
    segments = [
        AlignedSegmentFor("a", "char_a", "你好", 0.0, 1.5, 0.95, "whisperx"),
        AlignedSegmentFor("last", "char_a", "收尾的一句很長", 2.0, 2.4, 0.3, "whisperx"),
    ]
    result = regenerate_low_confidence_segments(
        segments,
        duration_estimator=_estimator({"收尾的一句很長": 3.0}),
        duration_source="measured",
        bed_duration=4.0,
    )
    by_id = {segment.segment_id: segment for segment in result.segments}
    # The bed ends at 4.0s: the last line may not run past the take.
    assert by_id["last"].end_time == 4.0
    assert len(result.warnings) == 1
    assert "收尾的一句很長" in result.warnings[0]
