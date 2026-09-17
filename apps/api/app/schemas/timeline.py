"""Pydantic schemas for the Timeline orchestration layer (ADR 0007)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TimelineTrackTypeV1 = Literal["video", "voice", "bgm", "sfx", "camera", "subtitle"]
TimelineTransitionTypeV1 = Literal["fade", "dissolve", "wipe"]


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
    # Video transitions
    transition_in_type: TimelineTransitionTypeV1 | None = None
    transition_in_duration: float | None = Field(default=None, ge=0.0)
    transition_out_type: TimelineTransitionTypeV1 | None = None
    transition_out_duration: float | None = Field(default=None, ge=0.0)
    # Binding (voice clip → 3D character)
    bound_character_id: str | None = None
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
    transition_in_type: TimelineTransitionTypeV1 | None = None
    transition_in_duration: float | None = None
    transition_out_type: TimelineTransitionTypeV1 | None = None
    transition_out_duration: float | None = None
    bound_character_id: str | None = None
    label: str | None = None
    color: str | None = None


class TimelineClipUpdateV1(BaseModel):
    """Request to update a clip (partial patch)."""

    model_config = ConfigDict(extra="forbid")

    start_time: float | None = Field(default=None, ge=0.0)
    duration: float | None = Field(default=None, gt=0.0)
    source_start: float | None = Field(default=None, ge=0.0)
    source_duration: float | None = Field(default=None, gt=0.0)
    fade_in: float | None = None
    fade_out: float | None = None
    transition_in_type: TimelineTransitionTypeV1 | None = None
    transition_in_duration: float | None = None
    transition_out_type: TimelineTransitionTypeV1 | None = None
    transition_out_duration: float | None = None
    bound_character_id: str | None = None
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
    ducking: TimelineDuckingConfigV1 | None = None


class TimelineTrackUpdateV1(BaseModel):
    """Request to update a track (name / muted / volume / locked / display_order)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    muted: bool | None = None
    volume: float | None = Field(default=None, ge=0.0, le=1.0)
    locked: bool | None = None
    display_order: int | None = Field(default=None, ge=0)
