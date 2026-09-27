"""Tests for the QA registry and its phase-1 checks (ADR 0003 §5).

Locks the contract the ADR asks for: named, ordered, versioned checks;
structured outcomes with reasons; duplicate names fail loudly; and — the one
that matters most — a check that cannot run degrades to ``warn`` WITH a reason
instead of reporting a pass it did not measure.
"""

from __future__ import annotations

import pytest

from app.services.dialogue.speech_qa_checks import (
    DURATION_SANITY_RATIO_RANGE,
    BoundSpeechVsShotDurationCheck,
    LoudnessTargetCheck,
    SpeechDurationSanityCheck,
    SpeechTimelineConsistencyCheck,
    build_speech_qa_registry,
)
from app.services.dialogue.v2_qa_registry import (
    QA_FAIL,
    QA_PASS,
    QA_WARN,
    QaOutcome,
    QaRegistry,
    QaSubject,
)
from app.services.scene3d.speech_orchestration import SpeechSegment


class _StubCheck:
    """A minimal check with a unique name per instance."""

    version = "1"

    def __init__(self, name: str, status: str = QA_PASS) -> None:
        self.name = name
        self._status = status

    def run(self, subject: QaSubject) -> QaOutcome:
        return QaOutcome(check=self.name, status=self._status, reason="stub")


class TestRegistryMechanics:
    def test_registration_is_ordered_and_named(self) -> None:
        registry = QaRegistry()
        registry.register(SpeechDurationSanityCheck())
        registry.register(SpeechTimelineConsistencyCheck())
        assert registry.names == (
            "speech_duration_sanity",
            "speech_timeline_consistency",
        )

    def test_a_duplicate_name_fails_loudly(self) -> None:
        registry = QaRegistry().register(SpeechDurationSanityCheck())
        with pytest.raises(ValueError, match="duplicate"):
            registry.register(SpeechDurationSanityCheck())

    def test_an_unnamed_check_fails_loudly(self) -> None:
        class _Nameless:
            name = ""
            version = "1"

            def run(self, subject: QaSubject) -> QaOutcome:  # pragma: no cover
                raise AssertionError("never reached")

        with pytest.raises(ValueError, match="name"):
            QaRegistry().register(_Nameless())  # type: ignore[arg-type]

    def test_the_report_aggregates_statuses(self) -> None:
        registry = QaRegistry()
        registry.register(_StubCheck("stub_pass", QA_PASS))
        registry.register(_StubCheck("stub_warn", QA_WARN))
        report = registry.report(QaSubject())
        assert report["warned"] == ["stub_warn"]
        assert report["failed"] == []
        assert report["passed"] is True

    def test_a_failure_fails_the_report(self) -> None:
        registry = QaRegistry().register(_StubCheck("stub_fail", QA_FAIL))
        report = registry.report(QaSubject())
        assert report["passed"] is False
        assert report["failed"] == ["stub_fail"]


class TestSpeechDurationSanity:
    def test_a_matching_measured_duration_passes(self) -> None:
        outcome = SpeechDurationSanityCheck().run(
            QaSubject(
                measured_durations=[
                    {"segment_id": "a", "measured": 1.0, "estimated": 1.0}
                ]
            )
        )
        assert outcome.status == QA_PASS
        assert "一致" in outcome.reason

    def test_an_outlier_warns_with_the_numbers(self) -> None:
        outcome = SpeechDurationSanityCheck().run(
            QaSubject(
                measured_durations=[
                    {"segment_id": "a", "measured": 3.0, "estimated": 1.0}
                ]
            )
        )
        assert outcome.status == QA_WARN
        outliers = outcome.details["outliers"]
        assert isinstance(outliers, list) and len(outliers) == 1
        assert outliers[0]["ratio"] == pytest.approx(3.0)

    def test_the_estimate_mode_passes_as_not_applicable(self) -> None:
        outcome = SpeechDurationSanityCheck().run(QaSubject())
        assert outcome.status == QA_PASS
        assert "不适用" in outcome.reason

    def test_the_range_boundaries_are_lived(self) -> None:
        low, high = DURATION_SANITY_RATIO_RANGE
        assert SpeechDurationSanityCheck().run(
            QaSubject(measured_durations=[{"segment_id": "a", "measured": low, "estimated": 1.0}])
        ).status == QA_PASS
        assert SpeechDurationSanityCheck().run(
            QaSubject(measured_durations=[{"segment_id": "a", "measured": high, "estimated": 1.0}])
        ).status == QA_PASS
        assert SpeechDurationSanityCheck().run(
            QaSubject(measured_durations=[{"segment_id": "a", "measured": high * 1.01, "estimated": 1.0}])
        ).status == QA_WARN


