"""Previs-anchor guardrail tests.

The change these cover: the playbook recorded a mandatory per-shot style suffix
("严禁素模/白模/低多边形 + 实拍电影质感", "v4/v6 实测有效") for video segments
anchored on a 3D previs, and nothing implemented it — the only record is the
author hand-rewriting prompts after two real failures (v1: the first shot came
back as a Blender grey model; v3: three of four shots kept a 3D-render look).

These test the guardrail and its trigger directly rather than driving the full
``AgentCanvasRolePromptCompiler.compile()``: no existing test calls that entry
point (it is reached through the preparation service), and the context model
demands document authority, occurrence provenance, and assertion blocks that
have nothing to do with what changed here.
"""

from __future__ import annotations

from app.schemas.agent_canvas_role_prompt_preparation import (
    RoleBindingSnapshotV2,
    RolePromptPreparationContextV2,
)
from app.services.agent_canvas_role_prompt_compiler import (
    _PREVIS_ANCHOR_GUARDRAIL,
    _PREVIS_SOURCE_ROLES,
)


def _binding(source_role: str | None) -> RoleBindingSnapshotV2:
    return RoleBindingSnapshotV2(
        binding_id="b1",
        binding_revision=1,
        source_node_id="scene-1",
        source_role=source_role,
        reference_purpose="previs_motion",
        display_order=0,
    )


def _context(source_role: str | None) -> RolePromptPreparationContextV2:
    return RolePromptPreparationContextV2(
        workflow_id="wf",
        node_id="node",
        node_revision=1,
        role_variant="video_segment",
        requirement_revision_id="req",
        requirement_revision_no=1,
        internal_skill_ref="skill",
        bindings=(_binding(source_role),),
        model_policy_revision=1,
        created_at="2026-10-06T00:00:00+00:00",
    )


class TestPrevisAnchorGuardrail:
    def test_the_previs_role_is_the_only_trigger(self):
        # "scene_3d_previs" is the creative role of the node that renders the
        # previs animation; if that string ever changes, the guardrail silently
        # stops firing and the blockout look leaks back in.
        assert "scene_3d_previs" in _PREVIS_SOURCE_ROLES

    def test_it_names_what_the_previs_is_for_before_what_to_ignore(self):
        # A model told only "do not look like the reference" may also drop the
        # blocking and camera motion the reference exists to carry.
        text = _PREVIS_ANCHOR_GUARDRAIL(_context("scene_3d_previs")).casefold()
        assert text.index("shot cutting, camera motion, blocking, timing") < text.index(
            "do not follow it for appearance"
        )

    def test_it_overrides_the_blockout_look(self):
        text = _PREVIS_ANCHOR_GUARDRAIL(_context("scene_3d_previs")).casefold()
        assert "no low-poly" in text
        assert "untextured" in text
        assert "grey-model" in text
        assert "3d-render look" in text
        assert "live-action cinematic footage" in text

    def test_it_cites_the_binding_it_came_from(self):
        # A guardrail that does not name the reference gives the author nothing
        # to check against when the output comes back wrong.
        text = _PREVIS_ANCHOR_GUARDRAIL(_context("scene_3d_previs"))
        assert "scene-1" in text

    def test_it_falls_back_to_a_generic_reference_when_unnamed(self):
        text = _PREVIS_ANCHOR_GUARDRAIL(_context(None))
        assert "the bound 3d previs" in text.casefold()
