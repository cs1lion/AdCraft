"""The two-fifths design share, and why a shot needs both kinds of reference.

The rose end-to-end run sent each video segment two pictures: the previs still
and a 3x3 tiling of previs frames standing in for a scene board.  Both were
renders of the same rough geometry, so the model had a motion reference and
nothing that said what the finished shot should look like -- and it reproduced
the rough model, decorating it in some segments and replacing it in others.  The
budget walk that allowed that was first-come in persisted binding order.

These tests pin the composition that replaces it.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.schemas.agent_canvas import (
    ResolvedMediaBindingInputV2,
    ResolvedNodeInputManifestV2,
)
from app.services.agent_canvas_reference_composition import (
    CLASS_CAMERA_MOTION,
    CLASS_DESIGN,
    CLASS_SUPPORTING,
    ReferenceBudget,
    compose_reference_budget,
    design_reference_budget,
    reference_composition_class,
)


def _input(
    binding_id: str,
    *,
    media_type: str = "image",
    input_role: str = "image_reference",
    semantic_role: str | None = None,
    binding_role: str | None = None,
    display_order: int = 0,
) -> ResolvedMediaBindingInputV2:
    return ResolvedMediaBindingInputV2(
        binding_id=binding_id,
        source_kind="node_output",
        source_node_id=f"node_{binding_id}",
        source_node_revision=3,
        input_role=input_role,  # type: ignore[arg-type]
        source_semantic_role=semantic_role,
        binding_metadata=(
            {"semantic_reference_role": binding_role} if binding_role else {}
        ),
        display_order=display_order,
        asset_id=f"asset_{binding_id}",
        asset_version_id=f"version_{binding_id}",
        media_type=media_type,  # type: ignore[arg-type]
        checksum=f"checksum_{binding_id}",
    )


def _budget(items, image_limit) -> ReferenceBudget:
    return compose_reference_budget(items, image_limit=image_limit)


# --- the share itself ------------------------------------------------------


@pytest.mark.parametrize(
    ("image_limit", "expected"),
    [
        (None, None),  # no provider limit: nothing to share
        (0, 0),
        (1, 0),  # one slot: motion must win
        (2, 1),
        (3, 1),
        (4, 2),
        (5, 2),  # exactly two fifths
        (9, 4),  # the video capability's published image limit
        (10, 4),
        (64, 26),
    ],
)
def test_the_design_share_is_roughly_two_fifths(image_limit, expected):
    assert design_reference_budget(image_limit) == expected


def test_a_single_image_slot_belongs_to_the_camera_motion_reference():
    """A finished look with no motion authority is worse than the reverse."""

    items = [
        _input("board", semantic_role="scene", display_order=0),
        _input("previs", semantic_role="storyboard_sequence", display_order=1),
    ]
    plan = _budget(items, 1)

    assert plan.admission == ("previs",)
    assert plan.withheld == frozenset({"board"})


def test_the_camera_motion_reference_survives_a_full_design_budget():
    """Design references are capped, so motion always keeps a slot."""

    design = [
        _input(f"design{index}", semantic_role="scene", display_order=index)
        for index in range(9)
    ]
    motion = _input("previs", semantic_role="storyboard_sequence", display_order=9)
    plan = _budget([*design, motion], 9)

    admitted_design = [
        binding_id
        for binding_id in plan.admission
        if binding_id != "previs"
    ]
    assert admitted_design == [f"design{index}" for index in range(4)]
    assert "previs" in plan.admission
    assert len(plan.withheld) == 5


def test_a_shot_with_no_camera_motion_reference_is_not_capped():
    """An image node carrying a lone turnaround has nothing to be crowded out by.

    Two design references with a two-slot budget would both be withheld if the
    share applied here, which would deliver *no* reference at all -- the share
    only means something when there is a motion reference to share with.
    """

    items = [
        _input("turnaround", semantic_role="character", display_order=0),
        _input("board", semantic_role="scene", display_order=1),
    ]
    plan = _budget(items, 2)

    assert plan.admission == ("turnaround", "board")
    assert plan.withheld == frozenset()


# --- classification -------------------------------------------------------


@pytest.mark.parametrize(
    ("semantic_role", "expected"),
    [
        ("character", CLASS_DESIGN),
        ("character_reference", CLASS_DESIGN),
        ("subject_reference", CLASS_DESIGN),
        ("scene", CLASS_DESIGN),
        ("scene_board", CLASS_DESIGN),
        ("scene_reference", CLASS_DESIGN),
        ("environment_reference", CLASS_DESIGN),
        ("storyboard_grid", CLASS_CAMERA_MOTION),
        ("storyboard_sequence", CLASS_CAMERA_MOTION),
        ("storyboard_visual_reference", CLASS_CAMERA_MOTION),
        ("product", CLASS_SUPPORTING),
        ("prop", CLASS_SUPPORTING),
        (None, CLASS_SUPPORTING),
        ("a_role_nobody_declared", CLASS_SUPPORTING),
    ],
)
def test_classification_covers_both_role_vocabularies(semantic_role, expected):
    item = _input("x", semantic_role=semantic_role)
    assert reference_composition_class(item) == expected


def test_a_previs_clip_is_the_motion_authority_even_with_no_image_role():
    """The camera lives in the previs node's animation, not in a role name."""

    clip = _input("previs", media_type="video", input_role="video_reference")
    assert reference_composition_class(clip) == CLASS_CAMERA_MOTION


