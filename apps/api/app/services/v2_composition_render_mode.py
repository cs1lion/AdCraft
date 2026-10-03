"""Choose the renderer that can actually honor the accepted authoring timeline."""

from __future__ import annotations

from app.schemas.workflow_v2 import WorkflowV2Timeline


def effective_composition_render_mode(configured_mode: str, timeline: WorkflowV2Timeline) -> str:
    """Keep legacy sequence defaults, but never discard explicitly authored edits."""
    if (
        timeline.metadata.get("requires_timeline_editor") is True
        or timeline.metadata.get("edit_mode") == "user_edited"
    ):
        return "timeline_editor"
    return configured_mode.strip().lower()
