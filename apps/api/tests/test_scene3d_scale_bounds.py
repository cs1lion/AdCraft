"""``scale`` must mean the same thing for every kind, and be bounded per kind.

§2.6 of ``docs/plans/previs-asset-and-motion-gap.md``. The evidence there is that
nobody -- including the model writing the SceneScript -- knew what ``scale`` produced
in metres, so a ``pillar`` at 4.5 shipped as a 19 m column beside a 1.85 m person and
a ``platform`` at 5 as a 25 m slab with every character underneath it. Five of eight
camera positions were inside that slab, which is why the frames were a flat brown
wall.

The fix has two halves and this file covers both:

- the PROMPT says what each kind measures (tested in
  ``test_scene3d_generator_prompt.py``), and
- the SCHEMA rejects a scale that renders something implausibly large.

The bound is derived from the rendered size rather than picked per kind, so a test
that only checked a handful of numbers would miss a kind whose bound came out wrong.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from app.schemas.scene_script import (
    EnvironmentType,
    PropType,
    SceneEnvironmentObject,
    SceneProp,
    SceneScriptRoot,
)
from app.services.scene3d import asset_dimensions as ad

FIXTURES = Path(__file__).resolve().parents[3] / "test-materials"


# ---------------------------------------------------------------------------
# The bound itself
# ---------------------------------------------------------------------------


def test_every_kind_either_has_a_bound_or_is_deliberately_exempt() -> None:
    """A kind with no bound and no exemption is a hole, not a default."""
    for kind in ad.kinds():
        exempt = kind in ad.SITE_PLATE_KINDS
        assert (ad.max_scale(kind) is None) == exempt or kind == "lowpoly_human", (
            f"{kind} has no scale bound and is not a documented site plate"
        )


def test_a_bound_is_derived_from_the_rendered_size_not_chosen() -> None:
    """Halving the largest extent must double the bound, exactly.

    This is the property that distinguishes "derived" from "a table someone wrote".
    A per-kind table could pass every other test here while still being a taste
    judgement; this one cannot.
    """
    for kind in ad.kinds():
        if ad.max_scale(kind) is None:
            continue
        dims = ad.ASSET_DIMENSIONS[kind]
        limit = ad.max_scale(kind)
        assert limit is not None
        largest = max(dims.width, dims.height, dims.depth)
        assert limit == pytest.approx(
            ad.MAX_EXTENT_PERSON_HEIGHTS * ad.REFERENCE_PERSON_HEIGHT / largest
        ), f"{kind}'s bound does not match its measured extent"
        # And the bound is exactly where the ceiling lands.
        at_limit = ad.rendered(kind, limit)
        assert at_limit is not None
        assert max(at_limit.width, at_limit.height, at_limit.depth) == pytest.approx(
            ad.MAX_EXTENT_PERSON_HEIGHTS * ad.REFERENCE_PERSON_HEIGHT
        )


def test_small_objects_get_a_generous_bound_and_large_ones_a_tight_one() -> None:
    """A bound that let a cup reach 3 would also let a pillar reach 3."""
    cup = ad.max_scale("cup")
    pillar = ad.max_scale("pillar")
    assert cup is not None and pillar is not None
    assert cup > 10 * pillar


def test_site_plates_are_unbounded_and_the_rest_are_not() -> None:
    """`ground` at 50 is a 750 m plate -- the scene. A `pillar` at 50 is a 210 m column."""
    assert ad.max_scale("ground") is None
    assert ad.max_scale("floor") is None
    assert ad.max_scale("pillar") is not None


# ---------------------------------------------------------------------------
# The schema rejects them, with a message that helps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "scale"),
    [("pillar", 4.5), ("platform", 5), ("wall", 5), ("fence", 6), ("pillar", 10)],
)
def test_environment_rejects_an_implausible_scale(kind: str, scale: float) -> None:
    with pytest.raises(ValidationError) as caught:
        SceneEnvironmentObject.model_validate(
            {"id": "x", "type": kind, "position": [0, 0, 0], "scale": scale}
        )
    message = str(caught.value)
    assert kind in message
    assert "m person" in message


def test_props_are_bounded_too_not_just_the_environment() -> None:
    """The doc's examples were all environment, but a prop has the same problem."""
    with pytest.raises(ValidationError):
        SceneProp.model_validate(
            {"id": "x", "type": "weapon", "position": [0, 0, 0], "scale": 10.2}
        )


def test_the_message_names_the_axis_that_actually_exceeds() -> None:
    """A pillar that is too TALL must not be described by its width.

    "renders 18.9 m tall, which is 1.5x a person" reads as a contradiction and the
    author stops trusting the message, which is the only thing the message is for.
    """
    message = ad.scale_explanation("pillar", 4.5)
    assert message is not None
    assert "the tall extent" in message
    assert "10.8x" in message


def test_the_message_says_what_to_write_instead() -> None:
    """Rejecting without a usable alternative is how these values got written blind."""
    message = ad.scale_explanation("pillar", 4.5)
    assert message is not None
    assert f"scale {ad.max_scale('pillar'):.2f} or less" in message


def test_a_scale_exactly_at_the_bound_is_allowed() -> None:
    """Off-by-one boundaries reject the value an author was told to use."""
    limit = ad.max_scale("pillar")
    assert limit is not None
    SceneEnvironmentObject.model_validate(
        {"id": "x", "type": "pillar", "position": [0, 0, 0], "scale": limit}
    )


# ---------------------------------------------------------------------------
# Nothing that already worked may break
# ---------------------------------------------------------------------------


def test_the_hand_tuned_recomposition_still_validates() -> None:
    """`jinghai_recomposed.json` is the sample the bounds were calibrated against.

    If a bound rejects it, the bound is wrong -- not the fixture. The doc is explicit
    that those hand-tuned values are the "reasonable values" and that fixing this
    "cannot require changing them".
    """
    scene = json.loads((FIXTURES / "jinghai_recomposed.json").read_text(encoding="utf-8"))
    SceneScriptRoot.model_validate(scene)


@pytest.mark.parametrize(
    "name", ["motion_scene.json", "pivot_scene.json", "jinghai_gait_probe.json"]
)
def test_the_other_fixtures_still_validate(name: str) -> None:
    SceneScriptRoot.model_validate(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def test_every_declared_kind_is_covered_by_the_dimension_table() -> None:
    """A kind with no measured size gets no bound, which is the silent case."""
    declared = set(get_args(PropType)) | set(get_args(EnvironmentType))
    assert declared <= set(ad.ASSET_DIMENSIONS), (
        f"no measured size for {sorted(declared - set(ad.ASSET_DIMENSIONS))}, so a "
        "scale on one of these is unbounded and unchecked"
    )
