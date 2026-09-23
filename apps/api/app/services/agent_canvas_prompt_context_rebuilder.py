"""Rebuild the immutable Stage authoring context for prompt preparation.

The dispatch outbox stores one frozen ``StageAuthoringContextV1`` per
preparation operation.  Node writers that cannot name a Stage context at
mutation time leave the row without a snapshot.  This service reconstructs
the snapshot from the workflow's current authoritative state so a missing
snapshot can be persisted exactly once and the bounded worker can proceed
instead of failing closed.

Reconstruction is a repair path only: rows that already carry a frozen
snapshot are never rewritten, and the result is deliberately re-derived
from current state (session, requirement ledger, working document, style
anchor) rather than invented from dispatch identity.  Workflows that
carry a usable guidance session rebuild from the frozen journey.  A
workflow that exists but has no guidance session — a free-authoring
canvas created directly via API or manual node addition — receives a
minimal context synthesized from the node itself and its current
requirement ledger.  Unknown workflows and workflows without a readable
requirement ledger still return ``None`` and keep the legacy fail-closed
behavior, because a snapshot must be backed by authoritative state.
"""

from __future__ import annotations

from typing import Protocol

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.errors import V2PersistenceError
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_creative_session import CreativeGoalV2
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1
from app.services.agent_canvas_role_prompt_context import resolve_role_prompt_variant


class _GuidanceSession(Protocol):
    session_id: str
    revision: int
    goal: object
    journey: object


class _ConversationRepository(Protocol):
    def get_guidance_session_or_none(self, workflow_id: str) -> _GuidanceSession | None: ...


class _RequirementRepository(Protocol):
    def get_current(self, workflow_id: str) -> object: ...


class _DocumentRepository(Protocol):
    def build_bounded_context(self, document_id: str, selector: str) -> object: ...


# Role variant -> authoring skill, aligned with the materialization table in
# ``agent_canvas_stage_authoring_context`` (capability ids collapsed into the
# variants that actually drive Node prompt compilation).
_SKILL_REFS: dict[str, str] = {
    "world_view": "agent/skills/video_agent_world_setting/SKILL.md",
    "product_main": "agent/skills/video_agent_product_design/SKILL.md",
    "product_multiview": "agent/skills/video_agent_product_design/SKILL.md",
    "prop": "agent/skills/video_agent_prop_design/SKILL.md",
    "character_main": "agent/skills/video_agent_character_design/SKILL.md",
    "character_turnaround": "agent/skills/video_agent_character_design/SKILL.md",
    "scene_board": "agent/skills/video_agent_scene_design/SKILL.md",
    "script": "agent/skills/video_agent_script_authoring/SKILL.md",
    "storyboard_grid": "agent/skills/video_agent_storyboard_design/SKILL.md",
    "video_segment": "agent/skills/video_agent_video_direction/SKILL.md",
    "bgm": "agent/skills/video_agent_bgm_direction/SKILL.md",
    "free_text": "agent/skills/video_agent_video_direction/SKILL.md",
    "free_image": "agent/skills/video_agent_video_direction/SKILL.md",
    "free_video": "agent/skills/video_agent_video_direction/SKILL.md",
    "free_audio": "agent/skills/video_agent_video_direction/SKILL.md",
}


def skill_ref_for_node(node: CanvasNodeV2) -> str:
    """Pick the authoring skill for a Node by its resolved role variant."""

    try:
        role_variant = resolve_role_prompt_variant(node)
    except Exception:
        return _SKILL_REFS["script"]
    return _SKILL_REFS.get(role_variant, _SKILL_REFS["script"])


def _facts_from_requirement(requirement: object) -> dict[str, object]:
    """Project the current hard controls of one ledger into plain facts."""

    controls = getattr(requirement, "hard_controls", None)
    if controls is None:
        ledger = getattr(requirement, "ledger", None)
        controls = getattr(ledger, "hard_controls", ())
    facts: dict[str, object] = {}
    for item in controls:
        control = getattr(item, "control", None)
        if control is None:
            continue
        facts[str(control)] = getattr(item, "value", None)
    return facts


