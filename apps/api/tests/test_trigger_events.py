"""Tests for the when/then trigger event expansion.

Locks the trigger vocabulary and the then-op expansion contract: a trigger
event expands into a deterministic ops batch that rides the existing gate,
with no new op kinds or schema fields.

The failure paths are locked as hard as the happy one: every argument the
director must supply, every frame range, and the script's character list
are checked *before* anything is expanded, because a trigger that cannot
fire is worse than a rejected one — the director sees nothing happen.
"""

from __future__ import annotations

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.trigger_events import (
    CHARACTER_TRIGGERS,
    THEN_OP_KINDS,
    TriggerError,
    expand_trigger_event,
    trigger_frame_to_keyframe,
)


def script() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(
        {
            "scene": {"name": "trigger-test", "environment": "indoor", "duration": 6, "frame_rate": 30},
            "characters": [
                {
                    "id": "char_a",
                    "type": "lowpoly_human",
                    "appearance": {"color": "#E74C3C"},
                    "keyframes": [
                        {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}
                    ],
                }
            ],
            "cameras": [
                {
                    "id": "cam1",
                    "shot_type": "wide",
                    "keyframes": [
                        {"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}
                    ],
                }
            ],
            "shots": [{"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 179}],
        }
    )


def test_trigger_sit_expands_cleanly() -> None:
    event = expand_trigger_event(
        trigger="sit",
        trigger_target_id="char_a",
        trigger_scene_script=script(),
        trigger_frame=45,
        then_ops=[
            {"op": "add_keyframe", "kind": "camera", "id": "cam1", "frame": 45,
             "position": [3, -3, 1.5], "look_at": [0, 0, 1.0]},
        ],
        then_frame=45,
    )
    assert event["trigger"] == "sit"
    assert event["trigger_frame"] == 45
    assert len(event["operations"]) == 1
    assert event["operations"][0]["op"] == "add_keyframe"


def test_trigger_arrive_requires_position() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="arrive",
            trigger_target_id="char_a",
            trigger_scene_script=script(),
            trigger_frame=30,
            then_ops=[],
            then_frame=30,
        )
    assert exc.value.code == "trigger_target_missing"


def test_trigger_arrive_expands_with_position() -> None:
    event = expand_trigger_event(
        trigger="arrive",
        trigger_target_id="char_a",
        trigger_scene_script=script(),
        trigger_frame=30,
        trigger_target_position=[6.0, 0.0, 0.0],
        then_ops=[
            {"op": "set_camera", "kind": "camera", "id": "cam1",
             "shot_type": "closeup"},
        ],
        then_frame=30,
    )
    assert event["trigger_target_position"] == [6.0, 0.0, 0.0]
    assert len(event["operations"]) == 1


def test_trigger_face_requires_yaw() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="face",
            trigger_target_id="char_a",
            trigger_scene_script=script(),
            trigger_frame=30,
            then_ops=[],
            then_frame=30,
        )
    assert exc.value.code == "trigger_target_missing"


def test_trigger_line_spoken_expands() -> None:
    event = expand_trigger_event(
        trigger="line_spoken",
        trigger_target_id="char_a",
        trigger_scene_script=script(),
        trigger_frame=60,
        then_ops=[
            {"op": "add_keyframe", "kind": "camera", "id": "cam1", "frame": 60,
             "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]},
        ],
        then_frame=60,
    )
    assert event["trigger"] == "line_spoken"
    assert event["then_frame"] == 60


def test_unknown_trigger_rejects() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="explode",
            trigger_target_id="char_a",
            trigger_scene_script=script(),
            trigger_frame=30,
            then_ops=[],
            then_frame=30,
        )
    assert exc.value.code == "trigger_unknown"


def test_then_op_kind_is_validated() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="sit",
            trigger_target_id="char_a",
            trigger_scene_script=script(),
            trigger_frame=45,
            then_ops=[{"op": "explode_everything", "kind": "camera", "id": "cam1"}],
            then_frame=45,
        )
    assert exc.value.code == "then_op_unknown"


def test_trigger_target_must_exist() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="sit",
            trigger_target_id="char_zz",
            trigger_scene_script=script(),
            trigger_frame=45,
            then_ops=[],
            then_frame=45,
        )
    assert exc.value.code == "trigger_target_missing"


def test_trigger_keyframe_for_arrive() -> None:
    event = expand_trigger_event(
        trigger="arrive",
        trigger_target_id="char_a",
        trigger_scene_script=script(),
        trigger_frame=30,
        trigger_target_position=[6.0, 0.0, 0.0],
        then_ops=[],
        then_frame=30,
    )
    keyframes = trigger_frame_to_keyframe(event, "char_a")
    assert len(keyframes) == 1
    kf = keyframes[0]
    assert kf["op"] == "add_keyframe"
    assert kf["frame"] == 30
    assert kf["position"] == [6.0, 0.0, 0.0]


