"""The pre-render sightline lint has to be a gate, not a report nobody reads.

§2.6 of ``docs/plans/previs-asset-and-motion-gap.md`` lists four missing contracts and
the fourth is this: a pre-render check that catches "the character is standing under
the platform". The script existed and was correct about the geometry -- it found the
camera inside ``landing_pad`` and the tower blocking shots -- but it only ever
printed, and it was wired into no script and no test, so nothing ran it.

Two detectors, because they fail differently:

- ``blocked_by_subject`` is a raycast approximation. Conservative: it can report a
  graze the real render would miss, never the reverse. An invented obstruction is
  worse than a missed one, because it sends you moving a camera to dodge a wall that
  was never in the way.
- ``subjects_under_floating`` is a footprint overlap plus a z-interval test, and it is
  exact. No raycasting needed.

The fixtures carry the doc's own evidence: the hand-un-tuned jinghai must fail and the
hand-tuned recomposition must mostly pass. That asymmetry is the point -- a check
that passes everything is not a check, and one that fails everything gets deleted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from previs_camera_sightlines import (  # noqa: E402
    blocked_by_subject,
    findings,
    subjects_under_floating,
)

FIXTURES = Path(__file__).resolve().parents[3] / "test-materials"


def scene(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The documented evidence
# ---------------------------------------------------------------------------


def test_the_hand_untuned_jinghai_is_caught() -> None:
    """The doc's own table: a pillar at 4.5 is 19 m and the platform buries everyone."""
    problems = findings(scene("jinghai_scenescript.json"))
    kinds = {finding.kind for finding in problems}
    assert "camera_inside_geometry" in kinds, (
        "five of eight camera positions were inside landing_pad; the check missed it"
    )
    assert "subject_under_floating" in kinds, (
        "every character is authored at z = 0 under a slab occupying z 1..3"
    )
    assert len(problems) >= 10, f"expected the whole scene flagged, got {len(problems)}"


def test_the_hand_tuned_recomposition_is_much_cleaner() -> None:
    """`jinghai_recomposed.json` is the doc's "reasonable values" sample.

    Not zero -- the landing pad still floats at z = 0.32 over yong2, which is a real
    residual -- but an order of magnitude fewer findings than the un-tuned scene, so
    the detector discriminates rather than flagging everything.
    """
    un_tuned = len(findings(scene("jinghai_scenescript.json")))
    tuned = len(findings(scene("jinghai_recomposed.json")))
    assert tuned < un_tuned / 4, (
        f"recomposition reduced findings from {un_tuned} to {tuned}, which is not "
        "enough to say the check discriminates"
    )


@pytest.mark.parametrize("name", ["motion_scene.json", "pivot_scene.json"])
def test_the_small_fixtures_are_clean(name: str) -> None:
    assert findings(scene(name)) == []


# ---------------------------------------------------------------------------
# Each detector on its own, on a scene built to trigger exactly it
# ---------------------------------------------------------------------------


def _minimal_scene(**overrides) -> dict:
    base = {
        "scene": {"name": "t", "environment": "indoor", "lighting": "neutral",
                  "duration": 2, "frame_rate": 30},
        "characters": [{
            "id": "person", "type": "lowpoly_human",
            "appearance": {"color": "#8B4513", "height": 1.85, "scale": 1.0},
            "keyframes": [{"frame": 0, "position": [0, 0, 0], "rotation_y": 0,
                           "action": "stand"}],
        }],
        "props": [],
        "environment": [],
        "cameras": [{"id": "cam", "shot_type": "wide", "keyframes": [
            {"frame": 0, "position": [0, -8, 1.6], "look_at": [0, 0, 1.0]}]}],
        "shots": [{"id": "s", "camera": "cam", "start_frame": 0, "end_frame": 30,
                   "description": "d"}],
        "speech_bindings": [],
    }
    base.update(overrides)
    return base


