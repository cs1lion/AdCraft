"""The converter's pose must be the SAME pose the preview renders.

Two implementations of one curve, because the two runtimes share nothing: the
preview's ``characterPose.ts`` and the converter's ``character_pose.py``. Constants
reaching the frontend through the contract generator covers the NUMBERS; this covers
the FORMULAS, which the generator cannot.

The comparison is phase by phase against ``scene_pose_parity.json``, sampled from the
preview and regenerated with::

    REGENERATE_SCENE_POSE_PARITY=1 npx vitest run \\
      src/features/agent-canvas/canvas/poseParityFixture.dump.test.ts

Comparing at sampled phases is what makes a drift legible: a flipped sign in the
stance shows up as every leg swapping places rather than as one aggregate number
that moved a bit.

This has already paid for itself. It caught the gesture head tilt living in the
preview component as ``-0.26 + pose.head`` while the pose carried ``-0.2``: the same
figure on screen, two different places to look for it, and no other gate in the repo
compares the two renderers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.scene3d import character_pose

FIXTURE = Path(__file__).parent / "fixtures" / "scene_pose_parity.json"

#: Both sides compute in float64; this only has to absorb the last bit or two of a
#: transcendental, not a real disagreement.
TOLERANCE = 1e-12

_FIELD_MAP = {
    "legL": "leg_l",
    "legR": "leg_r",
    "kneeL": "knee_l",
    "kneeR": "knee_r",
    "armL": "arm_l",
    "armR": "arm_r",
    "torso": "torso",
    "head": "head",
    "bob": "bob",
}


@pytest.fixture(scope="module")
def parity() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_is_not_empty(parity: dict) -> None:
    # A vacuous comparison is a green light wired to nothing, so this checks
    # COVERAGE -- every action the schema declares, more than one leg length, and
    # enough samples that a flipped sign cannot hide between two of them.
    actions = {case["action"] for case in parity["cases"]}
    assert actions == {"walk", "stand", "talk", "gesture", "sit"}
    assert len({case["legLengthMetres"] for case in parity["cases"]}) >= 2
    walk_samples = next(c for c in parity["cases"] if c["action"] == "walk")["samples"]
    assert len(walk_samples) >= 6


@pytest.mark.parametrize(
    ("action", "leg_length"),
    [(case["action"], case["legLengthMetres"]) for case in
     json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]],
)
def test_python_pose_matches_the_preview(
    action: str, leg_length: float, parity: dict
) -> None:
    case = next(
        candidate
        for candidate in parity["cases"]
        if candidate["action"] == action and candidate["legLengthMetres"] == leg_length
    )
    for sample in case["samples"]:
        actual = character_pose.segment_pose_at(action, sample["phase"], leg_length)
        for field, expected_field in _FIELD_MAP.items():
            expected = sample[field]
            got = actual.get(expected_field, 0.0)
            assert got == pytest.approx(expected, abs=TOLERANCE), (
                f"{action} phase {sample['phase']} leg {leg_length}: {expected_field} "
                f"is {got:+.9f} in the converter but {expected:+.9f} in the preview"
            )


def test_stride_and_amplitude_match_the_preview(parity: dict) -> None:
    derived = parity["derived"]
    assert character_pose.walk_stride_metres(0.925) == pytest.approx(
        derived["strideForReferenceLeg"], abs=TOLERANCE
    )
    assert character_pose.walk_stride_metres(0.55) == pytest.approx(
        derived["strideForShortLeg"], abs=TOLERANCE
    )
    assert character_pose.walk_leg_amplitude(0.925) == pytest.approx(
        derived["amplitudeForReferenceLeg"], abs=TOLERANCE
    )
    assert character_pose.walk_leg_amplitude(0.55) == pytest.approx(
        derived["amplitudeForShortLeg"], abs=TOLERANCE
    )


def test_every_pose_key_the_converter_reads_is_compared() -> None:
    """A field neither side compares can drift freely, so the map must be total."""
    fields = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"][0]["samples"][0]
    covered = {key for key in fields if key != "phase"}
    assert covered == set(_FIELD_MAP), (
        "the fixture samples a joint the parity test does not compare, or the test "
        f"compares one the fixture does not carry: {covered ^ set(_FIELD_MAP)}"
    )


def test_action_steps_but_position_interpolates() -> None:
    """The two keyframe semantics differ deliberately, and the converter must match.

    Action is STEP -- a keyframe's action governs frames AT AND AFTER it -- while
    position interpolates. A gesture starting at frame 300 must not fade in over the
    walk leading to it.
    """
    actions = ["walk", "gesture", "stand"]
    frames = [0, 30, 60]
    assert character_pose.action_at_frame(actions, frames, 0) == "walk"
    assert character_pose.action_at_frame(actions, frames, 29) == "walk"
    assert character_pose.action_at_frame(actions, frames, 30) == "gesture"
    assert character_pose.action_at_frame(actions, frames, 45) == "gesture"
    assert character_pose.action_at_frame(actions, frames, 60) == "stand"
    # And an unsorted list must not change the answer: the schema does not require
    # keyframes in order, and an unsorted list used to pin the figure to whichever
    # action happened to be written first.
    assert character_pose.action_at_frame(["stand", "walk"], [60, 0], 10) == "walk"


def test_a_stationary_character_never_accumulates_steps() -> None:
    """Phase comes from distance, so zero travel means zero cycles."""
    positions = [[0, 0, 0], [0, 0, 0]]
    frames = [0, 89]
    for frame in (0, 20, 89):
        assert character_pose.travelled_metres(positions, frames, frame) == 0.0
        pose = character_pose.pose_at_frame(["walk", "walk"], positions, frames, frame, 0.925)
        assert pose["leg_l"] == pytest.approx(-pose["leg_r"], abs=TOLERANCE)


def test_travelled_metres_is_monotonic_and_clamped() -> None:
    positions = [[0, 0, 0], [0, 0, 2.0], [0, 0, 5.0]]
    frames = [0, 30, 60]
    assert character_pose.travelled_metres(positions, frames, 0) == 0.0
    assert character_pose.travelled_metres(positions, frames, -5) == 0.0
    assert character_pose.travelled_metres(positions, frames, 999) == pytest.approx(5.0)
    halfway = character_pose.travelled_metres(positions, frames, 15)
    assert 0.0 < halfway < 2.0


class TestTheKnee:
    """The knee exists for one measurable reason: the swing foot must clear.

    A seven-box rig has no knee, so the swing leg passed through the ground at
    the same height on the way forward as on the way back. These are the numbers
    that say whether that is fixed, rather than a claim that it looks better.
    """

    def test_the_fixture_actually_samples_a_bent_knee(self, parity: dict) -> None:
        """The parity comparison of the knee must not be vacuous.

        Every walk phase below STANCE_FRACTION has a perfectly straight knee, so a
        fixture made only of those would report "both sides agree on the knee"
        while never once asking what the knee does.
        """
        walk = [c for c in parity["cases"] if c["action"] == "walk"]
        assert walk, "the fixture has no walk case to sample"
        bent = [s for case in walk for s in case["samples"] if s["kneeL"] != 0.0]
        assert bent, "no walk sample lands in the swing, so the knee is never compared"
    def test_the_swing_foot_lifts_off_the_ground(self) -> None:
        leg = 0.5 * 1.75
        lifts = [character_pose.walk_foot_lift_metres(q / 400, leg) for q in range(400)]
        peak = max(lifts)
        # An absolute floor in metres, so this cannot pass by the lift shrinking
        # with a rig change. 5 cm is about a fifth of the clearance a real walk
        # has and the least that reads as a step at previs scale.
        assert peak > 0.05, f"the swing foot only ever clears {peak * 100:.1f} cm"

    def test_the_clearance_scales_with_the_figure(self) -> None:
        """A child takes a smaller step, so the lift cannot be a fixed distance."""
        tall = max(character_pose.walk_foot_lift_metres(q / 400, 0.925) for q in range(400))
        short = max(character_pose.walk_foot_lift_metres(q / 400, 0.55) for q in range(400))
        assert tall > short
        ratio = tall / short
        assert ratio == pytest.approx(0.925 / 0.55, rel=0.02), (
            "the lift is not proportional to the leg, so one of two figures clears "
            f"the ground by the wrong amount: {ratio:.3f} against {0.925 / 0.55:.3f}"
        )

    def test_the_stance_leg_is_straight_so_the_no_slide_result_survives(self) -> None:
        """The no-slide argument is a STANCE property, and a planted foot is straight.

        If the knee ever flexed during stance the thigh would stop carrying the
        whole leg angle, `L*sin(theta)` would no longer rise at the rate the hip
        advances, and the verified 4% slide would quietly come back.
        """
        stance_samples = 500
        for q in range(int(character_pose.STANCE_FRACTION * stance_samples)):
            assert character_pose.walk_knee_shape(q / stance_samples) == 0.0
        for leg in (0.925, 0.55, 0.5 * 1.10):
            for frame in range(0, 40):
                pose = character_pose.pose_at_frame(
                    ["walk"], [[0, 0, 0], [0, 0, 4.0]], [0, 60],
                    frame, leg,
                )
                # Whichever leg is in stance this frame must be perfectly straight.
                knees = (pose["knee_l"], pose["knee_r"])
                assert min(knees) == 0.0, f"a planted leg is bent: {knees}"

    def test_the_foot_lands_flat_at_both_contacts(self) -> None:
        """Zero at toe off and zero at heel strike, or the foot lands on its toe.

        The bump has to return to zero *before* the next stance starts, which is
        a different requirement from peaking in the middle of the swing.
        """
        for contact in (0.0, character_pose.STANCE_FRACTION, 1.0):
            assert character_pose.walk_knee_shape(contact) == pytest.approx(0.0, abs=1e-12)
        # Just before the wrap, too -- that is the frame the foot actually lands on.
        assert character_pose.walk_knee_shape(1.0 - 1e-12) == pytest.approx(0.0, abs=1e-9)

    def test_the_knee_never_hyperextends(self) -> None:
        for action in ("walk", "stand", "sit", "talk", "gesture"):
            for q in range(0, 50):
                pose = character_pose.segment_pose_at(action, q / 50, 0.925)
                for field in ("knee_l", "knee_r"):
                    assert pose[field] >= 0.0, f"{action} {field} went negative"

    def test_the_legs_stay_half_a_cycle_apart(self) -> None:
        """A knee that lost its phase offset would have both legs off the ground."""
        for q in range(0, 100):
            phase = q / 100
            assert character_pose.walk_knee_shape(phase + character_pose.STANCE_FRACTION) == (
                pytest.approx(character_pose.walk_knee_shape(phase + 0.5), abs=1e-12)
            )
