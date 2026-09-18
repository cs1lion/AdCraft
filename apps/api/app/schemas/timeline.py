"""Pydantic schemas for the Timeline orchestration layer (ADR 0007)."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


TimelineTrackTypeV1 = Literal["video", "voice", "bgm", "sfx", "camera", "subtitle"]
TimelineTransitionTypeV1 = Literal["fade", "dissolve", "wipe", "slide"]
TimelineSubtitlePositionV1 = Literal["bottom", "middle", "top"]

_SUBTITLE_COLOR_PATTERN = r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"

# A clip envelope may carry at most this many automation points.
_MAX_VOLUME_KEYFRAMES = 64


class TimelineVolumeKeyframeV1(BaseModel):
    """One point of a clip-relative volume automation envelope.

    ``time_seconds`` is measured from the start of the clip (not the source
    in-point); ``value`` is a linear gain of 0–1.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    time_seconds: float = Field(ge=0.0)
    value: float = Field(ge=0.0, le=1.0)


def _normalize_volume_keyframes(
    points: tuple[TimelineVolumeKeyframeV1, ...] | None,
) -> tuple[TimelineVolumeKeyframeV1, ...] | None:
    """Sort envelope points by time and reject duplicates/non-finite input."""
    if points is None:
        return None
    for point in points:
        if not math.isfinite(point.time_seconds) or not math.isfinite(point.value):
            raise ValueError("Volume keyframes must use finite numbers.")
    ordered = tuple(sorted(points, key=lambda point: point.time_seconds))
    previous_time: float | None = None
    for point in ordered:
        if previous_time is not None and abs(point.time_seconds - previous_time) < 1e-6:
            raise ValueError("Volume keyframe times must be unique.")
        previous_time = point.time_seconds
    if len(ordered) > _MAX_VOLUME_KEYFRAMES:
        raise ValueError(f"A volume envelope supports at most {_MAX_VOLUME_KEYFRAMES} points.")
    return ordered


# Explicit-null capable: None on PATCH clears the stored envelope.
VolumeKeyframesField = Annotated[
    tuple[TimelineVolumeKeyframeV1, ...] | None,
    AfterValidator(_normalize_volume_keyframes),
]

# Stored/hydrated clips always carry a (possibly empty) sorted tuple.
StoredVolumeKeyframesField = Annotated[
    tuple[TimelineVolumeKeyframeV1, ...],
    AfterValidator(_normalize_volume_keyframes),
]


class TimelineDuckingConfigV1(BaseModel):
    """User-tuned sidechain auto-ducking settings (BGM lowered while voice active).

    Mirrors EditingDuckingConfigV2 ranges; ``None`` on the timeline means
    "auto": the export adapter applies defaults whenever both voice and BGM
    clips are present.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    threshold_db: float = Field(default=-30.0, ge=-80.0, le=-10.0)
    ratio: float = Field(default=12.0, gt=1.0, le=60.0)
    attack_ms: int = Field(default=50, ge=0, le=2000)
    release_ms: int = Field(default=250, ge=0, le=5000)
    makeup_gain_db: float = Field(default=0.0, ge=0.0, le=24.0)


class TimelineSubtitleStyleV1(BaseModel):
    """Per-cue subtitle styling; every field left as None falls back to the
    renderer default when SRT/ASS is generated or the cue is burned in."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    font_family: str | None = Field(default=None, min_length=1, max_length=80)
    font_size: int | None = Field(default=None, ge=8, le=160)
    primary_color: str | None = Field(
        default=None, pattern=_SUBTITLE_COLOR_PATTERN
    )
    outline_color: str | None = Field(
        default=None, pattern=_SUBTITLE_COLOR_PATTERN
    )
    position: TimelineSubtitlePositionV1 | None = None
    bold: bool | None = None
    italic: bool | None = None


class TimelineTrackV1(BaseModel):
    """One track within a Timeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    track_id: str = Field(min_length=1)
    timeline_id: str = Field(min_length=1)
    type: TimelineTrackTypeV1
    name: str = Field(min_length=1, max_length=120)
    muted: bool = False
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    locked: bool = False
    display_order: int = Field(default=0, ge=0)
    clips: tuple["TimelineClipV1", ...] = Field(default_factory=tuple)
    created_at: str
    updated_at: str


class TimelineClipV1(BaseModel):
    """One clip on a Timeline track — references an asset produced by a canvas node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    clip_id: str = Field(min_length=1)
    track_id: str = Field(min_length=1)
    asset_id: str | None = Field(default=None)
    asset_version_id: str | None = Field(default=None)
    source_node_id: str | None = Field(default=None)
    # Timeline position (seconds)
    start_time: float = Field(default=0.0, ge=0.0)
    duration: float = Field(gt=0.0)
    # Source clipping (in/out points within the asset)
    source_start: float = Field(default=0.0, ge=0.0)
    source_duration: float | None = Field(default=None, gt=0.0)
    # Audio fades
    fade_in: float | None = Field(default=None, ge=0.0)
    fade_out: float | None = Field(default=None, ge=0.0)
    # Clip-relative volume automation envelope (audio clips); empty = flat.
    volume_keyframes: StoredVolumeKeyframesField = Field(default_factory=tuple)
    # Video transitions
    transition_in_type: TimelineTransitionTypeV1 | None = None
    transition_in_duration: float | None = Field(default=None, ge=0.0)
    transition_out_type: TimelineTransitionTypeV1 | None = None
    transition_out_duration: float | None = Field(default=None, ge=0.0)
    # Binding (voice clip → 3D character)
    bound_character_id: str | None = None
    # Subtitle cue content (subtitle-track clips)
    subtitle_text: str | None = Field(default=None, max_length=4000)
    subtitle_style: TimelineSubtitleStyleV1 | None = None
    # Display metadata
    label: str | None = Field(default=None, max_length=200)
    color: str | None = None
    created_at: str
    updated_at: str


