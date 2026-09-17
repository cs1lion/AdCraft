"""
Timeline Clip Auto-Creation Service (ADR 0007)

When a node completes execution and produces a media asset, this service
automatically creates a timeline clip on the appropriate track.

Mapping:
- video node → video track
- voice-cast node → voice track
- audio node (bgm role) → bgm track
- audio node (sfx role) → sfx track
- scene-3d node → camera track (previs camera motion)
- text/script node (subtitle role) → subtitle track
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select

from app.persistence.models import AssetVersionRow
from app.persistence.timeline_repository import TimelineRepository
from app.schemas.agent_canvas import CanvasNodeV2

logger = logging.getLogger(__name__)


@dataclass
class AutoClipContext:
    """Context for auto-creating a timeline clip from a completed node."""

    workflow_id: str
    node_id: str
    node_type: str
    semantic_role: str | None
    output_asset_id: str | None
    output_asset_version_id: str | None
    title: str | None
    duration_hint: float | None = None  # seconds, if known


# Node type → default track type mapping
NODE_TYPE_TO_TRACK: dict[str, str] = {
    "video": "video",
    "voice-cast": "voice",
    "scene-3d": "camera",
}

# Semantic role → track type (for audio nodes that can be bgm or sfx)
ROLE_TO_TRACK: dict[str, str] = {
    "bgm": "bgm",
    "background_music": "bgm",
    "sfx": "sfx",
    "sound_effect": "sfx",
    "subtitle": "subtitle",
    "captions": "subtitle",
}

# Default clip duration when unknown (seconds)
DEFAULT_CLIP_DURATION = 3.0


class TimelineClipAutoCreator:
    """Automatically creates timeline clips when nodes complete."""

    def __init__(
        self,
        repository_factory: Callable[[], TimelineRepository],
        *,
        enabled: bool = True,
    ) -> None:
        self._repository_factory = repository_factory
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def determine_track_type(self, context: AutoClipContext) -> str | None:
        """Determine which track a node's output should go to."""
        # First check semantic role (for audio nodes that can be bgm/sfx)
        if context.semantic_role:
            role_lower = context.semantic_role.lower()
            if role_lower in ROLE_TO_TRACK:
                return ROLE_TO_TRACK[role_lower]

        # Then check node type
        if context.node_type in NODE_TYPE_TO_TRACK:
            return NODE_TYPE_TO_TRACK[context.node_type]

        # Generic audio → sfx by default
        if context.node_type == "audio":
            return "sfx"

        # Text/script with subtitle-like role
        if context.node_type in {"text", "script"} and context.semantic_role:
            if "subtitle" in context.semantic_role.lower() or "caption" in context.semantic_role.lower():
                return "subtitle"

        return None

    def create_clip_for_node(self, context: AutoClipContext) -> str | None:
        """Create a timeline clip for a completed node. Returns clip_id or None."""
        if not self._enabled:
            return None

        track_type = self.determine_track_type(context)
        if track_type is None:
            logger.debug(
                "No timeline track mapping for node type=%s role=%s, skipping auto-clip",
                context.node_type,
                context.semantic_role,
            )
            return None

        try:
            repo = self._repository_factory()
            try:
                # Get or create timeline for this workflow
                timeline = repo.get_by_workflow_id(context.workflow_id)

                # Find the appropriate track
                track = next(
                    (t for t in timeline.tracks if t.type == track_type),
                    None,
                )
                if track is None:
                    logger.warning(
                        "Track type=%s not found in timeline %s",
                        track_type,
                        timeline.timeline_id,
                    )
                    return None

                # Determine start time: append after last clip on this track
                start_time = repo.get_next_start_time_for_track(track.track_id)

                # Determine duration: explicit hint → asset metadata → default
                duration = context.duration_hint
                if duration is None and context.output_asset_id:
                    duration = self._resolve_asset_duration(
                        repo,
                        asset_id=context.output_asset_id,
                        asset_version_id=context.output_asset_version_id,
                    )
                if duration is None or duration <= 0:
                    duration = DEFAULT_CLIP_DURATION

                # Create clip
                clip = repo.add_clip(
                    track_id=track.track_id,
                    start_time=start_time,
                    duration=duration,
                    asset_id=context.output_asset_id,
                    asset_version_id=context.output_asset_version_id,
                    source_node_id=context.node_id,
                    label=context.title or f"{context.node_type}: {context.node_id[:8]}",
                )

                logger.info(
                    "Auto-created timeline clip %s on %s track for node %s (start=%.1fs, dur=%.1fs)",
                    clip.clip_id,
                    track_type,
                    context.node_id,
                    start_time,
                    duration,
                )
                repo._session.commit()
                return clip.clip_id

            except Exception:
                if hasattr(repo, "_session"):
                    repo._session.rollback()
                raise
            finally:
                # Close the session if the repository has one
                if hasattr(repo, "_session"):
                    try:
                        repo._session.close()
                    except Exception:
                        pass
        except Exception as error:
            logger.warning(
                "Failed to auto-create timeline clip for node %s: %s",
                context.node_id,
                error,
                exc_info=True,
            )
            return None

    def _resolve_asset_duration(
        self,
        repo: TimelineRepository,
        *,
        asset_id: str,
        asset_version_id: str | None,
    ) -> float | None:
        """Look up the media duration from the published asset version.

        Prefers the exact published version, otherwise the latest version of
        the asset. Returns None when the asset has no recorded duration
        (e.g. images), so callers can fall back to the default clip length.
        """
        try:
            session = repo._session  # same V2 database as the timeline
            statement = select(AssetVersionRow.duration_seconds).where(
                AssetVersionRow.asset_id == asset_id
            )
            if asset_version_id:
                statement = statement.where(
                    AssetVersionRow.version_id == asset_version_id
                )
            else:
                statement = statement.order_by(
                    AssetVersionRow.version_no.desc()
                )
            duration = session.execute(statement.limit(1)).scalar_one_or_none()
        except Exception as error:
            logger.debug(
                "Could not resolve duration for asset %s: %s", asset_id, error
            )
            return None
        return float(duration) if duration is not None and duration > 0 else None

    def create_clip_from_node(
        self,
        node: CanvasNodeV2,
        *,
        output_asset_id: str | None,
        output_asset_version_id: str | None = None,
        duration_hint: float | None = None,
    ) -> str | None:
        """Convenience: create a clip directly from a node object."""
        context = AutoClipContext(
            workflow_id=node.workflow_id,
            node_id=node.node_id,
            node_type=node.node_type,
            semantic_role=node.semantic_role,
            output_asset_id=output_asset_id,
            output_asset_version_id=output_asset_version_id,
            title=node.title,
            duration_hint=duration_hint,
        )
        return self.create_clip_for_node(context)
