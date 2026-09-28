"""Tests for director motion intent expansion.

These tests lock the MVP contract: camera/character intents expand into the
same backend op vocabulary the SceneScript tool service already gates, while
keeping the motion math close to the web presets without importing the
frontend package.

Expansion is verified through ``SceneScriptToolService.apply_operations`` —
the same all-or-nothing gate the live apply-operations endpoint runs — not
by hand-editing keyframes — so a regression in the preset math, the
service gate, or the schema itself surfaces here.
"""

from __future__ import annotations

import math

import pytest

from app.schemas.scene_script import SceneScriptRoot
from app.services.scene3d.director_motion import (
    DirectorMotionError,
    _character_motion_keyframes,
    expand_camera_motion_preset,
    expand_character_motion_preset,
    expand_director_motion,
)
from app.services.scene3d.scene_script_tool_service import (
    SceneScriptToolService,
)


SERVICE = SceneScriptToolService()


def script() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate(
        {
            "scene": {"name": "lab", "environment": "indoor", "duration": 6, "frame_rate": 30},
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


def apply(base: SceneScriptRoot, operations: list[dict]) -> SceneScriptRoot:
    result = SERVICE.apply_operations(base, operations)
    return result.scene_script


def camera_position_at(script_value: SceneScriptRoot, frame: int) -> list[float]:
    for camera in script_value.cameras:
        if camera.id != "cam1":
            continue
        for key in camera.keyframes:
            if key.frame == frame:
                return key.position
    raise AssertionError(f"missing camera keyframe {frame}")


def character_position_at(script_value: SceneScriptRoot, frame: int) -> list[float]:
    for character in script_value.characters:
        if character.id != "char_a":
            continue
        for key in character.keyframes:
            if key.frame == frame:
                return key.position
    raise AssertionError(f"missing character keyframe {frame}")


def test_camera_push_in_expands_into_sampled_keyframe_ops() -> None:
    base = script()
    operations = expand_camera_motion_preset(
        base,
        camera_id="cam1",
        preset_id="push_in",
        start_frame=0,
        duration_frames=30,
    )

    assert [operation["op"] for operation in operations] == ["add_keyframe"] * len(operations)
    assert [operation["frame"] for operation in operations] == [0, 15, 30]
    assert operations[-1]["position"] != operations[0]["position"]
    assert operations[-1]["look_at"] == [0.0, 0.0, 1.2]

    applied = apply(base, operations)
    # The gate re-validates the script post-apply, so the applied root must
    # stay schema-legal and carry a keyframe for every sampled frame.
    applied.model_dump(mode="json")
    assert [operation["frame"] for operation in operations] == [
        key.frame for key in applied.cameras[0].keyframes
    ]

    # A push-in moves the camera frame 0 -> frame 30 toward the look_at
    # target, so the frame-30 position is strictly closer to [0, 0, 1.2]
    # than the frame-0 position.
    start_distance = math.dist(camera_position_at(applied, 0), [0.0, 0.0, 1.2])
    end_distance = math.dist(camera_position_at(applied, 30), [0.0, 0.0, 1.2])
    assert end_distance < start_distance


def test_character_walk_to_expands_with_facing_and_landing_action() -> None:
    base = script()
    operations = expand_character_motion_preset(
        base,
        character_id="char_a",
        preset_id="walk_to",
        target=[6, 0, 0],
        start_frame=30,
        duration_frames=60,
    )

    assert [operation["frame"] for operation in operations] == [30, 45, 60, 75, 90]
    assert operations[-1]["position"] == [6.0, 0.0, 0.0]
    assert operations[-1]["action"] == "stand"
    assert operations[0]["action"] == "walk"
    assert operations[-1]["rotation_y"] == pytest.approx(90.0)

    applied = apply(base, operations)
    assert character_position_at(applied, 90) == pytest.approx([6.0, 0.0, 0.0])


def test_expanded_ops_apply_cleanly_through_scene_script_gate() -> None:
    base = script()
    camera_ops = expand_camera_motion_preset(
        base,
        camera_id="cam1",
        preset_id="orbit_left",
        start_frame=0,
        duration_frames=30,
    )
    character_ops = expand_character_motion_preset(
        base,
        character_id="char_a",
        preset_id="approach",
        target=[0, 5, 0],
        start_frame=0,
        duration_frames=30,
        stop_distance=1.0,
    )

    # The all-or-nothing gate is the real contract: a mixed batch of
    # preset-expanded ops must pass validation and end schema-legal.
    applied = apply(base, camera_ops + character_ops)
    assert applied.model_dump(mode="json")
    assert len(applied.cameras[0].keyframes) >= 3
    assert len(applied.characters[0].keyframes) >= 3


def test_unknown_preset_fails_with_code() -> None:
    with pytest.raises(DirectorMotionError) as exc:
        expand_camera_motion_preset(
            script(),
            camera_id="cam1",
            preset_id="handheld",
            start_frame=0,
            duration_frames=15,
        )
    assert exc.value.code == "director_motion_preset_unknown"


def test_intent_expansion_requires_a_known_target() -> None:
    with pytest.raises(DirectorMotionError) as exc:
        expand_director_motion(
            script(),
            intent="camera_motion",
            target_id="",
            preset_id="push_in",
        )
    assert exc.value.code == "director_motion_target_missing"


def test_intent_expansion_emits_replayable_contract() -> None:
    result = expand_director_motion(
        script(),
        intent="character_motion",
        target_id="char_a",
        preset_id="turn_to",
        target=[0, 5, 0],
        start_frame=0,
        duration_frames=30,
    )

    assert result["intent"] == "character_motion"
    assert result["target"] == "char_a"
    assert result["preset_id"] == "turn_to"
    assert result["operations"]
    assert all(operation["op"] == "add_keyframe" for operation in result["operations"])


# ---------------------------------------------------------------------------
# Failure paths (named codes, never a stack trace in the response)
# ---------------------------------------------------------------------------


def test_preset_from_the_other_family_is_named_as_a_mismatch() -> None:
    """A camera intent with a character preset is a caller mistake, not a
    missing preset — the error must say which family it wanted."""
    with pytest.raises(DirectorMotionError) as exc:
        expand_director_motion(
            script(),
            intent="camera_motion",
            target_id="cam1",
            preset_id="walk_to",
        )
    assert exc.value.code == "director_motion_preset_intent_mismatch"
    assert "camera_motion" in exc.value.message
    assert "walk_to" in exc.value.message


def test_unknown_intent_is_rejected() -> None:
    with pytest.raises(DirectorMotionError) as exc:
        expand_director_motion(
            script(),
            intent="teleport_motion",
            target_id="cam1",
            preset_id="push_in",
        )
    assert exc.value.code == "director_motion_invalid"


def test_character_target_is_required() -> None:
    with pytest.raises(DirectorMotionError) as exc:
        expand_director_motion(
            script(),
            intent="character_motion",
            target_id="char_a",
            preset_id="walk_to",
            target=None,
        )
    assert exc.value.code == "director_motion_target_missing"
    assert "position" in exc.value.message


def test_missing_camera_is_named() -> None:
    with pytest.raises(DirectorMotionError) as exc:
        expand_camera_motion_preset(
            script(),
            camera_id="ghost_cam",
            preset_id="push_in",
            start_frame=0,
            duration_frames=15,
        )
    assert exc.value.code == "director_motion_camera_missing"


def test_missing_character_is_named() -> None:
    with pytest.raises(DirectorMotionError) as exc:
        expand_character_motion_preset(
            script(),
            character_id="ghost",
            preset_id="walk_to",
            target=[1, 0, 0],
            start_frame=0,
            duration_frames=15,
        )
    assert exc.value.code == "director_motion_character_missing"


def test_frame_past_the_scene_end_is_clamped_not_crashed() -> None:
    """A director asking for frame 9999 gets a named range error, not ops."""
    with pytest.raises(DirectorMotionError) as exc:
        expand_camera_motion_preset(
            script(),
            camera_id="cam1",
            preset_id="push_in",
            start_frame=9999,
            duration_frames=15,
        )
    assert exc.value.code == "director_motion_frame_out_of_range"


def test_negative_frame_is_rejected() -> None:
    with pytest.raises(DirectorMotionError) as exc:
        expand_director_motion(
            script(),
            intent="camera_motion",
            target_id="cam1",
            preset_id="push_in",
            start_frame=-5,
        )
    assert exc.value.code == "director_motion_frame_out_of_range"


def test_zero_duration_is_rejected() -> None:
    with pytest.raises(DirectorMotionError) as exc:
        expand_camera_motion_preset(
            script(),
            camera_id="cam1",
            preset_id="push_in",
            start_frame=0,
            duration_frames=0,
        )
    assert exc.value.code == "director_motion_invalid"


def test_non_numeric_target_is_rejected() -> None:
    with pytest.raises(DirectorMotionError) as exc:
        expand_character_motion_preset(
            script(),
            character_id="char_a",
            preset_id="walk_to",
            target=["left", 0, 0],
            start_frame=0,
            duration_frames=15,
        )
    assert exc.value.code == "director_motion_invalid"
    assert "numeric" in exc.value.message


def test_short_target_vector_is_rejected() -> None:
    with pytest.raises(DirectorMotionError) as exc:
        expand_character_motion_preset(
            script(),
            character_id="char_a",
            preset_id="walk_to",
            target=[1, 0],
            start_frame=0,
            duration_frames=15,
        )
    assert exc.value.code == "director_motion_invalid"


# ---------------------------------------------------------------------------
# The recorded window is the window that actually runs
# ---------------------------------------------------------------------------


def test_recorded_window_matches_the_ops_it_describes() -> None:
    """A batch must be re-expandable from what it records."""
    result = expand_director_motion(
        script(),
        intent="camera_motion",
        target_id="cam1",
        preset_id="push_in",
        start_frame=150,
        duration_frames=30,
    )
    assert result["start_frame"] == 150
    assert result["duration_frames"] == 30
    # The recorded window is exactly the sampled window: first frame, last
    # frame, and the 15-frame step in between.
    assert result["duration_frames"] == result["operations"][-1]["frame"] - result["start_frame"]
    assert [operation["frame"] for operation in result["operations"]] == [150, 165, 180]


def test_move_running_past_the_scene_end_is_rejected_not_trimmed() -> None:
    """A director who asked for 60 frames gets 60 frames or a named error."""
    with pytest.raises(DirectorMotionError) as exc:
        expand_director_motion(
            script(),  # 180 total frames
            intent="camera_motion",
            target_id="cam1",
            preset_id="push_in",
            start_frame=160,
            duration_frames=60,
        )
    assert exc.value.code == "director_motion_frame_out_of_range"
    assert "220" in exc.value.message


def test_recorded_window_is_recorded_for_character_moves() -> None:
    result = expand_director_motion(
        script(),
        intent="character_motion",
        target_id="char_a",
        preset_id="approach",
        target=[0, 5, 0],
        start_frame=30,
        duration_frames=30,
        stop_distance=1.5,
    )
    assert result["start_frame"] == 30
    assert result["duration_frames"] == 30
    assert result["stop_distance"] == 1.5
    assert [operation["frame"] for operation in result["operations"]] == [30, 45, 60]
    assert result["operations"][-1]["frame"] == result["start_frame"] + result["duration_frames"]


def test_turn_to_does_not_divide_by_a_zero_duration() -> None:
    """The sampler guards a degenerate range instead of raising ZeroDivisionError."""
    keyframes = _character_motion_keyframes(
        "turn_to",
        {"position": [0.0, 0.0, 0.0], "rotation_y": 0.0, "action": "stand"},
        [0.0, 5.0, 0.0],
        start_frame=10,
        duration_frames=0,
    )
    assert [keyframe["frame"] for keyframe in keyframes] == [10]
    assert keyframes[0]["rotation_y"] == pytest.approx(0.0)


def test_walk_to_zero_duration_holds_still_instead_of_teleporting() -> None:
    """A move with no duration is a still at the anchor — never a jump."""
    keyframes = _character_motion_keyframes(
        "walk_to",
        {"position": [0.0, 0.0, 0.0], "rotation_y": 0.0, "action": "stand"},
        [6.0, 0.0, 0.0],
        start_frame=10,
        duration_frames=0,
    )
    assert [keyframe["frame"] for keyframe in keyframes] == [10]
    assert keyframes[0]["position"] == pytest.approx([0.0, 0.0, 0.0])
    assert keyframes[0]["action"] == "stand"


def test_approach_stops_short_of_the_target() -> None:
    """``approach`` keeps a stop distance; ``walk_to`` lands exactly on it."""
    anchor = {"position": [0.0, 0.0, 0.0], "rotation_y": 0.0, "action": "stand"}
    walked = _character_motion_keyframes(
        "walk_to", anchor, [0.0, 5.0, 0.0], start_frame=0, duration_frames=30
    )[-1]
    approached = _character_motion_keyframes(
        "approach", anchor, [0.0, 5.0, 0.0], start_frame=0, duration_frames=30, stop_distance=1.2
    )[-1]
    assert walked["position"][1] == pytest.approx(5.0)
    assert approached["position"][1] == pytest.approx(3.8)


def test_approach_within_the_stop_distance_does_not_move() -> None:
    anchor = {"position": [0.0, 0.0, 0.0], "rotation_y": 0.0, "action": "stand"}
    landing = _character_motion_keyframes(
        "approach", anchor, [0.0, 0.5, 0.0], start_frame=0, duration_frames=30, stop_distance=1.2
    )[-1]
    assert landing["position"] == pytest.approx([0.0, 0.0, 0.0])
