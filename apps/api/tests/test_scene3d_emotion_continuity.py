"""Tests for emotion continuity — the Continuity State 情绪 dimension (V0.2 §5).

Locks the question (not the answer): a whiplash across a cut with no pause to
read as intentional is ASKED about; with a pause, silence is doing the work and
nobody asks. Same emotions, missing emotions, and empty scenes are all silent.
"""

from __future__ import annotations


from app.schemas.scene_script import SceneShot
from app.services.scene3d.emotion_continuity import (
    check_emotion_continuity,
    normalize_emotion,
)
from app.services.scene3d.speech_orchestration import SpeechSegment


def _line(
    segment_id: str,
    start: float,
    end: float,
    emotion: str | None,
    text: str = "台词",
) -> SpeechSegment:
    return SpeechSegment(
        segment_id=segment_id,
        character_id="lin",
        text=text,
        start_time=start,
        end_time=end,
        emotion=emotion,
    )


def _shot(shot_id: str = "shot1", end_frame: int = 90) -> SceneShot:
    return SceneShot(id=shot_id, camera="cam1", start_frame=0, end_frame=end_frame)


class TestNormalizeEmotion:
    def test_punctuation_and_case_carry_no_signal(self) -> None:
        assert normalize_emotion("紧张！") == normalize_emotion("紧张")
        assert normalize_emotion("Fear") == normalize_emotion("fear")
        assert normalize_emotion(None) == ""
        assert normalize_emotion("  ") == ""


class TestEmotionWhiplash:
    def test_a_flip_with_no_pause_is_asked_about(self) -> None:
        # The cut sits at 3.0s (frame 90): line 1 ends just before it, line 2
        # starts just after, with 0.05s between them.
        advisories = check_emotion_continuity(
            shots=[_shot()],
            segments=[
                _line("a", 2.4, 3.0, "恐惧"),
                _line("b", 3.05, 3.6, "狂喜"),
            ],
            frame_rate=30,
        )
        assert [advisory.code for advisory in advisories] == ["emotion_whiplash"]
        advisory = advisories[0]
        assert advisory.shot_id == "shot1"
        assert "恐惧" in advisory.message and "狂喜" in advisory.message
        # A question with a remedy, never a defect: the reveal reading is named.
        assert "有意的情绪转折" in advisory.remedy

    def test_a_pause_between_the_lines_excuses_the_flip(self) -> None:
        # Line 2 starts 1.05s after line 1 ends: time passed, mood may turn.
        advisories = check_emotion_continuity(
            shots=[_shot()],
            segments=[
                _line("a", 1.5, 2.9, "恐惧"),
                _line("b", 4.0, 5.5, "狂喜"),
            ],
            frame_rate=30,
        )
        assert advisories == []

    def test_a_line_straddling_the_cut_is_an_l_cut_not_a_whiplash(self) -> None:
        # The line keeps playing through the cut: same emotion on both sides,
        # so there is no hand-off to ask about.
        advisories = check_emotion_continuity(
            shots=[_shot()],
            segments=[
                _line("a", 0.0, 1.5, "恐惧"),
                _line("b", 2.9, 5.0, "狂喜"),
            ],
            frame_rate=30,
        )
        assert advisories == []

    def test_the_same_emotion_is_silent(self) -> None:
        advisories = check_emotion_continuity(
            shots=[_shot()],
            segments=[
                _line("a", 0.0, 2.8, "紧张"),
                _line("b", 2.9, 5.0, "紧张！"),
            ],
            frame_rate=30,
        )
        assert advisories == []

    def test_a_missing_emotion_is_silent(self) -> None:
        advisories = check_emotion_continuity(
            shots=[_shot()],
            segments=[
                _line("a", 0.0, 2.8, None),
                _line("b", 2.9, 5.0, "狂喜"),
            ],
            frame_rate=30,
        )
        assert advisories == []

    def test_only_the_cut_boundary_is_examined(self) -> None:
        # The flip happens INSIDE one shot (before the 6.0s cut): not this
        # check's business — the cut is where the state hand-off happens.
        advisories = check_emotion_continuity(
            shots=[_shot(end_frame=180)],
            segments=[
                _line("a", 0.0, 2.0, "恐惧"),
                _line("b", 2.1, 4.0, "狂喜"),
            ],
            frame_rate=30,
        )
        assert advisories == []

    def test_empty_inputs_are_silent(self) -> None:
        assert check_emotion_continuity(shots=[], segments=[_line("a", 0, 1, "x")], frame_rate=30) == []
        assert check_emotion_continuity(shots=[_shot()], segments=[], frame_rate=30) == []


class TestLipSyncSummaryWiring:
    def test_the_summary_carries_emotion_advisories(self) -> None:
        from app.services.scene3d.dialogue_lipsync_service import apply_dialogue_lip_sync

        script = {
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
            "shots": [
                {"id": "s1", "camera": "cam1", "start_frame": 0, "end_frame": 89},
                {"id": "s2", "camera": "cam1", "start_frame": 90, "end_frame": 179},
            ],
            "speech_bindings": [],
        }
        result = apply_dialogue_lip_sync(
            script,
            [
                # The estimator gives line 1 ~1.1s, so it ends just before the
                # 3.0s cut and line 2 starts 0.1s after it: no pause to excuse
                # the fear→elation flip.
                {"character_id": "lin", "text": "别出声。", "start_time": 1.8, "emotion": "恐惧"},
                {"character_id": "lin", "text": "成功了！", "start_time": 3.05, "emotion": "狂喜"},
            ],
        )
        advisories = result.summary.get("emotion_advisories")
        assert isinstance(advisories, list)
        # The 3.0s cut sits between the lines with no room for a pause, and the
        # emotions disagree: the question is asked.
        assert any(entry["code"] == "emotion_whiplash" for entry in advisories)
