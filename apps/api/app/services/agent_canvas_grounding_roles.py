"""Canonical semantic roles for storyboard reference grounding."""

from __future__ import annotations

from typing import Final


_ROLE_ALIASES: Final[dict[str, str]] = {
    "storyboard_grid": "storyboard_grid",
    "storyboard_sequence": "storyboard_grid",
    "storyboard_visual_reference": "storyboard_grid",
    "character": "character_reference",
    "character_reference": "character_reference",
    "subject_reference": "character_reference",
    "scene": "scene_reference",
    "scene_board": "scene_reference",
    "scene_reference": "scene_reference",
    "environment_reference": "scene_reference",
    "product": "product_reference",
    "product_reference": "product_reference",
    "prop": "prop_reference",
    "prop_reference": "prop_reference",
}


def canonical_storyboard_reference_role(
    *,
    binding_role: object = None,
    source_role: object = None,
) -> str:
    """Project explicit binding and source roles to one grounding role."""

    values = tuple(
        value.strip()
        for value in (binding_role, source_role)
        if isinstance(value, str) and value.strip()
    )
    if not values:
        raise ValueError("v2_storyboard_reference_role_missing")
    canonical_roles = tuple(_ROLE_ALIASES.get(value) for value in values)
    if any(role is None for role in canonical_roles):
        raise ValueError("v2_storyboard_reference_role_invalid")
    unique_roles = set(canonical_roles)
    if len(unique_roles) != 1:
        raise ValueError("v2_storyboard_reference_role_mismatch")
    return canonical_roles[0]  # type: ignore[return-value]


def canonical_reference_role_or_none(value: object) -> str | None:
    """Normalize one role name, or return None when it names no known role.

    ``canonical_storyboard_reference_role`` refuses to guess: it raises when two
    roles disagree or when neither is known, because the storyboard grounding
    plan is version-pinned and a wrong role would mis-describe the shot.  Budget
    composition is the opposite situation -- it has to classify every bound
    reference, including ones whose role vocabulary comes from the automatic
    reference planner rather than a grounding rule, and it must not raise on a
    role it has simply never seen.  Falling back to "supporting" there only costs
    a slot ordering; raising would fail the whole run.
    """

    if not isinstance(value, str):
        return None
    return _ROLE_ALIASES.get(value.strip())
