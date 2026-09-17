"""
Timeline → Editing Manifest Adapter (ADR 0007, Phase 1/2)

Converts the global multi-track timeline (TimelineV1) into an
EditingManifestV2 that the existing editing/export pipeline can consume.

This adapter enables:
- Video clips from the timeline → editing video_entries with exact timing
- Voice/BGM/SFX clips → editing audio_entries with exact timeline positions
- Auto-ducking configuration when both voice and BGM clips are present
- Backward compatibility: editing nodes without timeline clips still work
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from app.schemas.agent_canvas_editing import (
    EditingAudioEntryV2,
    EditingAudioTrackRoleV2,
    EditingDuckingConfigV2,
    EditingManifestV2,
    EditingVideoEntryV2,
)
from app.schemas.timeline import TimelineClipV1, TimelineTrackV1, TimelineV1

logger = logging.getLogger(__name__)

# Role-specific base playback levels; track volume multiplies these.
_ROLE_BASE_VOLUME: dict[str, float] = {
    "voice": 1.0,
    "sfx": 1.0,
    "bgm": 0.3,
}
_AUDIO_ROLES: tuple[EditingAudioTrackRoleV2, ...] = ("voice", "bgm", "sfx")


@dataclass(frozen=True, slots=True)
class TimelineEditingConversionResult:
    """Result of converting a timeline to an editing manifest."""

    manifest: EditingManifestV2
    video_clip_count: int
    voice_clip_count: int
    bgm_clip_count: int
    sfx_clip_count: int
    total_duration_seconds: float
    warnings: tuple[str, ...]


AssetResolver = Callable[[str], str | None]  # asset_id → file path or None


class TimelineEditingAdapter:
    """Convert global timeline clips to editing manifest format."""

    def __init__(
        self,
        *,
        asset_resolver: AssetResolver | None = None,
        default_video_duration: float = 3.0,
    ) -> None:
        self._asset_resolver = asset_resolver
        self._default_video_duration = default_video_duration

    def convert(
        self,
        timeline: TimelineV1,
        *,
        editing_node_id: str | None = None,
    ) -> TimelineEditingConversionResult:
        """Convert a timeline to an editing manifest.

        Args:
            timeline: The global timeline with all tracks and clips.
            editing_node_id: Optional editing node ID for source_key generation.

        Returns:
            TimelineEditingConversionResult with manifest and metadata.
        """
        warnings: list[str] = []

        # Get tracks by type
        tracks_by_type: dict[str, TimelineTrackV1] = {
            track.type: track for track in timeline.tracks
        }

        video_track = tracks_by_type.get("video")

        # Convert video clips
        video_entries: list[EditingVideoEntryV2] = []
        if video_track and video_track.clips:
            sorted_clips = sorted(video_track.clips, key=lambda c: c.start_time)
            for index, clip in enumerate(sorted_clips):
                entry = self._convert_video_clip(
                    clip,
                    index=index,
                    editing_node_id=editing_node_id,
                )
                if entry is not None:
                    video_entries.append(entry)
                else:
                    warnings.append(
                        f"Video clip {clip.clip_id} has no asset, skipped"
                    )
        else:
            warnings.append("No video clips in timeline")

        # Convert every voice/BGM/SFX clip to a timeline-positioned audio entry
        audio_entries: list[EditingAudioEntryV2] = []
        role_entry_counts = {"voice": 0, "bgm": 0, "sfx": 0}
        for role in _AUDIO_ROLES:
            track = tracks_by_type.get(role)
            if not track or not track.clips:
                continue
            for clip in sorted(track.clips, key=lambda c: c.start_time):
                entry = self._convert_audio_clip(clip, track=track, role=role)
                if entry is None:
                    reason = "is muted" if track.muted else "has no asset"
                    warnings.append(
                        f"{role.capitalize()} audio clip {clip.clip_id} {reason}, skipped"
                    )
                    continue
                audio_entries.append(entry)
                role_entry_counts[role] += 1

        # Auto-ducking only makes sense with both voice and BGM present.
        # - no stored config (None) → renderer defaults (auto behavior)
        # - stored config with enabled=False → ducking fully off
        # - stored config with enabled=True → user-tuned sidechain parameters
        ducking: EditingDuckingConfigV2 | None = None
        if role_entry_counts["voice"] > 0 and role_entry_counts["bgm"] > 0:
            configured = timeline.ducking
            if configured is None:
                ducking = EditingDuckingConfigV2()
            elif configured.enabled:
                ducking = EditingDuckingConfigV2(
                    enabled=True,
                    threshold_db=configured.threshold_db,
                    ratio=configured.ratio,
                    attack_ms=configured.attack_ms,
                    release_ms=configured.release_ms,
                    makeup_gain_db=configured.makeup_gain_db,
                )

        # Calculate total duration
        total_duration = self._calculate_total_duration(timeline)

        # Build manifest
        manifest = EditingManifestV2(
            video_entries=tuple(video_entries),
            audio_entries=tuple(audio_entries),
            ducking=ducking,
            timeline_duration_seconds=total_duration if video_entries else None,
        )

        return TimelineEditingConversionResult(
            manifest=manifest,
            video_clip_count=len(video_entries),
            voice_clip_count=role_entry_counts["voice"],
            bgm_clip_count=role_entry_counts["bgm"],
            sfx_clip_count=role_entry_counts["sfx"],
            total_duration_seconds=total_duration,
            warnings=tuple(warnings),
        )

    def _convert_video_clip(
        self,
        clip: TimelineClipV1,
        *,
        index: int,
        editing_node_id: str | None,
    ) -> EditingVideoEntryV2 | None:
        """Convert a timeline video clip to an EditingVideoEntryV2."""
        if not clip.asset_id:
            return None

        # Determine duration: use clip duration, fall back to default
        duration = clip.duration or self._default_video_duration

        # Determine source trimming
        source_start = clip.source_start or 0.0
        source_duration = clip.source_duration or duration

        return EditingVideoEntryV2(
            asset_id=clip.asset_id,
            timeline_start_seconds=clip.start_time,
            trim_start_seconds=source_start,
            trim_end_seconds=source_start + source_duration if source_duration > 0 else None,
            enabled=True,
            volume=1.0,
            transition="cut",
            fit_mode="fill",
        )

    def _convert_audio_clip(
        self,
        clip: TimelineClipV1,
        *,
        track: TimelineTrackV1,
        role: EditingAudioTrackRoleV2,
    ) -> EditingAudioEntryV2 | None:
        """Convert a voice/BGM/SFX timeline clip to an EditingAudioEntryV2."""
        if track.muted or not clip.asset_id:
            return None

        source_start = clip.source_start or 0.0
        source_duration = clip.source_duration or clip.duration

        return EditingAudioEntryV2(
            asset_id=clip.asset_id,
            role=role,
            enabled=True,
            timeline_start_seconds=clip.start_time,
            trim_start_seconds=source_start,
            trim_end_seconds=source_start + source_duration if source_duration > 0 else None,
            volume=min(1.0, max(0.0, _ROLE_BASE_VOLUME[role] * track.volume)),
            fade_in_seconds=clip.fade_in or 0.0,
            fade_out_seconds=clip.fade_out or 0.0,
        )

    def _calculate_total_duration(self, timeline: TimelineV1) -> float:
        """Calculate the total duration of the timeline."""
        if timeline.duration_seconds and timeline.duration_seconds > 0:
            return timeline.duration_seconds

        max_end = 0.0
        for track in timeline.tracks:
            for clip in track.clips:
                end = clip.start_time + (clip.duration or 0)
                max_end = max(max_end, end)

        return max_end if max_end > 0 else self._default_video_duration
