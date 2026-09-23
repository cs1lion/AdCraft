"""How a shot's references share the provider's reference budget.

A video clip is grounded by two different kinds of picture and they do different
jobs.  The **camera-motion reference** is the rough-model (3D previs) frame or
clip: it is the only thing that says how the shot moves, so losing it leaves the
model inventing a camera.  The **design references** are the character turnaround
and the scene design board: they are the only things that say what the shot is
supposed to *look like* when it is finished, so losing them leaves the model with
the rough model's own look -- flat-shaded primitives, no materials, no grade.

The rule this module enforces is the one the operator stated: the design
references are delivered **together with** the camera-motion reference, and they
take roughly **two fifths** of the image budget.  Neither kind may crowd the
other out.

Before this, budget composition was a blind first-come walk in display order
(``apply_provider_reference_limits``).  That made the delivered set a function of
binding order rather than of what the references are for, which is how a shot
ended up sending only previs-derived pictures: the previs still and a 3x3 tiling
of previs frames, with no character and no finished scene anywhere in the request.
The model then had no target look to aim at and reproduced the rough geometry,
sometimes decorating it instead of replacing it.

The share is a **cap**, not a priority.  Demoting an over-share design reference
into a common pool would let it back in through that pool, which is how nine scene
boards still occupied eight of nine slots -- two fifths that can be exceeded is
not a ratio.  A design reference past its share is therefore withheld and recorded
as an omission, so the delivered set stays near the ratio and the operator can see
what was not sent and why.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.schemas.agent_canvas import ResolvedMediaBindingInputV2
from app.services.agent_canvas_grounding_roles import canonical_reference_role_or_none

#: The share of the image reference budget the character/scene design references
#: are entitled to.  Roughly two fifths: enough that a finished look is always
#: carried, few enough that motion and supporting references keep the rest.
DESIGN_REFERENCE_SHARE_NUMERATOR = 2
DESIGN_REFERENCE_SHARE_DENOMINATOR = 5

#: Composition classes, in the order they are admitted to the budget.
CLASS_DESIGN = "design"
CLASS_CAMERA_MOTION = "camera_motion"
CLASS_SUPPORTING = "supporting"

_DESIGN_ROLES = frozenset({"character_reference", "scene_reference"})
_CAMERA_MOTION_ROLES = frozenset({"storyboard_grid"})


@dataclass(frozen=True)
class ReferenceBudget:
    """One shot's references divided into who is sent, who is not, and in what order.

    ``admission`` lists the binding ids that may be sent, ordered: design
    references first (up to their share, taking turns across character and scene),
    then the camera-motion references, then everything else.  ``withheld`` holds
    the design references past that share; they are not sent at all.
    """

    admission: tuple[str, ...] = ()
    withheld: frozenset[str] = field(default_factory=frozenset)


def design_reference_budget(image_limit: int | None) -> int | None:
    """How many image slots the design references may take, or None for no cap.

    None means the provider set no image limit, so there is no budget to share
    and every design reference is admitted.  A finite limit below 2 yields 0:
    with a single image slot the camera-motion reference has to win, because a
    clip with a finished look and no motion authority is worse than the reverse.
    At every larger limit the share is the closest integer to two fifths, so a
    limit of 5 reserves exactly 2, a limit of 9 reserves 4, and a limit of 2
    reserves the 1 that fits.
    """

    if image_limit is None:
        return None
    if image_limit < 2:
        return 0
    share = (
        image_limit * DESIGN_REFERENCE_SHARE_NUMERATOR
    ) / DESIGN_REFERENCE_SHARE_DENOMINATOR
    return max(1, round(share))


def reference_composition_class(item: ResolvedMediaBindingInputV2) -> str:
    """Which job this reference does, so the budget can share between them."""

    role = _reference_role(item)
    if role in _DESIGN_ROLES:
        return CLASS_DESIGN
    if role in _CAMERA_MOTION_ROLES:
        return CLASS_CAMERA_MOTION
    # A previs node contributes its animation as a video reference; the camera
    # lives in that clip, so it is the motion authority even when the bound
    # asset carries no image role at all.
    if item.media_type == "video" and item.input_role == "video_reference":
        return CLASS_CAMERA_MOTION
    return CLASS_SUPPORTING


def compose_reference_budget(
    items: Sequence[ResolvedMediaBindingInputV2],
    *,
    image_limit: int | None,
) -> ReferenceBudget:
    """Order one shot's references and withhold the design ones past their share.

    The share only means anything when there is a motion reference to share the
    budget *with*: an image node carrying a lone character turnaround has nothing
    to be crowded out by, and capping it at two fifths would withhold its only
    reference.  So a shot with no image-typed motion reference admits all of its
    design references and leaves the provider's own limit to do the trimming.

    Only an *image-typed* motion reference shares the image budget.  A ``video``
    reference is delivered through the provider's separate ``videos`` array and
    occupies no image slot, so it neither takes the share nor is charged for it.

    An image-typed motion reference is admitted after the design share, which
    keeps it inside the image budget: the share rounds below two fifths, so it
    always leaves at least one slot.  It is not given a reserved slot against a
    provider's separate ``max_references``, since a total smaller than that
    provider's own image limit would be contradictory metadata.

    When no design share applies the design tail is uncapped, so the motion and
    supporting references are walked *first*; otherwise eight scene boards spend
    all five image slots and the motion reference the shot was bound for is the
    one that gets trimmed.  Admission order is the walk order under a tight
    provider limit only -- the wire order is always ``display_order``.

    Inside the share the design references take turns across their roles, so a
    shot bound to six scene boards and two turnarounds keeps both turnarounds
    rather than spending the share on boards alone (see
    ``_design_admission_order``).
    """

    share = design_reference_budget(image_limit)
    ordered = sorted(items, key=lambda item: (item.display_order, item.binding_id))
    design = [item for item in ordered if reference_composition_class(item) == CLASS_DESIGN]
    motion = [item for item in ordered if reference_composition_class(item) == CLASS_CAMERA_MOTION]
    supporting = [
        item for item in ordered if reference_composition_class(item) == CLASS_SUPPORTING
    ]
    # Only an *image-typed* motion reference competes for the image budget.  A
    # previs clip is bound as ``media_type == "video"`` and reaches the provider
    # through its own ``videos`` array, which takes no image slot -- so charging
    # the design share for it withheld four finished references on the rose node
    # in exchange for a video that was never occupying those slots to begin with.
    # ``storyboard_grid`` is the image-typed motion reference that does share.
    has_image_motion = any(item.media_type == "image" for item in motion)
    design_budget = share if has_image_motion and share is not None else None
    # Inside the share the design references take turns, or one role can spend the
    # whole share on itself.
    design_admission = _design_admission_order(design)
    if design_budget is not None and len(design_admission) > design_budget:
        admitted_design = design_admission[:design_budget]
        withheld = design_admission[design_budget:]
    else:
        admitted_design = design_admission
        withheld = []
    motion_ids = [item.binding_id for item in motion]
    supporting_ids = [item.binding_id for item in supporting]
    if design_budget is None and motion:
        # Nothing shares the image budget, so the design tail is uncapped and
        # would otherwise be walked first: eight boards spend all five image
        # slots and ``omitted_provider_reference_limit`` drops the motion
        # reference this shot was bound for.  Admission order is only the walk
        # order for a tight limit -- the wire order stays ``display_order``
        # (``SeedanceInputManifestV1.media_inputs``) -- so this reorders *which*
        # references survive, never how they are sent.
        admission = (*motion_ids, *supporting_ids, *admitted_design)
    else:
        admission = (*admitted_design, *motion_ids, *supporting_ids)
    return ReferenceBudget(
        admission=admission,
        withheld=frozenset(withheld),
    )


def _design_admission_order(
    design: Sequence[ResolvedMediaBindingInputV2],
) -> list[str]:
    """Interleave design roles so no single one can take the whole share.

    A shot is routinely bound to six scene boards and two character turnarounds,
    and a walk in display order inside the share spends all four slots on boards
    and withholds *both* turnarounds -- which is precisely the shot the film was
    accused of, where the model was never told what the woman looked like.  Taking
    turns across roles in order of first appearance keeps both kinds of finished
    look in the request, and keeps display order inside each role.
    """

    groups: dict[str, list[str]] = {}
    for item in design:
        # Only character_reference and scene_reference reach here, so this is
        # never actually unset; "" just keeps the loop total over one bucket.
        role = _reference_role(item) or ""
        groups.setdefault(role, []).append(item.binding_id)
    interleaved: list[str] = []
    for depth in range(max((len(ids) for ids in groups.values()), default=0)):
        for ids in groups.values():
            if depth < len(ids):
                interleaved.append(ids[depth])
    return interleaved


def _reference_role(item: ResolvedMediaBindingInputV2) -> str | None:
    """The reference's role, preferring the explicit binding over the source.

    The explicit binding role is what an operator chose, so it describes the
    reference's *job*; the source semantic role describes where the asset came
    from, which is why an uploaded scene board and a generated one can disagree.
    """

    binding_role = item.binding_metadata.get("semantic_reference_role")
    return (
        canonical_reference_role_or_none(binding_role)
        or canonical_reference_role_or_none(item.source_semantic_role)
    )