class PromptContextRebuilder:
    """Reconstruct one current Stage authoring context from workflow state."""

    def __init__(
        self,
        *,
        workflows: AgentCanvasWorkflowRepository,
        conversations: _ConversationRepository,
        requirements: _RequirementRepository,
        documents: _DocumentRepository | None = None,
    ) -> None:
        self._workflows = workflows
        self._conversations = conversations
        self._requirements = requirements
        self._documents = documents

    def build(self, workflow_id: str, node: CanvasNodeV2) -> StageAuthoringContextV1 | None:
        """Rebuild one Node context, or ``None`` when no authoritative state exists."""

        session = self._conversations.get_guidance_session_or_none(workflow_id)
        if session is None:
            # Free-authoring path: nodes created directly via API or manual
            # canvas addition have no guidance session. Synthesize a minimal
            # context from the node and its ledger; unknown workflows and
            # ledgeless workflows still fail closed there.
            return self._build_free_authoring_context(workflow_id, node)
        stage = session.journey.stage
        if not isinstance(stage, str) or not stage:
            return None

        requirement_facts: dict[str, object] = {}
        requirement = self._requirements.get_current(workflow_id)
        if requirement is not None:
            requirement_facts = _facts_from_requirement(requirement)

        style_projection: str | None = None
        style_anchor_node_id = node.metadata.get("style_anchor_node_id")
        if isinstance(style_anchor_node_id, str) and style_anchor_node_id:
            anchor = self._workflows.get_node(workflow_id, style_anchor_node_id)
            style = anchor.structured_content.get("style")
            if style is not None:
                style_projection = str(style)[:8192]

        context_kwargs: dict[str, object] = {}
        sequence_id = node.metadata.get("source_sequence_id")
        plan_document_id = node.metadata.get("source_agent_document_id")
        if sequence_id and plan_document_id and self._documents is not None:
            build_context = getattr(self._documents, "build_bounded_context", None)
            if build_context is not None:
                context_kwargs["working_document_excerpts"] = (
                    build_context(str(plan_document_id), f"sequence:{sequence_id}"),
                )
        if style_projection is not None:
            context_kwargs["style_projection"] = style_projection
        occurrence_id = node.metadata.get("occurrence_id")
        if isinstance(occurrence_id, str) and occurrence_id:
            context_kwargs["occurrence_id"] = occurrence_id

        return StageAuthoringContextV1(
            workflow_id=workflow_id,
            session_id=str(session.session_id),
            session_revision=int(session.revision),
            stage=stage,
            creative_goal=session.goal,
            requirement_facts=requirement_facts,
            internal_skill_ref=skill_ref_for_node(node),
            **context_kwargs,
        )

    def _build_free_authoring_context(
        self,
        workflow_id: str,
        node: CanvasNodeV2,
    ) -> StageAuthoringContextV1 | None:
        """Synthesize a context for a free-authoring Node, or fail closed.

        A workflow created directly via API or manual canvas addition has no
        guidance session, but it does own authoritative state: a workflow
        shell and a requirement ledger. The synthesized snapshot is built
        only from that state plus the node itself (stage from node type,
        creative goal from node type and title/prompt, skill from the role
        variant). Unknown workflows and workflows without a readable ledger
        return ``None`` so the legacy terminal failure is preserved.
        """

        try:
            self._workflows.get_workflow(workflow_id)
        except V2PersistenceError as error:
            if error.code != "workflow_not_found":
                raise
            return None
        try:
            requirement = self._requirements.get_current(workflow_id)
        except V2PersistenceError as error:
            if error.code != "requirement_ledger_not_found":
                raise
            return None
        requirement_facts = _facts_from_requirement(requirement)

        stage = _default_stage_for_node(node)
        requested_output = (
            node.node_type
            if node.node_type in {"text", "script", "image", "video", "audio"}
            else "text"
        )
        delivery_scope = (
            "generated_media" if node.node_type in {"image", "video", "audio"} else "draft"
        )
        summary = node.title or node.generation_prompt or f"Free-authoring {node.node_type} node"
        summary = summary[:4096] if len(summary) > 4096 else summary

        creative_goal = CreativeGoalV2(
            requested_output=requested_output,
            delivery_scope=delivery_scope,
            summary=summary,
        )

        context_kwargs: dict[str, object] = {}
        style_projection: str | None = None
        style_anchor_node_id = node.metadata.get("style_anchor_node_id")
        if isinstance(style_anchor_node_id, str) and style_anchor_node_id:
            try:
                anchor = self._workflows.get_node(workflow_id, style_anchor_node_id)
                style = anchor.structured_content.get("style")
                if style is not None:
                    style_projection = str(style)[:8192]
            except Exception:
                pass
        if style_projection is not None:
            context_kwargs["style_projection"] = style_projection
        occurrence_id = node.metadata.get("occurrence_id")
        if isinstance(occurrence_id, str) and occurrence_id:
            context_kwargs["occurrence_id"] = occurrence_id

        return StageAuthoringContextV1(
            workflow_id=workflow_id,
            session_id=f"free_authoring_{workflow_id}",
            session_revision=1,
            stage=stage,
            creative_goal=creative_goal,
            requirement_facts=requirement_facts,
            internal_skill_ref=skill_ref_for_node(node),
            **context_kwargs,
        )


def _default_stage_for_node(node: CanvasNodeV2) -> str:
    """Derive a default journey stage from node type and creative role."""

    node_type = node.node_type
    role = node.creative_role

    if role == "world_setting" or node_type == "text" and "world" in (role or "").lower():
        return "world_view"
    if role in {"product", "product_main", "product_multiview"}:
        return "product"
    if role == "prop":
        return "props"
    if role in {"character", "character_main", "character_turnaround"}:
        return "character"
    if role == "scene":
        return "scene"
    if node_type == "script" or role == "script":
        return "narrative_direction"
    if role == "storyboard" or "storyboard" in (role or ""):
        return "storyboard_grids"
    if node_type == "video" or role in {"video", "general_video", "storyboard_video"}:
        return "videos"
    if node_type == "audio" or role == "bgm":
        return "bgm"
    if node_type == "editing":
        return "editing"
    # Default for free text/general nodes
    return "intake"