def test_the_explicit_binding_role_describes_the_job_and_wins():
    """An operator's choice beats where the asset happened to come from."""

    item = _input("x", semantic_role="prop", binding_role="scene")
    assert reference_composition_class(item) == CLASS_DESIGN


# --- ordering -------------------------------------------------------------


def test_design_references_are_admitted_with_the_motion_reference_not_after_it():
    """The whole point: both kinds are in the request together."""

    items = [
        _input("previs", semantic_role="storyboard_sequence", display_order=0),
        _input("board", semantic_role="scene", display_order=1),
        _input("hero", semantic_role="character", display_order=2),
    ]
    plan = _budget(items, 9)

    # Persisted order would have put the previs still first and pushed the
    # design references out of a tight budget; composition reverses that.
    assert plan.admission == ("board", "hero", "previs")
    assert plan.withheld == frozenset()


def test_design_references_past_their_share_are_not_sent():
    """A share that over-share references can re-enter is not a ratio.

    With five image slots and four boards, the share is two.  Demoting the extra
    boards into a common pool -- as an earlier version did -- delivered three of
    the four, so the cap was really a priority and the delivered set was three
    fifths design.  They are withheld instead.
    """

    items = [
        _input("board_a", semantic_role="scene", display_order=0),
        _input("board_b", semantic_role="scene", display_order=1),
        _input("board_c", semantic_role="scene", display_order=2),
        _input("board_d", semantic_role="scene", display_order=3),
        _input("previs", semantic_role="storyboard_sequence", display_order=4),
    ]
    plan = _budget(items, 5)  # budget 2

    assert plan.admission == ("board_a", "board_b", "previs")
    assert plan.withheld == frozenset({"board_c", "board_d"})


def test_supporting_references_outrank_design_past_the_share():
    """The rest of the budget belongs to the shot's other references."""

    items = [
        _input("board_a", semantic_role="scene", display_order=0),
        _input("board_b", semantic_role="scene", display_order=1),
        _input("board_c", semantic_role="scene", display_order=2),
        _input("previs", semantic_role="storyboard_sequence", display_order=3),
        _input("prop", semantic_role="prop", display_order=4),
    ]
    plan = _budget(items, 5)  # budget 2

    assert plan.admission == ("board_a", "board_b", "previs", "prop")
    assert plan.withheld == frozenset({"board_c"})


def test_design_roles_take_turns_inside_the_share():
    """Six boards and two turnarounds: the turnarounds still ship.

    This is the rose video node's own binding set.  A walk in display order inside
    the share spends all four slots on boards and withholds both turnarounds, which
    is the failure the whole policy exists to prevent -- the model would again be
    shown six finished locations and never told what the woman looks like.

    The motion reference here is the bound **previs clip**, which reaches the
    provider through its own ``videos`` array and takes no image slot -- so it
    neither takes the share nor is charged for it.  All eight finished references
    are admitted and nothing is withheld as over-share; the trimming that would
    have lost the turnarounds is left to the provider's own image limit.  The
    interleave is still what decides the order they are walked in, so a tight
    provider limit spends its slots on the turnarounds rather than the boards.
    """

    boards = [
        _input(f"board{index}", semantic_role="scene", display_order=index)
        for index in range(6)
    ]
    turnarounds = [
        _input(f"hero{index}", semantic_role="character", display_order=10 + index)
        for index in range(2)
    ]
    motion = _input(
        "previs",
        media_type="video",
        input_role="video_reference",
        display_order=20,
    )
    plan = _budget([*boards, *turnarounds, motion], 9)  # budget 4 if it applied

    assert plan.admission == (
        "previs",
        "board0",
        "hero0",
        "board1",
        "hero1",
        "board2",
        "board3",
        "board4",
        "board5",
    )
    assert plan.withheld == frozenset()


