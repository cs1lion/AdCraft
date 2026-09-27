"""Tests for the Continuity State ↔ Transition Intent reconciliation (V0.2 §13 第 4 问).

The doc asks to connect the two halves: Continuity State answers "什么必须连续"
and Transition Intent answers "什么发生改变". The reason they must be connected
is the ambiguity each one lives with alone:

* a facing flip nobody declared reads as a BUG;
* a declared 连续运动 over a flipped keyframe reads as FINE.

So these tests lock the two directions of that join — a change reading EXPLAINS
a continuity finding, a continuity reading is CONTRADICTED BY one — plus the
silences that keep the check from becoming noise.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.scene_script import SceneShot
from app.services.scene3d.emotion_continuity import check_emotion_continuity
from app.services.scene3d.speech_orchestration import SpeechSegment
from app.services.scene3d.transition_intent_reconciliation import (
    reconcile_transition_intents,
)


@dataclass
class _BlockingIssue:
    boundary: str
    code: str


def _shot(
    shot_id: str,
    start: int,
    intent: str | None = None,
    end_frame: int | None = None,
) -> SceneShot:
    payload = {
        "id": shot_id,
        "camera": "cam",
        "start_frame": start,
        "end_frame": end_frame if end_frame is not None else start + 89,
    }
    if intent is not None:
        payload["transition_intent"] = intent
    return SceneShot.model_validate(payload)


class TestAChangeReadingExplainsAContinuityFinding:
    def test_time_jump_absorbs_a_facing_flip(self) -> None:
        notes = reconcile_transition_intents(
            shots=[_shot("s1", 0), _shot("s2", 90, "time_jump")],
            blocking_issues=[_BlockingIssue(boundary="s1→s2", code="facing_flip")],
        )
        assert [note.code for note in notes] == ["transition_intent_explains_continuity"]
        note = notes[0]
        assert note.shot_id == "s2"
        assert note.severity == "info"
        assert "变化是读法的一部分" in note.message

    def test_angle_switch_absorbs_a_position_jump(self) -> None:
        notes = reconcile_transition_intents(
            shots=[_shot("s1", 0), _shot("s2", 90, "angle_switch")],
            blocking_issues=[_BlockingIssue(boundary="s1→s2", code="position_jump")],
        )
        assert [note.code for note in notes] == ["transition_intent_explains_continuity"]
        assert "视角切换" in notes[0].message

    def test_an_emotion_advisory_is_joined_on_the_shot_it_lands_on(self) -> None:
        """The emotion gate names a shot, not a boundary — the join uses it."""

        # Two lines with DIFFERENT emotions and a gap too short to hide the
        # cut in — the whiplash the gate exists to notice.
        segments = [
            SpeechSegment(
                segment_id="a", character_id="lin", text="走！",
                start_time=0.0, end_time=1.0, emotion="calm",
            ),
            SpeechSegment(
                segment_id="b", character_id="lin", text="为什么",
                start_time=1.2, end_time=2.0, emotion="angry",
            ),
        ]
        # The cut must fall in the GAP between the two lines (1.0–1.2s), so
        # the shot ends at 35 frames (35/30 = 1.17s).
        advisories = check_emotion_continuity(
            shots=[_shot("s1", 0, end_frame=35), _shot("s2", 36)],
            segments=segments,
            frame_rate=30,
        )
        assert advisories, "fixture should produce an emotion advisory"
        notes = reconcile_transition_intents(
            shots=[_shot("s1", 0), _shot("s2", 90, "time_jump")],
            emotion_advisories=advisories,
        )
        assert [note.code for note in notes] == ["transition_intent_explains_continuity"]


class TestAContinuityReadingIsContradictedByAFinding:
    def test_continuous_motion_over_a_facing_flip_is_called_out(self) -> None:
        notes = reconcile_transition_intents(
            shots=[_shot("s1", 0), _shot("s2", 90, "continuous_motion")],
            blocking_issues=[_BlockingIssue(boundary="s1→s2", code="facing_flip")],
        )
        assert [note.code for note in notes] == [
            "transition_intent_contradicts_continuity"
        ]
        note = notes[0]
        assert note.severity == "warning"
        assert "登记与关键帧互相矛盾" in note.message
        assert "时间跳跃" in note.remedy

    def test_gaze_closeup_over_a_position_jump_is_called_out(self) -> None:
        notes = reconcile_transition_intents(
            shots=[_shot("s1", 0), _shot("s2", 90, "gaze_closeup")],
            blocking_issues=[_BlockingIssue(boundary="s1→s2", code="position_jump")],
        )
        assert [note.code for note in notes] == [
            "transition_intent_contradicts_continuity"
        ]


class TestSilences:
    def test_a_clean_boundary_produces_no_note(self) -> None:
        notes = reconcile_transition_intents(
            shots=[_shot("s1", 0), _shot("s2", 90, "continuous_motion")],
            blocking_issues=[],
        )
        assert notes == []

    def test_a_shot_with_no_declaration_is_not_interrogated(self) -> None:
        notes = reconcile_transition_intents(
            shots=[_shot("s1", 0), _shot("s2", 90)],
            blocking_issues=[_BlockingIssue(boundary="s1→s2", code="facing_flip")],
        )
        assert notes == []

    def test_the_first_shot_has_no_entry_boundary(self) -> None:
        """A reading on shot 1 has nothing to reconcile against."""

        notes = reconcile_transition_intents(
            shots=[_shot("s1", 0, "time_jump")],
            blocking_issues=[_BlockingIssue(boundary="s1→s2", code="facing_flip")],
        )
        assert notes == []

    def test_an_unknown_reading_is_left_alone(self) -> None:
        """A machine-proposed reading nobody classified is not guessed at."""

        notes = reconcile_transition_intents(
            shots=[_shot("s1", 0), _shot("s2", 90, "llm_overhead_match_cut")],
            blocking_issues=[_BlockingIssue(boundary="s1→s2", code="facing_flip")],
        )
        assert notes == []

    def test_a_finding_on_another_boundary_is_not_borrowed(self) -> None:
        notes = reconcile_transition_intents(
            shots=[
                _shot("s1", 0),
                _shot("s2", 90),
                _shot("s3", 180, "time_jump"),
            ],
            blocking_issues=[_BlockingIssue(boundary="s1→s2", code="facing_flip")],
        )
        # The finding is on s1→s2, not on the boundary that enters s3.
        assert notes == []

    def test_no_findings_at_all_is_no_notes(self) -> None:
        assert reconcile_transition_intents(shots=[_shot("s1", 0), _shot("s2", 90, "time_jump")]) == []
