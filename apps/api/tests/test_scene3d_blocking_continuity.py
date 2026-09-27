"""Tests for cross-shot blocking continuity (the Continuity State core).

Locks the V0.2 §5 failure example, the walk-budget arithmetic, and the
frontend parity of the codes.
"""

from __future__ import annotations

from app.schemas.scene_script import SceneCamera, SceneCharacter, SceneScriptRoot, SceneShot
from app.services.scene3d.blocking_continuity import (
    FACING_FLIP_THRESHOLD_DEGREES,
    WALK_SPEED_MPS,
    check_blocking_continuity,
    yaw_delta_degrees,
)


def _character(
    keyframes: list[tuple[int, list[float], float]],
) -> SceneCharacter:
    return SceneCharacter(
        id="lin",
        type="lowpoly_human",
        appearance={"color": "#E74C3C"},
        keyframes=[
            {"frame": frame, "position": position, "rotation_y": yaw, "action": "stand"}
            for frame, position, yaw in keyframes
        ],
    )


def _script(character: SceneCharacter, shots: list[tuple[str, int, int]]) -> SceneScriptRoot:
    return SceneScriptRoot(
        scene={"name": "lab", "duration": 8, "frame_rate": 30},
        characters=[character],
        props=[],
        environment=[],
        cameras=[
            SceneCamera(
                id="cam1",
                shot_type="wide",
                keyframes=[{"frame": 0, "position": [5, -6, 2.6], "look_at": [0, 0, 1]}],
            )
        ],
        shots=[
            SceneShot(id=shot_id, camera="cam1", start_frame=start, end_frame=end)
            for shot_id, start, end in shots
        ],
        speech_bindings=[],
    )


ADJACENT = [("s1", 0, 89), ("s2", 90, 179)]


class TestYawDelta:
    def test_takes_the_short_way(self) -> None:
        assert yaw_delta_degrees(350, 10) == 20
        assert yaw_delta_degrees(0, 270) == 90
        assert yaw_delta_degrees(0, 180) == 180
        assert yaw_delta_degrees(0, 0) == 0


class TestFacingFlip:
    def test_flags_an_unauthored_turn_at_the_cut(self) -> None:
        script = _script(
            _character([(0, [0, 0, 0], 0), (89, [0, 0, 0], 0), (90, [0, 0, 0], 180)]),
            ADJACENT,
        )

        issues = check_blocking_continuity(script)

        assert [issue.code for issue in issues] == ["facing_flip"]
        issue = issues[0]
        assert issue.subject == "lin"
        assert issue.boundary == "s1→s2"
        assert issue.severity == "warning"  # advisory, never blocking
        assert "转身面向" in issue.remedy
        payload = issue.to_dict()
        assert payload["code"] == "facing_flip"

    def test_a_smooth_turn_is_not_a_flip(self) -> None:
        # The turn is authored across the whole scene: no discontinuity.
        script = _script(
            _character([(0, [0, 0, 0], 0), (179, [0, 0, 0], 180)]),
            ADJACENT,
        )

        assert check_blocking_continuity(script) == []


class TestPositionJump:
    def test_flags_a_teleport_between_contiguous_shots(self) -> None:
        script = _script(
            _character([(0, [0, 0, 0], 90), (89, [0, 0, 0], 90), (90, [6, 0, 0], 90)]),
            ADJACENT,
        )

        issues = check_blocking_continuity(script)
        jump = next(issue for issue in issues if issue.code == "position_jump")
        assert "6.0m" in jump.message
        assert "走到" in jump.remedy

    def test_a_walk_that_fits_the_gap_is_accepted(self) -> None:
        # A 2s gap between shots allows ~2.4m of travel.
        script = _script(
            _character([(0, [0, 0, 0], 90), (150, [1.5, 0, 0], 90)]),
            [("s1", 0, 89), ("s2", 150, 239)],
        )

        assert check_blocking_continuity(script) == []


class TestDegenerate:
    def test_a_single_shot_has_no_boundary_to_check(self) -> None:
        assert check_blocking_continuity(_script(_character([(0, [0, 0, 0], 0)]), [("s1", 0, 89)])) == []

    def test_a_character_with_one_keyframe_holds_its_pose_across_shots(self) -> None:
        # The schema requires at least one keyframe; a single authored pose
        # simply carries through both shots (no flip, no jump).
        assert check_blocking_continuity(_script(_character([(0, [0, 0, 0], 90)]), ADJACENT)) == []

    def test_thresholds_are_exported_for_parity(self) -> None:
        assert FACING_FLIP_THRESHOLD_DEGREES > 0
        assert WALK_SPEED_MPS > 0