def test_only_an_image_typed_motion_reference_shares_the_share():
    """The contrast that makes the video case deliberate rather than an accident.

    A ``storyboard_grid`` is the motion reference that *does* occupy image slots,
    so the share applies and the design tail is trimmed -- exactly as before.  Same
    eight references, same image limit, opposite outcome, and the only difference is
    which provider array the motion reference travels in.
    """

    design = [
        _input(f"board{index}", semantic_role="scene", display_order=index)
        for index in range(6)
    ] + [
        _input(f"hero{index}", semantic_role="character", display_order=10 + index)
        for index in range(2)
    ]
    grid = _input("grid", semantic_role="storyboard_grid", display_order=20)
    plan = _budget([*design, grid], 9)  # budget 4

    assert plan.admission == ("board0", "hero0", "board1", "hero1", "grid")
    assert plan.withheld == frozenset(
        {"board2", "board3", "board4", "board5"}
    )


def test_the_video_motion_reference_is_walked_before_the_design_tail():
    """Eight boards and one previs clip: the clip is the first one walked.

    With nothing sharing the image budget the design tail is uncapped, so walking
    it first lets eight boards spend all five of the provider's image slots and the
    provider's own limit drops the clip -- the shot that was bound for a camera
    move ships without one.  Admission order is the walk order under a tight limit
    only; the wire order stays ``display_order``.
    """

    boards = [
        _input(f"board{index}", semantic_role="scene", display_order=index)
        for index in range(8)
    ]
    motion = _input(
        "previs",
        media_type="video",
        input_role="video_reference",
        display_order=9,
    )
    plan = _budget([*boards, motion], 5)  # the provider's image limit

    assert plan.admission[0] == "previs"
    assert plan.admission[-1] == "board7"
    assert plan.withheld == frozenset()


def test_display_order_still_decides_inside_one_design_role():
    boards = [
        _input(f"board{index}", semantic_role="scene", display_order=index)
        for index in range(5)
    ]
    motion = _input(
        "previs",
        media_type="video",
        input_role="video_reference",
        display_order=9,
    )
    plan = _budget([*boards, motion], 9)

    # The clip leads the walk, but the boards behind it keep display order and all
    # five survive, because the previs clip does not spend the share on itself.
    assert plan.admission == (
        "previs",
        "board0",
        "board1",
        "board2",
        "board3",
        "board4",
    )
    assert plan.withheld == frozenset()


def test_no_limit_and_no_design_references_leaves_order_untouched():
    """Backwards compatible for shots that carry only one kind of reference."""

    items = [
        _input("grid", semantic_role="storyboard_grid", display_order=0),
        _input("clip", media_type="video", input_role="video_reference", display_order=1),
        _input("bgm", media_type="audio", input_role="audio_reference", display_order=2),
    ]
    plan = _budget(items, None)

    assert plan.admission == ("grid", "clip", "bgm")
    assert plan.withheld == frozenset()


def test_composition_accounts_for_every_bound_reference():
    items = [
        _input("a", semantic_role="scene", display_order=0),
        _input("b", semantic_role="character", display_order=1),
        _input("c", semantic_role="prop", display_order=2),
        _input("d", media_type="video", input_role="video_reference", display_order=3),
    ]
    plan = _budget(items, 4)

    assert set(plan.admission) | set(plan.withheld) == {"a", "b", "c", "d"}
    assert set(plan.admission) & set(plan.withheld) == set()


# --- the manifest walk that consumes it -----------------------------------


def _manifest(*items: ResolvedMediaBindingInputV2) -> ResolvedNodeInputManifestV2:
    return ResolvedNodeInputManifestV2(
        manifest_id="manifest_test",
        workflow_id="wf_test",
        execution_id="exec_test",
        node_run_id="run_test",
        target_node_id="node_video",
        workflow_revision=7,
        created_at=datetime(2026, 9, 22, 12, 0, 0),
        media_inputs=tuple(items),
    )


class _Resolution:
    """Only the capability metadata the walk reads."""

    def __init__(self, metadata: dict) -> None:
        self.capability_metadata = metadata


def _walk(items, *, image_limit: int | None, total_limit: int | None = None):
    from app.services.agent_canvas_resolved_inputs import apply_provider_reference_limits

    metadata: dict = {"reference_limits": {}}
    if image_limit is not None:
        metadata["reference_limits"]["image"] = image_limit
    if total_limit is not None:
        metadata["max_references"] = total_limit
    updated = apply_provider_reference_limits(_manifest(*items), _Resolution(metadata))
    return (
        [item.binding_id for item in updated.media_inputs],
        [item.binding_id for item in updated.omitted_optional_inputs],
    )


