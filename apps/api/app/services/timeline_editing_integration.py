"""
Timeline → Editing Integration Service (ADR 0007, Phase 2)

Integrates the global timeline into the editing export pipeline:
- Check if timeline has video clips
- If yes, convert timeline to EditingManifestV2 using TimelineEditingAdapter
- Optionally merge with node's existing manifest
- Backward compatible: no timeline clips → use node's original manifest
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.persistence.timeline_repository import TimelineRepository
from app.schemas.agent_canvas_editing import EditingManifestV2
from app.schemas.timeline import TimelineV1
from app.services.timeline_editing_adapter import (
    TimelineEditingAdapter,
    TimelineEditingConversionResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TimelineIntegrationResult:
    """Result of timeline integration check."""

    used_timeline: bool
    manifest: EditingManifestV2
    timeline: TimelineV1 | None = None
    conversion_result: TimelineEditingConversionResult | None = None
    reason: str = ""


class TimelineEditingIntegrationService:
    """Integrate global timeline into editing export pipeline."""

    def __init__(
        self,
        *,
        timeline_repository: TimelineRepository,
        adapter: TimelineEditingAdapter | None = None,
        min_video_clips: int = 1,
    ) -> None:
        self._timeline_repository = timeline_repository
        self._adapter = adapter or TimelineEditingAdapter()
        self._min_video_clips = min_video_clips

    def build_export_manifest(
        self,
        *,
        workflow_id: str,
        editing_node_id: str,
        node_manifest: EditingManifestV2,
    ) -> TimelineIntegrationResult:
        """Build the final export manifest, preferring timeline if available.

        Args:
            workflow_id: The workflow ID.
            editing_node_id: The editing node ID.
            node_manifest: The manifest from the editing node's structured_content.

        Returns:
            TimelineIntegrationResult with the final manifest and integration info.
        """
        # Get timeline (auto-creates default if not exists)
        try:
            timeline = self._timeline_repository.get_by_workflow_id(workflow_id)
        except Exception as error:
            logger.warning(
                "Failed to get timeline for workflow %s: %s",
                workflow_id,
                error,
            )
            return TimelineIntegrationResult(
                used_timeline=False,
                manifest=node_manifest,
                reason=f"timeline_access_error: {error}",
            )

        # Count video clips
        video_clips = self._get_clips_by_track_type(timeline, "video")

        if len(video_clips) < self._min_video_clips:
            return TimelineIntegrationResult(
                used_timeline=False,
                manifest=node_manifest,
                timeline=timeline,
                reason=f"insufficient_video_clips: {len(video_clips)} < {self._min_video_clips}",
            )

        # Check if video clips have valid assets
        valid_video_clips = [
            clip for clip in video_clips if clip.asset_id
        ]

        if not valid_video_clips:
            return TimelineIntegrationResult(
                used_timeline=False,
                manifest=node_manifest,
                timeline=timeline,
                reason="no_video_clips_with_assets",
            )

        # Convert timeline to editing manifest
        try:
            conversion_result = self._adapter.convert(
                timeline,
                editing_node_id=editing_node_id,
            )
        except Exception as error:
            logger.warning(
                "Failed to convert timeline to manifest for workflow %s: %s",
                workflow_id,
                error,
            )
            return TimelineIntegrationResult(
                used_timeline=False,
                manifest=node_manifest,
                timeline=timeline,
                reason=f"conversion_error: {error}",
            )

        # Validate the converted manifest
        if not conversion_result.manifest.video_entries:
            return TimelineIntegrationResult(
                used_timeline=False,
                manifest=node_manifest,
                timeline=timeline,
                conversion_result=conversion_result,
                reason="converted_manifest_has_no_video_entries",
            )

        # Use timeline manifest, but preserve node's output settings
        timeline_manifest = conversion_result.manifest.model_copy(
            update={
                "output": node_manifest.output,
                "manifest_revision": node_manifest.manifest_revision,
            }
        )

        logger.info(
            "Using timeline manifest for editing export: workflow=%s, node=%s, "
            "video_entries=%d, audio_entries=%d, ducking=%s, duration=%.1fs",
            workflow_id,
            editing_node_id,
            len(timeline_manifest.video_entries),
            len(timeline_manifest.audio_entries),
            "on" if timeline_manifest.ducking and timeline_manifest.ducking.enabled else "off",
            timeline_manifest.timeline_duration_seconds or 0.0,
        )

        return TimelineIntegrationResult(
            used_timeline=True,
            manifest=timeline_manifest,
            timeline=timeline,
            conversion_result=conversion_result,
            reason="timeline_applied",
        )

    def get_timeline_status(
        self,
        workflow_id: str,
    ) -> dict[str, object]:
        """Get timeline status for display in UI.

        Returns a dict with:
        - has_timeline: bool
        - video_clip_count: int
        - voice_clip_count: int
        - bgm_clip_count: int
        - sfx_clip_count: int
        - total_duration_seconds: float
        - can_override_editing: bool
        """
        try:
            timeline = self._timeline_repository.get_by_workflow_id(workflow_id)
        except Exception:
            return {
                "has_timeline": False,
                "video_clip_count": 0,
                "voice_clip_count": 0,
                "bgm_clip_count": 0,
                "sfx_clip_count": 0,
                "total_duration_seconds": 0.0,
                "can_override_editing": False,
            }

        video_clips = self._get_clips_by_track_type(timeline, "video")
        valid_video_clips = [c for c in video_clips if c.asset_id]

        return {
            "has_timeline": True,
            "video_clip_count": len(video_clips),
            "voice_clip_count": len(self._get_clips_by_track_type(timeline, "voice")),
            "bgm_clip_count": len(self._get_clips_by_track_type(timeline, "bgm")),
            "sfx_clip_count": len(self._get_clips_by_track_type(timeline, "sfx")),
            "total_duration_seconds": timeline.duration_seconds or 0.0,
            "can_override_editing": len(valid_video_clips) >= self._min_video_clips,
        }

    def _get_clips_by_track_type(
        self,
        timeline: TimelineV1,
        track_type: str,
    ) -> list:
        """Get all clips from a specific track type."""
        for track in timeline.tracks:
            if track.type == track_type:
                return list(track.clips)
        return []