def test_a_camera_inside_geometry_is_a_hard_failure() -> None:
    """A pillar standing where the camera is."""
    blocked = blocked_by_subject(_minimal_scene(environment=[
        {"id": "column", "type": "pillar", "position": [0, -8, 0], "scale": 1.0}
    ]))
    assert [f.kind for f in blocked] == ["camera_inside_geometry"]


def test_a_wall_in_front_of_the_subject_blocks_it() -> None:
    """Close enough to the camera to sit in front of the subject.

    At y = -6.5 the obstruction is 19% along a sightline that runs from y = -8 to
    y = 0, comfortably inside the 50% the detector treats as blocking. Placed near the
    subject instead it reads as scenery, which is the intended distinction.
    """
    blocked = blocked_by_subject(_minimal_scene(environment=[
        {"id": "screen", "type": "wall", "position": [0, -6.5, 0], "scale": 1.0}
    ]))
    assert [f.kind for f in blocked] == ["subject_blocked"]
    assert "screen" in blocked[0].detail


def test_an_obstruction_past_the_midpoint_is_scenery_not_a_block() -> None:
    """The other half of the threshold, because a detector that flags everything is noise."""
    blocked = blocked_by_subject(_minimal_scene(environment=[
        {"id": "screen", "type": "wall", "position": [0, -1.5, 0], "scale": 1.0}
    ]))
    assert blocked == []


def test_a_clear_shot_produces_nothing() -> None:
    """The negative case. Without it the detector could be reporting everything."""
    assert blocked_by_subject(_minimal_scene()) == []
    assert subjects_under_floating(_minimal_scene()) == []


def test_a_character_under_a_floating_slab_is_caught() -> None:
    """The doc's specific case: `platform` at scale 2 occupies z 0.4..1.2.

    The character is authored at z = 0 with its head at 1.8, so it is underneath.
    """
    problems = subjects_under_floating(_minimal_scene(environment=[
        {"id": "pad", "type": "platform", "position": [0, 0, 0], "scale": 2.0}
    ]))
    assert [f.kind for f in problems] == ["subject_under_floating"]
    assert "person" in problems[0].detail and "pad" in problems[0].detail


def test_a_character_beside_the_slab_is_not_caught() -> None:
    """Footprint overlap is required, not just the slab existing somewhere in the scene."""
    assert subjects_under_floating(_minimal_scene(environment=[
        {"id": "pad", "type": "platform", "position": [40, 0, 0], "scale": 2.0}
    ])) == []


def test_a_slab_below_the_feet_is_not_under_them() -> None:
    """`platform` at scale 0.2 spans z 0.04..0.2, which a character stands ON."""
    assert subjects_under_floating(_minimal_scene(environment=[
        {"id": "pad", "type": "platform", "position": [0, 0, 0], "scale": 0.2}
    ])) == []


def test_ground_is_not_treated_as_a_floating_slab() -> None:
    """`ground` has a negative base -- it is below the feet by construction."""
    assert subjects_under_floating(_minimal_scene(environment=[
        {"id": "site", "type": "ground", "position": [0, 0, 0], "scale": 2.0}
    ])) == []


def test_every_floating_kind_is_actually_floating() -> None:
    """The mirrored list must not drift from the dimension table, in either direction.

    ``FLOATING_KINDS`` is a literal in a standalone script, so nothing else would
    notice it drifting. It is deliberately a SUBSET rather than a copy --
    ``weapon`` has a positive base and is still not something a character can stand
    under -- so this asserts both halves: nothing here fails to float, and nothing
    missing here could have floated.
    """
    from previs_camera_sightlines import FLOATING_KINDS
    from app.services.scene3d import asset_dimensions

    floating = set(asset_dimensions.floating_kinds())
    assert FLOATING_KINDS <= floating, (
        f"{sorted(FLOATING_KINDS - floating)} are listed as burying but do not float"
    )
    unexplained = floating - FLOATING_KINDS
    assert unexplained == {"weapon"}, (
        f"{sorted(unexplained)} float but are not in the list; if one of them can "
        "bury a character standing at z = 0, add it, and say why here"
    )