def test_a_tight_image_budget_still_carries_both_kinds():
    """The failure this module exists for, as one assertion."""

    # Persisted order puts the previs still first -- pre-vis binding order is
    # what produced an all-previs reference set before.
    items = [
        _input("previs", semantic_role="storyboard_sequence", display_order=0),
        _input("board", semantic_role="scene", display_order=1),
        _input("hero", semantic_role="character", display_order=2),
        _input("prop", semantic_role="prop", display_order=3),
    ]
    selected, omitted = _walk(items, image_limit=3)

    # Three slots: one design (the share of 3 is 1), the motion reference, and
    # one supporting.  The second design reference is over the share, and the
    # supporting reference outranks it, because two fifths that can be exceeded
    # is not a ratio.
    assert selected == ["board", "previs", "prop"]
    assert omitted == ["hero"]


def test_the_previs_only_reference_set_cannot_happen_again():
    """Nine design references and one previs clip: the clip still ships."""

    items = [
        _input(f"design{index}", semantic_role="scene", display_order=index)
        for index in range(9)
    ] + [_input("previs", semantic_role="storyboard_sequence", display_order=9)]
    selected, _ = _walk(items, image_limit=9)

    assert "previs" in selected
    assert len([item for item in selected if item.startswith("design")]) == 4


def test_a_withheld_design_reference_is_recorded_as_our_own_policy():
    """Not the provider's limit: the operator's fix is to bind fewer boards."""

    items = [
        _input("board_a", semantic_role="scene", display_order=0),
        _input("board_b", semantic_role="scene", display_order=1),
        _input("board_c", semantic_role="scene", display_order=2),
        _input("previs", semantic_role="storyboard_sequence", display_order=3),
    ]
    from app.services.agent_canvas_resolved_inputs import apply_provider_reference_limits

    updated = apply_provider_reference_limits(
        _manifest(*items),
        _Resolution({"reference_limits": {"image": 5}}),
    )
    codes = {
        item.binding_id: item.reason_code
        for item in updated.omitted_optional_inputs
    }

    assert codes == {"board_c": "omitted_reference_share"}
    # The identity record still has to be exact, or a frozen run cannot match the
    # omission back to its binding authority.
    omission = updated.omitted_optional_inputs[0]
    assert omission.asset_id == "asset_board_c"
    assert omission.asset_version_id == "version_board_c"
    assert omission.media_type == "image"
    assert omission.checksum == "checksum_board_c"


def test_omissions_still_carry_exact_asset_identity():
    """Phase ordering must not weaken the omission record."""

    items = [
        _input("previs", semantic_role="storyboard_sequence", display_order=0),
        _input("board", semantic_role="scene", display_order=1),
        _input("prop", semantic_role="prop", display_order=2),
    ]
    from app.services.agent_canvas_resolved_inputs import apply_provider_reference_limits

    updated = apply_provider_reference_limits(
        _manifest(*items),
        _Resolution({"reference_limits": {"image": 1}}),
    )
    by_binding = {item.binding_id: item for item in updated.omitted_optional_inputs}

    # With one slot: the board is over the share, the prop is over the provider's
    # limit.  Two different causes, two different codes, both exactly identified.
    assert set(by_binding) == {"board", "prop"}
    assert by_binding["board"].reason_code == "omitted_reference_share"
    assert by_binding["prop"].reason_code == "omitted_provider_reference_limit"
    for omission in by_binding.values():
        assert omission.asset_id
        assert omission.checksum
        assert omission.asset_version_id


def test_no_reference_limits_leaves_the_manifest_alone():
    items = [_input("a", semantic_role="scene", display_order=0)]
    manifest = _manifest(*items)

    from app.services.agent_canvas_resolved_inputs import apply_provider_reference_limits

    assert apply_provider_reference_limits(manifest, _Resolution({})) is manifest


def test_the_manifest_digest_changes_when_composition_changes_the_subset():
    """A different delivered set is a different manifest, not a rewrite."""

    items = [
        _input("previs", semantic_role="storyboard_sequence", display_order=0),
        _input("board", semantic_role="scene", display_order=1),
    ]
    before = _manifest(*items).manifest_digest
    from app.services.agent_canvas_resolved_inputs import apply_provider_reference_limits

    after = apply_provider_reference_limits(
        _manifest(*items), _Resolution({"reference_limits": {"image": 1}})
    ).manifest_digest

    assert before != after