class TimelineV1(BaseModel):
    """One Timeline for a Workflow — the orchestration layer above nodes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeline_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    fps: int = Field(default=30, gt=0)
    # None = auto-ducking with renderer defaults; explicit config = user override.
    ducking: TimelineDuckingConfigV1 | None = None
    # Burn subtitle cues into the exported video instead of shipping them only
    # as a sidecar SRT/ASS file.
    subtitle_burn_in: bool = True
    tracks: tuple[TimelineTrackV1, ...] = Field(default_factory=tuple)
    created_at: str
    updated_at: str


# --- Create / Update request schemas ---


class TimelineClipCreateV1(BaseModel):
    """Request to manually add a clip to a track."""

    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(min_length=1)
    asset_id: str | None = None
    asset_version_id: str | None = None
    source_node_id: str | None = None
    start_time: float = Field(default=0.0, ge=0.0)
    duration: float = Field(gt=0.0)
    source_start: float = Field(default=0.0, ge=0.0)
    source_duration: float | None = Field(default=None, gt=0.0)
    fade_in: float | None = None
    fade_out: float | None = None
    volume_keyframes: VolumeKeyframesField = None
    transition_in_type: TimelineTransitionTypeV1 | None = None
    transition_in_duration: float | None = None
    transition_out_type: TimelineTransitionTypeV1 | None = None
    transition_out_duration: float | None = None
    bound_character_id: str | None = None
    subtitle_text: str | None = Field(default=None, max_length=4000)
    subtitle_style: TimelineSubtitleStyleV1 | None = None
    label: str | None = None
    color: str | None = None


class TimelineClipUpdateV1(BaseModel):
    """Request to update a clip (partial patch)."""

    model_config = ConfigDict(extra="forbid")

    start_time: float | None = Field(default=None, ge=0.0)
    duration: float | None = Field(default=None, gt=0.0)
    source_start: float | None = Field(default=None, ge=0.0)
    # Re-linking a manual/orphan clip to a canvas node follows explicit-null
    # semantics like the other nullable fields: omitted leaves it untouched,
    # an explicit JSON null unlinks the clip from its node.
    source_node_id: str | None = Field(default=None, min_length=1)
    source_duration: float | None = Field(default=None, gt=0.0)
    fade_in: float | None = None
    fade_out: float | None = None
    volume_keyframes: VolumeKeyframesField = None
    transition_in_type: TimelineTransitionTypeV1 | None = None
    transition_in_duration: float | None = None
    transition_out_type: TimelineTransitionTypeV1 | None = None
    transition_out_duration: float | None = None
    bound_character_id: str | None = None
    subtitle_text: str | None = Field(default=None, max_length=4000)
    # Explicit-null clears the stored style; omission leaves it untouched
    # (handled via model_fields_set in the endpoint).
    subtitle_style: TimelineSubtitleStyleV1 | None = None
    label: str | None = None
    color: str | None = None
    muted: bool | None = None  # for track-level, but kept here for convenience


class TimelineClipMoveV1(BaseModel):
    """Request to move a clip to a new track and/or start time."""

    model_config = ConfigDict(extra="forbid")

    track_id: str | None = Field(default=None, min_length=1)
    start_time: float = Field(ge=0.0)


class TimelineUpdateV1(BaseModel):
    """Request to update timeline metadata (duration / fps / ducking).

    ``ducking`` follows explicit-null semantics: omitted leaves the stored
    value untouched; an explicit JSON ``null`` resets it to auto-defaults.
    """

    model_config = ConfigDict(extra="forbid")

    duration_seconds: float | None = Field(default=None, ge=0.0)
    fps: int | None = Field(default=None, gt=0)
    subtitle_burn_in: bool | None = None
    ducking: TimelineDuckingConfigV1 | None = None


class TimelineTrackUpdateV1(BaseModel):
    """Request to update a track (name / muted / volume / locked / display_order)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    muted: bool | None = None
    volume: float | None = Field(default=None, ge=0.0, le=1.0)
    locked: bool | None = None
    display_order: int | None = Field(default=None, ge=0)


class TimelineBeatAnalysisV1(BaseModel):
    """Result of BGM beat detection (Phase 4.4).

    ``beats`` are asset-relative onset times in seconds (from the start of
    the underlying media, not clip-relative); callers map them onto the
    timeline via ``clip.start_time + (beat - clip.source_start)``.
    ``confidence`` is a 0–1 salience score for the estimated tempo.
    """

    model_config = ConfigDict(frozen=True)

    bpm: float = Field(gt=0.0)
    beats: tuple[float, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
