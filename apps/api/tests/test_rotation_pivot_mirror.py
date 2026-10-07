"""The rotation pivot must be the SAME on both sides of the render boundary.

``rotation_pivot.py`` is the single source of truth for the pivot table, and the
frontend re-exports the GENERATED copy of it rather than keeping its own. So this
does not compare two hand-maintained tables -- it checks that the committed
generated file is byte-identical to what the generator produces from the backend
table. That is the same drift guarantee the prop types and palette already have,
extended to the pivot.

The failure this guards against is silent and asymmetric: the preview would spin a
crate on its own axis while the Blender render tumbled it around its base, and no
other gate compares the two renderers.
"""

from __future__ import annotations

from app.cli.generate_scene_script_preview_contract import (
    DEFAULT_OUTPUT,
    render_typescript,
)
from app.services.scene3d.rotation_pivot import KIND_ROTATION_PIVOT, rotation_pivot_for


def test_generated_contract_is_up_to_date() -> None:
    """The checked-in generated file must match the generator's output exactly."""
    assert DEFAULT_OUTPUT.read_text(encoding="utf-8") == render_typescript(), (
        f"{DEFAULT_OUTPUT} is stale. Run:\n"
        "  cd apps/api && uv run python -m app.cli.generate_scene_script_preview_contract"
    )


def test_generated_contract_carries_the_pivot_table() -> None:
    """The frontend must actually receive the pivots, not just the backend know them."""
    generated = render_typescript()
    assert "KIND_ROTATION_PIVOT" in generated
    for kind in KIND_ROTATION_PIVOT:
        assert f'"{kind}":' in generated, f"{kind} is missing from the generated contract"


def test_door_pivot_is_a_hinge_not_a_centroid() -> None:
    """A door turns about an edge, which is what makes this per-kind and not a rule.

    If a refactor ever "simplifies" the table into a computed centroid, this is the
    entry that breaks -- and it is the entry whose breakage a screenshot would not
    catch, because a door swinging about its middle still looks like a moving door.
    """
    assert KIND_ROTATION_PIVOT["door"] == (-0.5, 0.0, 0.0)


def test_kinds_without_pivots_turn_about_their_base() -> None:
    """Ground-standing kinds are absent on purpose: the base is the right pivot.

    A tree sways about its root and a staircase tips about its foot, so listing
    them would be wrong. This test exists so that adding them is a deliberate,
    reviewed act rather than an accident of coverage.
    """
    for kind in (
        "tree", "stairs", "round_table", "rect_table", "chair", "stool",
        "floor", "ground", "fence",
    ):
        assert kind not in KIND_ROTATION_PIVOT, (
            f"{kind} turns about its base; a pivot here would lift it off the ground"
        )
        assert rotation_pivot_for(kind) == (0.0, 0.0, 0.0)


def test_unknown_kind_falls_back_to_the_origin() -> None:
    """A kind with no entry turns about its authored position, never to nowhere."""
    assert rotation_pivot_for("no_such_kind") == (0.0, 0.0, 0.0)