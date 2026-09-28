"""Tests for the V3 ④ 台词即表演 gesture layer."""

from __future__ import annotations

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.gesture_performance import (
    gesture_keyframes_for_segment,
    merge_gestures_into_scene_script,
)
from app.services.scene3d.speech_orchestration import SpeechSegment


def _script() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(
        {
            "scene": {
                "name": "gesture",
                "environment": "indoor",
                "lighting": "neutral",
                "duration": 5,
                "frame_rate": 30,
            },
            "characters": [
                {
                    "id": "char1",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#8B4513", "height": 1.7, "scale": 1.0},
                    "keyframes": [
                        {"frame": 0, "position": [0.0, 1.0, 0.0], "rotation_y": 0.0, "action": "stand"},
                        {"frame": 150, "position": [0.0, 1.0, 0.0], "rotation_y": 0.0, "action": "stand"},
                    ],
                }
            ],
            "props": [],
            "environment": [],
            "cameras": [],
            "shots": [],
            "speech_bindings": [],
        }
    )


def _segment(emotion: str | None = None, text: str = "你好") -> SpeechSegment:
    return SpeechSegment(
        segment_id="seg1",
        character_id="char1",
        text=text,
        start_time=1.0,
        end_time=3.0,
        emotion=emotion,
    )


def test_neutral_line_produces_no_gestures() -> None:
    script = _script()
    keyframes = gesture_keyframes_for_segment(
        _segment(), script.characters[0], frame_rate=30, total_frames=150
    )
    assert keyframes == []


def test_strong_emotion_adds_lean_keyframes() -> None:
    script = _script()
    keyframes = gesture_keyframes_for_segment(
        _segment(emotion="angry"), script.characters[0], frame_rate=30, total_frames=150
    )
    assert len(keyframes) == 2
    # Start leans forward (+15°), end returns to the authored yaw.
    assert keyframes[0].rotation_y == 15.0
    assert keyframes[1].rotation_y == 0.0
    assert all(kf.action == "gesture" for kf in keyframes)


def test_negation_text_adds_shake_keyframes() -> None:
    script = _script()
    keyframes = gesture_keyframes_for_segment(
        _segment(text="不，我不去"), script.characters[0], frame_rate=30, total_frames=150
    )
    # A shake is a 3-frame oscillation at the segment midpoint.
    assert len(keyframes) == 3
    mid = keyframes[1]
    assert mid.rotation_y > 0
    assert all(kf.action == "gesture" for kf in keyframes)


def test_merge_gestures_keeps_authored_keyframes() -> None:
    script = _script()
    before = [kf for char in script.characters for kf in char.keyframes]
    merged = merge_gestures_into_scene_script(
        script, [_segment(emotion="angry")]
    )
    after = [kf for char in merged.characters for kf in char.keyframes]
    # Authored frames survive: the merge only ADDS gesture frames.
    authored_frames = {kf.frame for kf in before}
    assert authored_frames <= {kf.frame for kf in after}
    # The gesture frames carry the gesture action.
    gesture_frames = [kf for kf in after if kf.action == "gesture"]
    assert gesture_frames


def test_merge_gestures_noop_for_unknown_speaker() -> None:
    script = _script()
    unknown = SpeechSegment(
        segment_id="seg_x",
        character_id="char_ghost",
        text="你好",
        start_time=0.5,
        end_time=1.0,
        emotion="angry",
    )
    merged = merge_gestures_into_scene_script(script, [unknown])
    assert merged is script
