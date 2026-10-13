"""Authored joint tracks lock schema, seek semantics, and converter consumption."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.schemas.scene_script import CharacterPose, SceneCharacter, SceneScriptRoot
from app.services.scene3d import character_pose
from app.services.scene3d.asset_dimensions import ASSET_DIMENSIONS
from app.services.scene3d.blender_converter import (
    _build_asset,
    _character_pose_code,
    asset_color,
    degraded_asset_ids,
    scene_script_to_blender,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("field", tuple(CharacterPose.model_fields))
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_pose_finite_validation_mutation(field: str, bad: float) -> None:
    # Locks finite radians, including fields that are not pitches. Mutation must reject.
    assert getattr(CharacterPose.model_validate({field: 0}), field) == 0
    with pytest.raises(ValidationError):
        CharacterPose.model_validate({field: bad})


@pytest.mark.parametrize(
    ("field", "bad"),
    [("arm_l", 3.2), ("arm_r_side", 1.6), ("head", -1.6),
     ("head_yaw", -3.2), ("leg_l", 1.6), ("knee_l", -0.01), ("knee_r", 2.41),
     ("bob", -0.151), ("bob", 0.151)],
)
def test_pose_angle_bounds_mutation(field: str, bad: float) -> None:
    # Locks anatomically useful ranges; knee flexion cannot become hyperextension.
    assert getattr(CharacterPose.model_validate({field: 0}), field) == 0
    with pytest.raises(ValidationError):
        CharacterPose.model_validate({field: bad})


def test_pose_unknown_field_mutation() -> None:
    assert CharacterPose.model_validate({"head_yaw": 0}).head_yaw == 0
    with pytest.raises(ValidationError):
        CharacterPose.model_validate({"head_yaw": 0, "elbow_l": 0.1})


def test_sparse_tracks_zero_null_and_backward_seek() -> None:
    frames = [30, 0, 20, 10]
    poses = [{"arm_r": 0, "head_yaw": 0}, None,
             {"head_yaw": 0.8, "arm_r": None}, {"arm_r": 1.0}]
    # Sparse fields resolve independently, sorted internally, with zero retained.
    assert character_pose.authored_pose_at_frame(poses, frames, 9) == {}
    assert character_pose.authored_pose_at_frame(poses, frames, 15) == {"arm_r": 0.75}
    assert character_pose.authored_pose_at_frame(poses, frames, 25) == {
        "arm_r": 0.25, "head_yaw": 0.4,
    }
    assert character_pose.authored_pose_at_frame(poses, frames, 40) == {
        "arm_r": 0, "head_yaw": 0,
    }
    forward = {frame: character_pose.authored_pose_at_frame(poses, frames, frame)
               for frame in range(41)}
    for frame in reversed(range(41)):
        assert character_pose.authored_pose_at_frame(poses, frames, frame) == forward[frame]


def test_explicit_overlay_preserves_unowned_action_and_legacy_pose() -> None:
    args = (["walk", "stand"], [[0, 0, 0], [0, 0.9, 0]], [0, 30], 15, 0.85)
    old = character_pose.pose_at_frame(*args)
    assert character_pose.pose_at_frame(*args, poses=[None, None]) == old
    authored = character_pose.pose_at_frame(*args, poses=[{"head_yaw": 0}, {"head_yaw": 1}])
    assert authored["head_yaw"] == 0.5
    for field, value in old.items():
        assert authored[field] == value


def test_duplicate_frame_last_authored_zero_wins() -> None:
    assert character_pose.authored_pose_at_frame(
        [{"head_yaw": 0.8}, {"head_yaw": 0}, {"head_yaw": 0.4}], [10, 10, 20], 10,
    ) == {"head_yaw": 0}


def _script() -> SceneScriptRoot:
    return SceneScriptRoot.model_validate({
        "scene": {"name": "authored-preflight", "duration": 2, "frame_rate": 30},
        "characters": [{
            "id": "A", "keyframes": [
                {"frame": 0, "position": [0, 0, 0], "rotation_y": 0,
                 "pose": {"arm_r": 0, "arm_r_side": 0, "head_yaw": 0}},
                {"frame": 30, "position": [0, 0, 0], "rotation_y": 0,
                 "pose": {"arm_r": 0.8, "arm_r_side": 0.3, "head_yaw": -0.6}},
                {"frame": 60, "position": [0, 0, 0], "rotation_y": 0,
                 "pose": {"arm_r": 0, "arm_r_side": 0, "head_yaw": 0}},
            ],
        }],
        "props": [{"id": "chip", "type": "chip", "position": [0, 0.2, 1.0]}],
        "cameras": [{"id": "cam", "keyframes": [
            {"frame": 0, "position": [4, -5, 3], "look_at": [0, 0, 1]},
        ]}],
        "shots": [{"id": "shot", "camera": "cam", "start_frame": 0, "end_frame": 60}],
    })


def test_pose_json_round_trip_and_converter_axes() -> None:
    script = _script()
    again = SceneScriptRoot.model_validate_json(script.model_dump_json())
    assert again.model_dump() == script.model_dump()
    code = scene_script_to_blender(script, "D:/unused-authored-preflight-output")
    compile(code, "<generated-authored-preflight>", "exec")
    assert "_p_AArmR.rotation_euler.x = -0.400000" in code
    assert "_p_AArmR.rotation_euler.y = -0.150000" in code
    assert "_p_AHead.rotation_euler.z = -0.300000" in code
    assert "(_p_AArmR, 'rotation_euler', (1,))" in code
    assert "(_p_AHead, 'rotation_euler', (2,))" in code
    assert "_p_AArmR.rotation_mode = 'ZYX'" in code
    assert "_p_AHead.rotation_mode = 'ZYX'" in code
    assert 'nose.name = "A_Nose"' in code


def test_absent_authored_tracks_leave_legacy_axis_curves_and_face_alone() -> None:
    script = _script()
    char = script.characters[0]
    for keyframe in char.keyframes:
        keyframe.pose = None
    code = "\n".join(_character_pose_code(char, script, 60))
    assert "rotation_euler.y" not in code
    assert "rotation_euler.z" not in code
    assert "A_Nose" not in _build_asset("A", "lowpoly_human", [0, 0, 0], 0)


def test_nonhuman_pose_rejected_instead_of_silently_ignored() -> None:
    raw = _script().model_dump()
    raw["characters"][0]["type"] = "door"
    for keyframe in raw["characters"][0]["keyframes"]:
        keyframe["action"] = "door_swing_open"
    with pytest.raises(ValidationError, match="human joint pose"):
        SceneScriptRoot.model_validate(raw)


def test_chip_is_native_disc_at_authored_surface() -> None:
    script = _script()
    assert degraded_asset_ids(script) == ()
    dims = ASSET_DIMENSIONS["chip"]
    assert (dims.width, dims.depth, dims.height, dims.base) == (0.14, 0.14, 0.025, 0)
    assert asset_color("chip") == "#32B7A5"
    code = _build_asset("token", "chip", [0, 0, 1.0], 0)
    assert "radius=0.0700, depth=0.0250, location=(0, 0, 0.0125)" in code
    assert "PREVIS_DEGRADED_ASSET" not in code


def test_explicit_stop_can_author_legs_and_knees_without_state() -> None:
    char = SceneCharacter.model_validate({
        "id": "walker", "keyframes": [
            {"frame": 0, "position": [0, 0, 0], "rotation_y": 0, "action": "walk",
             "pose": {"leg_l": 0.2, "leg_r": -0.2, "knee_l": 0.4, "knee_r": 0}},
            {"frame": 30, "position": [0, 0.9, 0], "rotation_y": 0, "action": "stand",
             "pose": {"leg_l": 0.05, "leg_r": -0.05, "knee_l": 0, "knee_r": 0}},
        ],
    })
    kwargs = {
        "actions": [key.action for key in char.keyframes],
        "positions": [key.position for key in char.keyframes],
        "frames": [key.frame for key in char.keyframes],
        "leg_length_metres": 0.85,
        "poses": [key.pose.model_dump(exclude_none=True) for key in char.keyframes],
    }
    final = character_pose.pose_at_frame(frame=30, **kwargs)
    middle = character_pose.pose_at_frame(frame=15, **kwargs)
    assert middle["leg_l"] == pytest.approx(0.125)
    assert middle["knee_l"] == pytest.approx(0.2)
    assert final["knee_l"] == 0
    assert character_pose.pose_at_frame(frame=30, **kwargs) == final
