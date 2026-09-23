"""Creation flow guidance for the structured-derivation 3D previs pipeline (P4).

Defines the complete creation flow stages and generates next-step guidance
based on workflow state. This is the backend service that powers the guided
creation-flow UX (world → script → storyboard → 3D → binding → render).

Architecture:
    Workflow state (nodes + statuses)
        │
        ▼
    CreationFlowGuidanceService.assess_flow()
        │
        ▼
    FlowAssessment (current_stage, completed_stages, next_action, blockers)
        │
        ▼
    Frontend guided UX (progress indicator + next-step CTA)

Stages (per ADR bulletin §3 revised roadmap):
    1. world_setting  — World setting with multi-scene ownership (P4)
    2. script         — Script text (existing node)
    3. storyboard     — Storyboard panels with structured fields (P0 + P1a)
    4. scene_3d       — 3D previs SceneScript per panel (P1b + P2)
    5. binding        — Panel asset binding + speech_bindings (P2)
    6. render         — Video generation with previs reference (P3)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.schemas.agent_canvas import CanvasNodeV2


# ---------------------------------------------------------------------------
# Flow stage definitions
# ---------------------------------------------------------------------------


class CreationFlowStage(str, Enum):
    """Stages of the structured-derivation 3D previs creation flow."""

    WORLD_SETTING = "world_setting"
    SCRIPT = "script"
    STORYBOARD = "storyboard"
    SCENE_3D = "scene_3d"
    BINDING = "binding"
    RENDER = "render"


# Stage metadata: display name, description, required node types, next stage
FLOW_STAGE_METADATA: dict[CreationFlowStage, dict] = {
    CreationFlowStage.WORLD_SETTING: {
        "display_name": "World Setting",
        "description": "Define the world: era, rules, style, and owned scenes.",
        "creative_roles": ("world_setting",),
        "next_stage": CreationFlowStage.SCRIPT,
    },
    CreationFlowStage.SCRIPT: {
        "display_name": "Script",
        "description": "Write the script: dialogue, action, and narrative beats.",
        "node_types": ("script",),
        "next_stage": CreationFlowStage.STORYBOARD,
    },
    CreationFlowStage.STORYBOARD: {
        "display_name": "Storyboard",
        "description": "Generate storyboard panels with camera, action, and composition.",
        "creative_roles": ("storyboard_sequence",),
        "next_stage": CreationFlowStage.SCENE_3D,
    },
    CreationFlowStage.SCENE_3D: {
        "display_name": "3D Previs",
        "description": "Derive 3D low-fidelity previs from storyboard panels.",
        "node_types": ("scene-3d",),
        "next_stage": CreationFlowStage.BINDING,
    },
    CreationFlowStage.BINDING: {
        "display_name": "Asset Binding",
        "description": "Bind characters, props, scenes, and speech audio to panels.",
        "creative_roles": ("character", "prop", "scene"),
        # The binding does not have to be a node of its own.  A scene_3d_previs
        # node writes the whole scene script, and with it the characters,
        # environment, props and speech that its panels are bound to -- so a
        # previs-first workflow has every binding present on the canvas while this
        # stage's own creative_roles match nothing, and it used to report "No Asset
        # Binding node created yet" over a fully bound workflow.
        "binding_carrier_roles": ("scene_3d_previs",),
        "next_stage": CreationFlowStage.RENDER,
    },
    CreationFlowStage.RENDER: {
        "display_name": "Render",
        "description": "Generate final video with 3D previs as camera/blocking reference.",
        "creative_roles": ("storyboard_video",),
        "next_stage": None,
    },
}

# Stage order for progress calculation
FLOW_STAGE_ORDER: tuple[CreationFlowStage, ...] = (
    CreationFlowStage.WORLD_SETTING,
    CreationFlowStage.SCRIPT,
    CreationFlowStage.STORYBOARD,
    CreationFlowStage.SCENE_3D,
    CreationFlowStage.BINDING,
    CreationFlowStage.RENDER,
)


# ---------------------------------------------------------------------------
# Assessment data structures
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Binding content carried by a scene script
# ---------------------------------------------------------------------------


def scene_script_bindings(structured_content: dict | None) -> dict[str, list[str]]:
    """What a node's `structured_content.scene_script` says is bound to its panels.

    The 3D previs node is where the binding is actually authored: it emits the
    whole scene script, and inside it are `scene`, `environment`, `characters`,
    `props` and `speech_bindings`.  Nothing copies those onto the node's own
    fields -- `CanvasNodeV2` has none to copy them onto -- so this is the single
    place a binding can be read from, and it is on the canvas, not off it.

    Returns the ids of each kind, so a caller can report counts that mean
    something (`2 characters, 1 prop`) instead of only "a node exists".  A key is
    absent when the script declares nothing of that kind, and every list is ids
    or names, never the raw geometry.
    """
    script = (structured_content or {}).get("scene_script")
    if not isinstance(script, dict):
        return {}

    def _ids(entries: object) -> list[str]:
        if not isinstance(entries, list):
            return []
        out: list[str] = []
        for entry in entries:
            if isinstance(entry, dict):
                value = entry.get("id") or entry.get("name")
                if isinstance(value, str) and value:
                    out.append(value)
            elif isinstance(entry, str) and entry:
                out.append(entry)
        return out

    bindings: dict[str, list[str]] = {}
    scene = script.get("scene")
    if isinstance(scene, dict):
        name = scene.get("name") or scene.get("id")
        if isinstance(name, str) and name:
            bindings["scene"] = [name]
        environment = scene.get("environment")
        if environment:
            bindings["environment_type"] = [str(environment)]
    for key in ("characters", "props", "environment", "speech_bindings"):
        ids = _ids(script.get(key))
        if ids:
            bindings[key] = ids
    return bindings


def format_binding_summary(bindings: dict[str, list[str]]) -> str:
    """One line a person can read about what is bound, e.g. "1 scene, 1 character"."""
    if not bindings:
        return ""
    parts: list[str] = []
    for key, label in (
        ("scene", "scene"),
        ("characters", "character"),
        ("props", "prop"),
        ("environment", "environment object"),
        ("speech_bindings", "speech binding"),
    ):
        count = len(bindings.get(key) or [])
        if count:
            parts.append(f"{count} {label}{'s' if count != 1 else ''}")
    return ", ".join(parts)


@dataclass(frozen=True)
class StageStatus:
    """Status of one creation flow stage."""

    stage: CreationFlowStage
    display_name: str
    description: str
    completed: bool
    has_nodes: bool
    ready_nodes: int
    total_nodes: int
    blockers: tuple[str, ...] = ()
    # What is actually bound, when the stage's binding lives inside another node's
    # scene script rather than in nodes of its own.  Empty for stages that have no
    # such content, so it never has to be interpreted by the reader.
    binding_summary: str = ""


@dataclass(frozen=True)
class FlowAssessment:
    """Complete assessment of the creation flow for a workflow."""

    current_stage: CreationFlowStage
    current_stage_index: int
    completed_stages: tuple[CreationFlowStage, ...]
    stage_statuses: tuple[StageStatus, ...]
    progress_percent: float
    next_action: str
    next_action_detail: str
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return self.current_stage_index >= len(FLOW_STAGE_ORDER) - 1 and all(
            s.completed for s in self.stage_statuses
        )


# ---------------------------------------------------------------------------
# Guidance service
# ---------------------------------------------------------------------------


class CreationFlowGuidanceService:
    """Assess creation flow progress and generate next-step guidance.

    This service reads workflow node state and produces a FlowAssessment
    that the frontend can use for guided UX (progress indicator + next-step
    CTA + blocker diagnostics).
    """

    def assess_flow(self, *, nodes: list[CanvasNodeV2]) -> FlowAssessment:
        """Assess the creation flow for a list of workflow nodes.

        Args:
            nodes: List of canvas nodes in the workflow.

        Returns:
            FlowAssessment with current stage, progress, and next action.
        """
        stage_statuses: list[StageStatus] = []
        completed_stages: list[CreationFlowStage] = []
        blockers: list[str] = []
        warnings: list[str] = []

        # Assess each stage
        for stage in FLOW_STAGE_ORDER:
            status = self._assess_stage(stage=stage, nodes=nodes)
            stage_statuses.append(status)
            if status.completed:
                completed_stages.append(stage)
            blockers.extend(status.blockers)

        # Determine current stage (first incomplete stage, or last if all complete)
        current_stage_index = 0
        for i, status in enumerate(stage_statuses):
            if not status.completed:
                current_stage_index = i
                break
            current_stage_index = i
        else:
            current_stage_index = len(stage_statuses) - 1

        current_stage = FLOW_STAGE_ORDER[current_stage_index]

        # Calculate progress
        completed_count = len(completed_stages)
        progress_percent = (completed_count / len(FLOW_STAGE_ORDER)) * 100

        # Generate next action
        next_action, next_action_detail = self._generate_next_action(
            current_stage=current_stage,
            current_status=stage_statuses[current_stage_index],
        )

        # Warnings
        if not any(n.creative_role == "world_setting" for n in nodes):
            warnings.append(
                "No world_setting node found. Start by defining the world "
                "(era, rules, style) to establish visual continuity."
            )

        return FlowAssessment(
            current_stage=current_stage,
            current_stage_index=current_stage_index,
            completed_stages=tuple(completed_stages),
            stage_statuses=tuple(stage_statuses),
            progress_percent=round(progress_percent, 1),
            next_action=next_action,
            next_action_detail=next_action_detail,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )

    def _assess_stage(
        self,
        *,
        stage: CreationFlowStage,
        nodes: list[CanvasNodeV2],
    ) -> StageStatus:
        """Assess the completion status of one flow stage."""
        metadata = FLOW_STAGE_METADATA[stage]
        stage_nodes = self._filter_stage_nodes(stage=stage, nodes=nodes)
        # A stage's work can also be carried inside another node's scene script.
        # Only a node that actually declares bindings counts as a carrier, so an
        # empty previs does not complete the stage it merely sits next to.
        carriers = self._binding_carriers(stage=stage, nodes=nodes)
        has_nodes = len(stage_nodes) > 0 or bool(carriers)
        ready_nodes = sum(1 for n in stage_nodes if n.status == "ready") + len(carriers)
        total_nodes = len(stage_nodes) + len(carriers)

        # Completion criteria: has at least one ready node
        completed = has_nodes and ready_nodes > 0

        # Blockers
        blockers: list[str] = []
        if not has_nodes:
            blockers.append(f"No {metadata['display_name']} node created yet.")
        elif ready_nodes == 0:
            blockers.append(
                f"{metadata['display_name']} node(s) exist but none are ready "
                f"(status: {', '.join(sorted(set(n.status for n in stage_nodes)))})."
            )

        return StageStatus(
            stage=stage,
            display_name=metadata["display_name"],
            description=metadata["description"],
            completed=completed,
            has_nodes=has_nodes,
            ready_nodes=ready_nodes,
            total_nodes=total_nodes,
            blockers=tuple(blockers),
            binding_summary=format_binding_summary(
                self._carried_bindings(stage=stage, nodes=nodes)
            ),
        )

    def _binding_carriers(
        self,
        *,
        stage: CreationFlowStage,
        nodes: list[CanvasNodeV2],
    ) -> list[CanvasNodeV2]:
        """Nodes that carry this stage's work inside their scene script."""
        roles = FLOW_STAGE_METADATA[stage].get("binding_carrier_roles") or ()
        if not roles:
            return []
        carriers = [n for n in nodes if n.creative_role in roles]
        return [n for n in carriers if self._node_bindings(n)]

    def _node_bindings(self, node: CanvasNodeV2) -> dict[str, list[str]]:
        return scene_script_bindings(node.structured_content)

    def _carried_bindings(
        self,
        *,
        stage: CreationFlowStage,
        nodes: list[CanvasNodeV2],
    ) -> dict[str, list[str]]:
        """Merge every carrier's bindings, so the stage reports the union.

        Merged rather than per node because the stage is a fact about the
        workflow, not about one previs: six shots each naming `her` is one
        character bound, not six.
        """
        merged: dict[str, set[str]] = {}
        for node in self._binding_carriers(stage=stage, nodes=nodes):
            for key, ids in self._node_bindings(node).items():
                merged.setdefault(key, set()).update(ids)
        return {key: sorted(values) for key, values in merged.items()}

    def _filter_stage_nodes(
        self,
        *,
        stage: CreationFlowStage,
        nodes: list[CanvasNodeV2],
    ) -> list[CanvasNodeV2]:
        """Filter nodes that belong to a given flow stage."""
        metadata = FLOW_STAGE_METADATA[stage]
        result: list[CanvasNodeV2] = []

        for node in nodes:
            # Match by node_type if specified
            if "node_types" in metadata and node.node_type in metadata["node_types"]:
                result.append(node)
                continue
            # Match by creative_role if specified
            if "creative_roles" in metadata and node.creative_role in metadata["creative_roles"]:
                result.append(node)
                continue

        return result

    def _generate_next_action(
        self,
        *,
        current_stage: CreationFlowStage,
        current_status: StageStatus,
    ) -> tuple[str, str]:
        """Generate a human-readable next action and detail for the current stage."""
        if current_status.completed:
            next_stage = FLOW_STAGE_METADATA[current_stage].get("next_stage")
            if next_stage:
                next_metadata = FLOW_STAGE_METADATA[next_stage]
                return (
                    f"Move to {next_metadata['display_name']}",
                    f"{current_status.display_name} is complete. Next: {next_metadata['description']}",
                )
            return (
                "Flow complete",
                "All creation flow stages are complete. Review and export the final video.",
            )

        if not current_status.has_nodes:
            return (
                f"Create {current_status.display_name}",
                current_status.description,
            )

        # Nodes exist but not ready
        return (
            f"Run {current_status.display_name} node",
            f"{current_status.display_name} node(s) exist but need to be executed. "
            f"Click 'Run' on the {current_status.display_name.lower()} node to generate output.",
        )

    def get_stage_guidance(self, stage: CreationFlowStage) -> dict:
        """Get guidance metadata for a specific stage."""
        return FLOW_STAGE_METADATA[stage]

    def get_flow_stages(self) -> list[dict]:
        """Get all flow stages in order with metadata."""
        return [
            {
                "stage": stage.value,
                "index": i,
                **FLOW_STAGE_METADATA[stage],
            }
            for i, stage in enumerate(FLOW_STAGE_ORDER)
        ]
