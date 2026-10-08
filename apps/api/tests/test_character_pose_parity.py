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