def test_trigger_keyframe_for_face() -> None:
    event = expand_trigger_event(
        trigger="face",
        trigger_target_id="char_a",
        trigger_scene_script=script(),
        trigger_frame=30,
        trigger_target_yaw=90.0,
        then_ops=[],
        then_frame=30,
    )
    keyframes = trigger_frame_to_keyframe(event, "char_a")
    assert len(keyframes) == 1
    assert keyframes[0]["rotation_y"] == 90.0


def test_trigger_keyframe_for_sit() -> None:
    event = expand_trigger_event(
        trigger="sit",
        trigger_target_id="char_a",
        trigger_scene_script=script(),
        trigger_frame=45,
        then_ops=[],
        then_frame=45,
    )
    keyframes = trigger_frame_to_keyframe(event, "char_a")
    assert len(keyframes) == 1
    assert keyframes[0]["action"] == "sit"


def test_all_triggers_have_known_fields() -> None:
    """Every trigger in CHARACTER_TRIGGERS must have a valid frame_field
    that corresponds to a CharacterKeyframe field."""
    valid_fields = {"action", "position", "rotation_y", "frame"}
    for name, spec in CHARACTER_TRIGGERS.items():
        assert spec["frame_field"] in valid_fields, f"trigger '{name}' has unknown field"
        assert "description" in spec


def test_then_op_kinds_are_a_subset_of_gate_vocabulary() -> None:
    """Every op kind in THEN_OP_KINDS must be in the gate's OP_KINDS."""
    from app.services.scene3d.scene_script_tool_service import OP_KINDS
    gate_kinds = set(OP_KINDS)
    for kind in THEN_OP_KINDS:
        assert kind in gate_kinds, f"THEN_OP_KINDS has '{kind}' but the gate doesn't"


# ---------------------------------------------------------------------------
# Dict-shaped scripts (callers that hand raw JSON, not a validated root)
# ---------------------------------------------------------------------------


def _dict_script() -> dict:
    return {
        "scene": {"name": "trigger-test", "environment": "indoor", "duration": 6, "frame_rate": 30},
        "characters": [
            {
                "id": "char_a",
                "type": "lowpoly_human",
                "appearance": {"color": "#E74C3C"},
                "keyframes": [
                    {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "stand"}
                ],
            }
        ],
        "cameras": [
            {
                "id": "cam1",
                "shot_type": "wide",
                "keyframes": [{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1.2]}],
            }
        ],
        "shots": [{"id": "shot1", "camera": "cam1", "start_frame": 0, "end_frame": 179}],
    }


def test_dict_shaped_script_resolves_its_character() -> None:
    """A dict script must not silently answer 'no characters'."""
    event = expand_trigger_event(
        trigger="sit",
        trigger_target_id="char_a",
        trigger_scene_script=_dict_script(),
        trigger_frame=45,
        then_ops=[],
        then_frame=45,
    )
    assert event["trigger_target_id"] == "char_a"


def test_dict_shaped_script_still_rejects_an_unknown_character() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="sit",
            trigger_target_id="char_b",
            trigger_scene_script=_dict_script(),
            trigger_frame=45,
            then_ops=[],
            then_frame=45,
        )
    assert exc.value.code == "trigger_target_missing"


def test_script_without_any_characters_rejects() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="sit",
            trigger_target_id="char_a",
            trigger_scene_script={},
            trigger_frame=45,
            then_ops=[],
            then_frame=45,
        )
    assert exc.value.code == "trigger_target_missing"


# ---------------------------------------------------------------------------
# Frame and target validation (named codes before anything is expanded)
# ---------------------------------------------------------------------------


def test_negative_trigger_frame_is_rejected() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="sit",
            trigger_target_id="char_a",
            trigger_scene_script=script(),
            trigger_frame=-1,
            then_ops=[],
            then_frame=0,
        )
    assert exc.value.code == "trigger_frame_invalid"


def test_non_integer_trigger_frame_is_rejected() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="sit",
            trigger_target_id="char_a",
            trigger_scene_script=script(),
            trigger_frame=12.5,
            then_ops=[],
            then_frame=0,
        )
    assert exc.value.code == "trigger_frame_invalid"


def test_trigger_frame_past_the_scene_end_is_rejected() -> None:
    """A frame the scene does not contain would be a trigger that never fires."""
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="sit",
            trigger_target_id="char_a",
            trigger_scene_script=script(),  # 180 total frames
            trigger_frame=999,
            then_ops=[],
            then_frame=999,
        )
    assert exc.value.code == "trigger_frame_out_of_range"
    assert "999" in exc.value.message


def test_then_frame_past_the_scene_end_is_rejected() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="sit",
            trigger_target_id="char_a",
            trigger_scene_script=script(),
            trigger_frame=45,
            then_ops=[],
            then_frame=400,
        )
    assert exc.value.code == "then_frame_out_of_range"


