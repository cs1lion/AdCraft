"""An uploaded scene board or turnaround must be able to reference a previs.

``_roles`` has declared ``("image", "scene-3d"): ("image_reference",)`` since
the 3D previs shipped, but ``decide`` narrows that table through the shorter
``image_asset_targets`` whenever the source is an asset -- and that second table
had no scene-3d key.  So the rule was unreachable for exactly the source that
carries a scene design board or a character turnaround: binding either to a
scene-3d node failed with ``canvas_connection_incompatible``, the previs ran
with no scene reference at all, and the video node sitting next to it accepted
the same asset without complaint.

These tests pin the two halves of that: the asset edge is accepted, and the
narrowing table still refuses everything an asset genuinely cannot contribute.
"""

from __future__ import annotations

from app.services.agent_canvas_connection_policy import (
    AgentCanvasConnectionPolicyService,
)


def _decide(policy: AgentCanvasConnectionPolicyService, *, source, target, is_asset):
    return policy.decide(
        source_node_type=source,
        target_node_type=target,
        input_role=None,
        is_image_asset=is_asset,
    )


def test_scene_asset_may_reference_a_scene_3d_previs() -> None:
    policy = AgentCanvasConnectionPolicyService()

    decision = _decide(
        policy, source="image", target="scene-3d", is_asset=True
    )

    assert decision.accepted, decision.error_code
    assert decision.input_role == "image_reference"
    assert decision.input_type == "image"


def test_asset_to_scene_3d_matches_what_a_generated_image_node_gets() -> None:
    """The declared ``_roles`` rule and the asset rule must not disagree."""

    policy = AgentCanvasConnectionPolicyService()

    from_node = _decide(policy, source="image", target="scene-3d", is_asset=False)
    from_asset = _decide(policy, source="image", target="scene-3d", is_asset=True)

    assert from_node.accepted
    assert from_node.input_role == from_asset.input_role == "image_reference"


def test_asset_still_cannot_become_text_context() -> None:
    """Widening the table must not let an asset play a text role."""

    policy = AgentCanvasConnectionPolicyService()

    for target in ("text", "script", "audio", "voice-cast"):
        decision = _decide(policy, source="image", target=target, is_asset=True)
        assert not decision.accepted, f"{target} accepted an image asset"
        assert decision.error_code == "canvas_connection_incompatible"


def test_scene_3d_output_may_feed_the_video_node() -> None:
    """The previs -> video edge is the canonical one; it must stay open."""

    policy = AgentCanvasConnectionPolicyService()

    decision = _decide(policy, source="scene-3d", target="video", is_asset=False)

    assert decision.accepted, decision.error_code
    assert decision.input_role == "video_reference"
    assert decision.input_type == "video"


def test_public_policy_publishes_the_scene_3d_asset_target() -> None:
    """The published policy is what the frontend draws its allow-list from."""

    policy = AgentCanvasConnectionPolicyService()

    targets = policy.public_policy().image_asset_targets

    assert targets["scene-3d"] == ("image_reference",)
    assert targets["image"] == ("image_reference",)
    assert targets["video"] == ("image_reference",)
