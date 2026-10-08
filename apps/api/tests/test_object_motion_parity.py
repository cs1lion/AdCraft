"""The converter's object motion must be the SAME motion the preview renders.

The mirror of ``test_character_pose_parity`` for non-human actors. Two
implementations of one set of curves, constants shared through the contract
generator and formulas compared here phase by phase against
``object_motion_parity.json``.

Comparing sampled phases is what makes a drift legible rather than aggregate: the
wrap-versus-clamp distinction is invisible in a total, because a wrapping door and
a clamping door produce the same values over [0, 1] and differ everywhere after it.
That is why the fixture samples past phase 1 for the one-shot actions.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.services.scene3d import object_motion

FIXTURE = Path(__file__).parent / "fixtures" / "object_motion_parity.json"

#: Both sides compute in float64; this absorbs the last bit or two of a
#: transcendental, not a real disagreement.
TOLERANCE = 1e-12


@pytest.fixture(scope="module")
def parity() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_covers_every_action_including_a_human_one(parity: dict) -> None:
    actions = {case["action"] for case in parity["cases"]}
    assert actions == {"door_swing_open", "spin", "drive", "flyover", "stand"}
    # The one-shot action must be sampled PAST its cycle, or the clamp is untested.
    door = next(c for c in parity["cases"] if c["action"] == "door_swing_open")
    assert max(s["phase"] for s in door["samples"]) > 1.0
    # And a continuous one past it, so the wrap is tested rather than assumed.
    spin = next(c for c in parity["cases"] if c["action"] == "spin")
    assert max(s["phase"] for s in spin["samples"]) > 1.0


@pytest.mark.parametrize(
    "action",
    [case["action"] for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]],
)
def test_python_object_motion_matches_the_preview(action: str, parity: dict) -> None:
    case = next(c for c in parity["cases"] if c["action"] == action)
    for sample in case["samples"]:
        actual = object_motion.object_motion_at(action, sample["phase"])
        for field in ("rotation", "translation"):
            expected = sample[field]
            got = actual.get(field)
            if expected is None:
                assert got is None, (
                    f"{action} phase {sample['phase']}: the converter produces "
                    f"{field}={got} but the preview produces none"
                )
                continue
            assert got is not None, (
                f"{action} phase {sample['phase']}: the converter produces no "
                f"{field} but the preview produces {expected}"
            )
            assert got == pytest.approx(tuple(expected), abs=TOLERANCE), (
                f"{action} phase {sample['phase']}: {field} is {got} in the "
                f"converter but {tuple(expected)} in the preview"
            )


def test_a_door_clamps_and_a_wheel_wraps(parity: dict) -> None:
    """The distinction the whole wrap/clamp branch exists for, stated as numbers.

    A wrapping one-shot counts a second cycle and shuts the finished door again on
    the next frame, which reads as a metronome. Both behaviours have to hold at once
    or the sign of that bug flips silently.
    """
    assert object_motion.object_motion_at("door_swing_open", 1.5) == (
        object_motion.object_motion_at("door_swing_open", 1.0)
    )
    # Phase 1 wraps back to zero for a continuous motion, and a quarter cycle past it
    # is a quarter turn -- not a stopped wheel.
    assert object_motion.object_motion_at("spin", 1.0)["rotation"][0] == pytest.approx(0.0)
    wrapped = object_motion.object_motion_at("spin", 1.25)["rotation"][0]
    assert wrapped == pytest.approx(0.25 * 2 * math.pi, abs=TOLERANCE)


def test_derived_constants_match_the_preview(parity: dict) -> None:
    derived = parity["derived"]
    assert object_motion.MOTION_STRIDE_METRES["drive"] == pytest.approx(
        derived["driveStrideMetres"], abs=TOLERANCE
    )
    assert object_motion.MOTION_STRIDE_METRES["flyover"] == pytest.approx(
        derived["flyoverStrideMetres"], abs=TOLERANCE
    )
    assert object_motion.DOOR_SWING_SECONDS == pytest.approx(
        derived["doorSwingSeconds"], abs=TOLERANCE
    )
    assert object_motion.CONTINUOUS_CYCLE_SECONDS == pytest.approx(
        derived["continuousCycleSeconds"], abs=TOLERANCE
    )
    assert object_motion.cycle_phase_for_frame("spin", 20, 30) == pytest.approx(
        derived["phaseAtFrame30Fps20"], abs=TOLERANCE
    )
    assert object_motion.cycle_phase_for_frame("door_swing_open", 60, 30) == pytest.approx(
        derived["phaseAtFrame30Fps60"], abs=TOLERANCE
    )


def test_a_human_action_leaves_a_non_human_actor_at_rest() -> None:
    """A script pairing a body action with a door is a bug; it must be visible.

    Rest is the honest rendering -- the object sits in the scene doing nothing --
    rather than an exception that takes the whole frame down over one actor.
    """
    for action in ("walk", "stand", "talk", "sit", "gesture", None, ""):
        assert object_motion.object_motion_at(action, 0.4) == {}
        assert not object_motion.is_non_human_action(action)


def test_phase_survives_a_degenerate_frame_rate() -> None:
    assert object_motion.cycle_phase_for_frame("spin", 10, 0) == 0.0
    assert object_motion.cycle_phase_for_frame("spin", 10, -5) == 0.0