def test_arrive_rejects_a_malformed_position() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="arrive",
            trigger_target_id="char_a",
            trigger_scene_script=script(),
            trigger_frame=30,
            trigger_target_position=[1.0, 2.0],
            then_ops=[],
            then_frame=30,
        )
    assert exc.value.code == "trigger_target_invalid"


def test_arrive_rejects_a_non_numeric_position() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="arrive",
            trigger_target_id="char_a",
            trigger_scene_script=script(),
            trigger_frame=30,
            trigger_target_position=["near", 0.0, 0.0],
            then_ops=[],
            then_frame=30,
        )
    assert exc.value.code == "trigger_target_invalid"


def test_face_rejects_a_non_numeric_yaw() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="face",
            trigger_target_id="char_a",
            trigger_scene_script=script(),
            trigger_frame=30,
            trigger_target_yaw="left",
            then_ops=[],
            then_frame=30,
        )
    assert exc.value.code == "trigger_target_invalid"


def test_then_ops_are_copied_not_aliased() -> None:
    """The returned batch must not alias the caller's request body."""
    then_ops = [{"op": "add_keyframe", "kind": "camera", "id": "cam1", "frame": 45}]
    event = expand_trigger_event(
        trigger="sit",
        trigger_target_id="char_a",
        trigger_scene_script=script(),
        trigger_frame=45,
        then_ops=then_ops,
        then_frame=45,
    )
    event["operations"][0]["frame"] = 999
    assert then_ops[0]["frame"] == 45


def test_non_object_then_op_is_named_by_index() -> None:
    with pytest.raises(TriggerError) as exc:
        expand_trigger_event(
            trigger="sit",
            trigger_target_id="char_a",
            trigger_scene_script=script(),
            trigger_frame=45,
            then_ops=["not an op"],
            then_frame=45,
        )
    assert exc.value.code == "then_op_not_object"
    assert "then_ops[0]" in exc.value.message


# ---------------------------------------------------------------------------
# Keyframe conversion (the piece that makes the trigger playable)
# ---------------------------------------------------------------------------


def test_keyframe_conversion_rejects_an_unknown_trigger() -> None:
    with pytest.raises(TriggerError) as exc:
        trigger_frame_to_keyframe({"trigger": "explode", "trigger_frame": 10}, "char_a")
    assert exc.value.code == "trigger_unknown"


def test_keyframe_conversion_names_a_missing_arrive_position() -> None:
    """An empty list would read as 'this trigger needs no pose'."""
    with pytest.raises(TriggerError) as exc:
        trigger_frame_to_keyframe({"trigger": "arrive", "trigger_frame": 10}, "char_a")
    assert exc.value.code == "trigger_target_missing"


def test_keyframe_conversion_names_a_missing_face_yaw() -> None:
    with pytest.raises(TriggerError) as exc:
        trigger_frame_to_keyframe({"trigger": "face", "trigger_frame": 10}, "char_a")
    assert exc.value.code == "trigger_target_missing"


def test_keyframe_conversion_normalises_the_position_payload() -> None:
    keyframes = trigger_frame_to_keyframe(
        {"trigger": "arrive", "trigger_frame": 12, "trigger_target_position": [3, 4, 0]},
        "char_a",
    )
    assert keyframes[0]["position"] == [3.0, 4.0, 0.0]
    assert keyframes[0]["frame"] == 12


def test_keyframe_conversion_passes_the_yaw_through() -> None:
    keyframes = trigger_frame_to_keyframe(
        {"trigger": "face", "trigger_frame": 12, "trigger_target_yaw": 270},
        "char_a",
    )
    assert keyframes[0]["rotation_y"] == pytest.approx(270.0)


@pytest.mark.parametrize("trigger", sorted(CHARACTER_TRIGGERS))
def test_every_trigger_yields_exactly_one_keyframe(trigger: str) -> None:
    event = expand_trigger_event(
        trigger=trigger,
        trigger_target_id="char_a",
        trigger_scene_script=script(),
        trigger_frame=45,
        trigger_target_position=[6.0, 0.0, 0.0],
        trigger_target_yaw=90.0,
        then_ops=[],
        then_frame=45,
    )
    keyframes = trigger_frame_to_keyframe(event, "char_a")
    assert len(keyframes) == 1
    assert keyframes[0]["id"] == "char_a"
    assert keyframes[0]["frame"] == 45
    assert keyframes[0]["op"] == "add_keyframe"


def test_keyframes_are_the_frame_the_trigger_fires_on() -> None:
    """The pose lands on the trigger frame, not on frame 0."""
    event = expand_trigger_event(
        trigger="sit",
        trigger_target_id="char_a",
        trigger_scene_script=script(),
        trigger_frame=77,
        then_ops=[],
        then_frame=80,
    )
    keyframes = trigger_frame_to_keyframe(event, "char_a")
    assert keyframes[0]["frame"] == 77
