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

# Clips whose boundaries differ by more than this (seconds) are treated as
# separated by a gap, so a cross-dissolve cannot join them.
_TRANSITION_ADJACENCY_EPSILON = 0.02
# A dissolve may never consume more than half of either clip.
_TRANSITION_MAX_CLIP_FRACTION = 0.5


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
                previous_clip = sorted_clips[index - 1] if index > 0 else None
                next_clip = (
                    sorted_clips[index + 1]
                    if index + 1 < len(sorted_clips)
                    else None
                )
                entry, entry_warnings = self._convert_video_clip(
                    clip,
                    index=index,
                    editing_node_id=editing_node_id,
                    previous_clip=previous_clip,
                    next_clip=next_clip,
                )
                if entry is not None:
                    video_entries.append(entry)
                    warnings.extend(entry_warnings)
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
        previous_clip: TimelineClipV1 | None,
        next_clip: TimelineClipV1 | None,
    ) -> tuple[EditingVideoEntryV2 | None, tuple[str, ...]]:
        """Convert a timeline video clip to an EditingVideoEntryV2.

        Returns the entry (or ``None`` when the clip has no asset) plus
        warnings for transitions that could not be honoured.
        """
        if not clip.asset_id:
            return None, ()

        # Determine duration: use clip duration, fall back to default
        duration = clip.duration or self._default_video_duration

        # Determine source trimming
        source_start = clip.source_start or 0.0
        source_duration = clip.source_duration or duration

        transition, transition_duration, warnings = self._resolve_transition(
            clip,
            duration=duration,
            previous_clip=previous_clip,
            next_clip=next_clip,
        )

        entry = EditingVideoEntryV2(
            asset_id=clip.asset_id,
            timeline_start_seconds=clip.start_time,
            trim_start_seconds=source_start,
            trim_end_seconds=source_start + source_duration if source_duration > 0 else None,
            enabled=True,
            volume=1.0,
            transition=transition,
            transition_duration_seconds=transition_duration,
            fit_mode="fill",
        )
        return entry, tuple(warnings)

    def _resolve_transition(
        self,
        clip: TimelineClipV1,
        *,
        duration: float,
        previous_clip: TimelineClipV1 | None,
        next_clip: TimelineClipV1 | None,
    ) -> tuple[str, float, list[str]]:
        """Resolve the render transition for a clip's incoming/outgoing edges.

        A cross-dissolve is carried by the *incoming* clip entry and only
        applies when the two clips are back-to-back; its duration is the
        shortest of the two configured edges, capped to half of either clip.
        """
        warnings: list[str] = []

        # --- Incoming boundary -------------------------------------------------
        transition = "cut"
        transition_duration = 0.0
        incoming_request = clip.transition_in_type
        if previous_clip is not None and (
            incoming_request == "dissolve"
            or previous_clip.transition_out_type == "dissolve"
        ):
            if self._clips_are_adjacent(previous_clip, clip):
                candidates = [
                    value
                    for value, owner_type in (
                        (clip.transition_in_duration, incoming_request),
                        (
                            previous_clip.transition_out_duration,
                            previous_clip.transition_out_type,
                        ),
                    )
                    if owner_type == "dissolve" and value and value > 0
                ]
                if not candidates:
                    warnings.append(
                        f"Video clip {clip.clip_id} requests a cross-dissolve "
                        "without a duration; rendered as a cut."
                    )
                else:
                    requested = min(candidates)
                    clamped = min(
                        requested,
                        _TRANSITION_MAX_CLIP_FRACTION * duration,
                        _TRANSITION_MAX_CLIP_FRACTION
                        * (previous_clip.duration or self._default_video_duration),
                    )
                    if clamped < requested - 1e-6:
                        warnings.append(
                            f"Cross-dissolve into clip {clip.clip_id} shortened "
                            f"from {requested:.3f}s to {clamped:.3f}s to fit the clips."
                        )
                    transition = "dissolve"
                    transition_duration = clamped
            else:
                warnings.append(
                    f"Video clip {clip.clip_id} requests a cross-dissolve but is "
                    "separated from the previous clip by a gap; rendered as a cut."
                )
        elif incoming_request is not None:
            # Fade-from-black and wipe-in are not produced by the renderer yet.
            warnings.append(
                f"Video clip {clip.clip_id} transition-in '{incoming_request}' "
                "is not supported on this boundary; rendered as a cut."
            )

        # --- Outgoing boundary -------------------------------------------------
        # The dissolve itself is attached to the incoming clip; here we only
        # flag an outgoing dissolve that can never meet a successor.
        outgoing = clip.transition_out_type
        if transition == "cut" and outgoing == "fade":
            superseded = (
                next_clip is not None
                and self._clips_are_adjacent(clip, next_clip)
                and next_clip.transition_in_type == "dissolve"
            )
            if not superseded and clip.transition_out_duration and clip.transition_out_duration > 0:
                transition = "fade"
                transition_duration = clip.transition_out_duration
        if outgoing == "dissolve" and (
            next_clip is None or not self._clips_are_adjacent(clip, next_clip)
        ):
            warnings.append(
                f"Video clip {clip.clip_id} requests an outgoing cross-dissolve "
                "but has no adjacent following clip; rendered as a cut."
            )
        if outgoing == "wipe":
            warnings.append(
                f"Video clip {clip.clip_id} outgoing 'wipe' transition is not "
                "supported by the renderer; rendered as a cut."
            )

        return transition, transition_duration, warnings

    @staticmethod
    def _clips_are_adjacent(previous: TimelineClipV1, current: TimelineClipV1) -> bool:
        return abs(
            current.start_time - (previous.start_time + previous.duration)
        ) <= _TRANSITION_ADJACENCY_EPSILON

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