def _segment(segment_id: str, start: float, end: float, character_id: str = "lin"):
    return SpeechSegment(
        segment_id=segment_id,
        character_id=character_id,
        text="台词",
        start_time=start,
        end_time=end,
    )


class TestBoundSpeechVsShot:
    def test_no_bound_bindings_is_not_applicable(self) -> None:
        outcome = BoundSpeechVsShotDurationCheck().run(
            QaSubject(
                speech_bindings=[{"character": "lin", "mode": "free"}],
                segments=[_segment("a", 0, 1)],
                shots=[{"id": "s1", "start_seconds": 0.0, "end_seconds": 2.0}],
            )
        )
        assert outcome.status == QA_PASS
        assert "不适用" in outcome.reason

    def test_a_bound_line_past_its_shot_warns(self) -> None:
        outcome = BoundSpeechVsShotDurationCheck().run(
            QaSubject(
                speech_bindings=[{"character": "lin", "mode": "bound"}],
                segments=[_segment("a", 1.0, 3.5)],
                shots=[{"id": "s1", "start_seconds": 0.0, "end_seconds": 3.0}],
            )
        )
        assert outcome.status == QA_WARN
        overruns = outcome.details["overruns"]
        assert isinstance(overruns, list) and overruns[0]["shot_id"] == "s1"

    def test_a_bound_line_inside_its_shot_passes(self) -> None:
        outcome = BoundSpeechVsShotDurationCheck().run(
            QaSubject(
                speech_bindings=[{"character": "lin", "mode": "bound"}],
                segments=[_segment("a", 1.0, 2.5)],
                shots=[{"id": "s1", "start_seconds": 0.0, "end_seconds": 3.0}],
            )
        )
        assert outcome.status == QA_PASS

    def test_another_characters_bound_binding_does_not_capture_the_line(self) -> None:
        outcome = BoundSpeechVsShotDurationCheck().run(
            QaSubject(
                speech_bindings=[{"character": "su", "mode": "bound"}],
                segments=[_segment("a", 1.0, 3.5, character_id="lin")],
                shots=[{"id": "s1", "start_seconds": 0.0, "end_seconds": 3.0}],
            )
        )
        assert outcome.status == QA_PASS


class TestTimelineConsistencyEntry:
    def test_findings_travel_into_the_outcome(self) -> None:
        outcome = SpeechTimelineConsistencyCheck().run(
            QaSubject(
                timeline_issues=[
                    {"issue_type": "overlap", "description": "两句重叠", "segments": "a,b"}
                ]
            )
        )
        assert outcome.status == QA_WARN
        assert outcome.details["issues"][0]["issue_type"] == "overlap"

    def test_a_clean_timeline_passes(self) -> None:
        outcome = SpeechTimelineConsistencyCheck().run(QaSubject())
        assert outcome.status == QA_PASS


class TestLoudnessProbe:
    def test_no_audio_warns_instead_of_claiming_a_pass(self) -> None:
        outcome = LoudnessTargetCheck().run(QaSubject())
        assert outcome.status == QA_WARN
        assert "未测量" in outcome.reason

    def test_a_missing_ffmpeg_warns_with_the_reason(self, monkeypatch) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: None)
        outcome = LoudnessTargetCheck().run(QaSubject(audio_path="/tmp/bed.mp3"))
        assert outcome.status == QA_WARN
        assert "ffmpeg" in outcome.reason

    def test_the_ebur128_summary_parses(self) -> None:
        from app.services.dialogue.speech_qa_checks import _parse_integrated_loudness

        stderr = (
            "[Parsed_ebur128_0 @ 0x1] Summary:\n"
            "  Integrated loudness:\n"
            "    I:         -18.2 LUFS\n"
        )
        assert _parse_integrated_loudness(stderr) == pytest.approx(-18.2)

    def test_no_summary_line_parses_to_none(self) -> None:
        from app.services.dialogue.speech_qa_checks import _parse_integrated_loudness

        assert _parse_integrated_loudness("garbage") is None


class TestRegistryOrdering:
    def test_the_phase_one_registry_is_the_documented_order(self) -> None:
        assert build_speech_qa_registry().names == (
            "speech_duration_sanity",
            "bound_speech_vs_shot_duration",
            "speech_timeline_consistency",
            "speech_loudness_target",
        )

    def test_every_entry_reports_itself_even_with_an_empty_subject(self) -> None:
        report = build_speech_qa_registry().report(QaSubject())
        # Nothing measured, nothing bound, no audio: three not-applicable
        # passes and one honest "not measured" warn.
        statuses = [outcome["status"] for outcome in report["outcomes"]]
        assert statuses == [QA_PASS, QA_PASS, QA_PASS, QA_WARN]


# ---------------------------------------------------------------------------
# The lip-sync summary publishes the report
# ---------------------------------------------------------------------------


def _script() -> dict[str, object]:
    return {
        "scene": {"name": "lab", "environment": "indoor", "lighting": "cool", "duration": 6, "frame_rate": 30},
        "characters": [
            {
                "id": "lin",
                "type": "lowpoly_human",
                "appearance": {"color": "#E74C3C"},
                "keyframes": [{"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}],
            }
        ],
        "props": [],
        "environment": [],
        "cameras": [
            {"id": "cam1", "shot_type": "wide", "keyframes": [{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}]}
        ],
        "shots": [{"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 179}],
        "speech_bindings": [],
    }


def test_the_lipsync_summary_carries_the_qa_report() -> None:
    from app.services.scene3d.dialogue_lipsync_service import apply_dialogue_lip_sync

    result = apply_dialogue_lip_sync(
        _script(), [{"character_id": "lin", "text": "就是这里", "start_time": 0.5}]
    )
    report = result.summary["qa_report"]
    assert report["passed"] is True
    assert len(report["outcomes"]) == 4
    # No audio was offered, so the loudness entry says so rather than passing.
    loudness = next(o for o in report["outcomes"] if o["check"] == "speech_loudness_target")
    assert loudness["status"] == QA_WARN
    assert "未测量" in loudness["reason"]


# ---------------------------------------------------------------------------
# The loudness probe against a real binary (engineering standard §3)
# ---------------------------------------------------------------------------


def _tone(tmp_path, seconds: float = 1.0, amplitude: int = 9000) -> str:
    import math
    import struct
    import wave

    path = tmp_path / "bed.wav"
    rate = 8000
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    int(amplitude * math.sin(2 * math.pi * 220 * index / rate)),
                )
                for index in range(int(rate * seconds))
            )
        )
    return str(path)


@pytest.mark.media
def test_the_loudness_probe_measures_a_real_file(tmp_path) -> None:
    """The real ebur128 probe: a quiet, loud, and loudness-free bed each get a
    verdict with the measured number inside — never a fabricated pass."""

    import shutil

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")

    from app.services.dialogue.speech_qa_checks import (
        SPEECH_LOUDNESS_TARGET_LUFS,
        LoudnessTargetCheck,
    )

    # A loud tone lands above the speech target: the probe must WARN and carry
    # the measured value.
    loud = LoudnessTargetCheck().run(QaSubject(audio_path=_tone(tmp_path, amplitude=30000)))
    assert loud.status == QA_WARN
    assert "LUFS" in loud.reason
    assert loud.details["integrated_lufs"] > SPEECH_LOUDNESS_TARGET_LUFS

    # A very quiet tone lands far below it: also a warn, on the other side.
    quiet = LoudnessTargetCheck().run(QaSubject(audio_path=_tone(tmp_path, amplitude=60)))
    assert quiet.status == QA_WARN
    assert quiet.details["integrated_lufs"] < SPEECH_LOUDNESS_TARGET_LUFS

    # An unreadable file degrades with a reason rather than crashing.
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not audio")
    outcome = LoudnessTargetCheck().run(QaSubject(audio_path=str(broken)))
    assert outcome.status == QA_WARN
    assert outcome.reason
