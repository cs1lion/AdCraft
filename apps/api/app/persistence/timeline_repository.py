"""Repository for Timeline persistence (ADR 0007).

Handles CRUD for timelines, tracks, and clips, plus auto-creation
of default timelines with 6 standard tracks.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import (
    TimelineClipRow,
    TimelineRow,
    TimelineTrackRow,
)
from app.schemas.timeline import (
    TimelineClipV1,
    TimelineDuckingConfigV1,
    TimelineTrackV1,
    TimelineV1,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# Sentinel distinguishing "field omitted from PATCH" from an explicit null.
_UNSET: object = object()

logger = logging.getLogger(__name__)


def _parse_ducking(raw: str | None) -> TimelineDuckingConfigV1 | None:
    """Deserialize the stored ducking blob; fail open to auto-defaults."""
    if not raw:
        return None
    try:
        return TimelineDuckingConfigV1.model_validate(json.loads(raw))
    except (ValueError, TypeError):
        logger.warning("Corrupt timeline ducking settings blob, falling back to auto: %s", raw)
        return None


# Default track definitions for a new timeline
_DEFAULT_TRACKS: Sequence[tuple[str, str, int]] = (
    ("video", "Video", 0),
    ("voice", "Voice", 1),
    ("bgm", "BGM", 2),
    ("sfx", "SFX", 3),
    ("camera", "Camera", 4),
    ("subtitle", "Subtitles", 5),
)


class TimelineRepository:
    """Persistence operations for Timelines, Tracks, and Clips."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- Timeline ---

    def get_by_workflow_id(self, workflow_id: str) -> TimelineV1:
        """Get a timeline by workflow_id, creating one with default tracks if missing."""
        row = self._session.execute(
            select(TimelineRow).where(TimelineRow.workflow_id == workflow_id)
        ).scalar_one_or_none()

        if row is None:
            row = self._create_default_timeline(workflow_id)

        return self._hydrate_timeline(row)

    def get_by_id(self, timeline_id: str) -> TimelineV1:
        row = self._session.execute(
            select(TimelineRow).where(TimelineRow.timeline_id == timeline_id)
        ).scalar_one()
        return self._hydrate_timeline(row)

    def update_timeline(
        self,
        timeline_id: str,
        *,
        duration_seconds: float | None = None,
        fps: int | None = None,
        ducking: TimelineDuckingConfigV1 | None | object = _UNSET,
    ) -> TimelineV1:
        row = self._session.execute(
            select(TimelineRow).where(TimelineRow.timeline_id == timeline_id)
        ).scalar_one()

        if duration_seconds is not None:
            row.duration_seconds = duration_seconds
        if fps is not None:
            row.fps = fps
        if ducking is not _UNSET:
            row.ducking_json = (
                json.dumps(ducking.model_dump(mode="json"))
                if ducking is not None
                else None
            )
        row.updated_at = _utc_now_iso()
        self._session.flush()
        return self._hydrate_timeline(row)

    # --- Tracks ---

    def get_tracks(self, timeline_id: str) -> list[TimelineTrackV1]:
        rows = self._session.execute(
            select(TimelineTrackRow)
            .where(TimelineTrackRow.timeline_id == timeline_id)
            .order_by(TimelineTrackRow.display_order)
        ).scalars().all()
        return [self._hydrate_track(row) for row in rows]

    def update_track(
        self,
        track_id: str,
        *,
        name: str | None = None,
        muted: bool | None = None,
        volume: float | None = None,
        locked: bool | None = None,
        display_order: int | None = None,
    ) -> TimelineTrackV1:
        row = self._session.execute(
            select(TimelineTrackRow).where(TimelineTrackRow.track_id == track_id)
        ).scalar_one()

        if name is not None:
            row.name = name
        if muted is not None:
            row.muted = muted
        if volume is not None:
            row.volume = volume
        if locked is not None:
            row.locked = locked
        if display_order is not None:
            row.display_order = display_order
        row.updated_at = _utc_now_iso()
        self._session.flush()
        return self._hydrate_track(row)

    # --- Clips ---

    def add_clip(
        self,
        *,
        track_id: str,
        start_time: float,
        duration: float,
        asset_id: str | None = None,
        asset_version_id: str | None = None,
        source_node_id: str | None = None,
        source_start: float = 0.0,
        source_duration: float | None = None,
        fade_in: float | None = None,
        fade_out: float | None = None,
        label: str | None = None,
        color: str | None = None,
    ) -> TimelineClipV1:
        now = _utc_now_iso()
        row = TimelineClipRow(
            clip_id=_new_id("clip"),
            track_id=track_id,
            asset_id=asset_id,
            asset_version_id=asset_version_id,
            source_node_id=source_node_id,
            start_time=start_time,
            duration=duration,
            source_start=source_start,
            source_duration=source_duration,
            fade_in=fade_in,
            fade_out=fade_out,
            label=label,
            color=color,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        self._session.flush()

        # Auto-update timeline duration_seconds to max clip end time
        track_row = self._session.execute(
            select(TimelineTrackRow).where(TimelineTrackRow.track_id == track_id)
        ).scalar_one_or_none()
        if track_row:
            all_clips = self._session.execute(
                select(TimelineClipRow)
                .join(TimelineTrackRow, TimelineClipRow.track_id == TimelineTrackRow.track_id)
                .where(TimelineTrackRow.timeline_id == track_row.timeline_id)
            ).scalars().all()
            if all_clips:
                max_end = max(c.start_time + c.duration for c in all_clips)
                timeline_row = self._session.execute(
                    select(TimelineRow).where(TimelineRow.timeline_id == track_row.timeline_id)
                ).scalar_one_or_none()
                if timeline_row and max_end > timeline_row.duration_seconds:
                    timeline_row.duration_seconds = max_end
                    timeline_row.updated_at = _utc_now_iso()

        return self._hydrate_clip(row)

    def get_clip(self, clip_id: str) -> TimelineClipV1:
        row = self._session.execute(
            select(TimelineClipRow).where(TimelineClipRow.clip_id == clip_id)
        ).scalar_one()
        return self._hydrate_clip(row)

    def get_clips_for_track(self, track_id: str) -> list[TimelineClipV1]:
        rows = self._session.execute(
            select(TimelineClipRow)
            .where(TimelineClipRow.track_id == track_id)
            .order_by(TimelineClipRow.start_time)
        ).scalars().all()
        return [self._hydrate_clip(row) for row in rows]

    def get_clips_for_node(self, source_node_id: str) -> list[TimelineClipV1]:
        rows = self._session.execute(
            select(TimelineClipRow)
            .where(TimelineClipRow.source_node_id == source_node_id)
            .order_by(TimelineClipRow.start_time)
        ).scalars().all()
        return [self._hydrate_clip(row) for row in rows]

    def update_clip(
        self,
        clip_id: str,
        *,
        start_time: float | None = None,
        duration: float | None = None,
        source_start: float | None = None,
        source_duration: float | None | object = _UNSET,
        fade_in: float | None | object = _UNSET,
        fade_out: float | None | object = _UNSET,
        transition_in_type: str | None | object = _UNSET,
        transition_in_duration: float | None | object = _UNSET,
        transition_out_type: str | None | object = _UNSET,
        transition_out_duration: float | None | object = _UNSET,
        bound_character_id: str | None | object = _UNSET,
        label: str | None | object = _UNSET,
        color: str | None | object = _UNSET,
    ) -> TimelineClipV1:
        row = self._session.execute(
            select(TimelineClipRow).where(TimelineClipRow.clip_id == clip_id)
        ).scalar_one()

        if start_time is not None:
            row.start_time = start_time
        if duration is not None:
            row.duration = duration
        if source_start is not None:
            row.source_start = source_start
        # Nullable fields use the _UNSET sentinel: omitted leaves the stored
        # value untouched, while an explicit None clears the column.
        if source_duration is not _UNSET:
            row.source_duration = source_duration
        if fade_in is not _UNSET:
            row.fade_in = fade_in
        if fade_out is not _UNSET:
            row.fade_out = fade_out
        if transition_in_type is not _UNSET:
            row.transition_in_type = transition_in_type
        if transition_in_duration is not _UNSET:
            row.transition_in_duration = transition_in_duration
        if transition_out_type is not _UNSET:
            row.transition_out_type = transition_out_type
        if transition_out_duration is not _UNSET:
            row.transition_out_duration = transition_out_duration
        if bound_character_id is not _UNSET:
            row.bound_character_id = bound_character_id
        if label is not _UNSET:
            row.label = label
        if color is not _UNSET:
            row.color = color
        row.updated_at = _utc_now_iso()
        self._session.flush()
        return self._hydrate_clip(row)

    def move_clip(
        self,
        clip_id: str,
        *,
        new_track_id: str | None = None,
        new_start_time: float,
    ) -> TimelineClipV1:
        row = self._session.execute(
            select(TimelineClipRow).where(TimelineClipRow.clip_id == clip_id)
        ).scalar_one()

        if new_track_id is not None:
            row.track_id = new_track_id
        row.start_time = new_start_time
        row.updated_at = _utc_now_iso()
        self._session.flush()
        return self._hydrate_clip(row)

    def delete_clip(self, clip_id: str) -> None:
        row = self._session.execute(
            select(TimelineClipRow).where(TimelineClipRow.clip_id == clip_id)
        ).scalar_one()
        self._session.delete(row)
        self._session.flush()

    def get_next_start_time_for_track(self, track_id: str) -> float:
        """Get the start time for appending a new clip after the last one."""
        rows = self._session.execute(
            select(TimelineClipRow)
            .where(TimelineClipRow.track_id == track_id)
            .order_by(TimelineClipRow.start_time.desc())
        ).scalars().first()
        if rows is None:
            return 0.0
        return rows.start_time + rows.duration

    # --- Internal ---

    def _create_default_timeline(self, workflow_id: str) -> TimelineRow:
        now = _utc_now_iso()
        timeline_id = _new_id("timeline")
        timeline = TimelineRow(
            timeline_id=timeline_id,
            workflow_id=workflow_id,
            duration_seconds=0.0,
            fps=30,
            created_at=now,
            updated_at=now,
        )
        self._session.add(timeline)

        for track_type, track_name, order in _DEFAULT_TRACKS:
            track = TimelineTrackRow(
                track_id=_new_id("track"),
                timeline_id=timeline_id,
                type=track_type,
                name=track_name,
                muted=False,
                volume=1.0,
                locked=False,
                display_order=order,
                created_at=now,
                updated_at=now,
            )
            self._session.add(track)

        self._session.flush()
        return timeline

    def _hydrate_timeline(self, row: TimelineRow) -> TimelineV1:
        tracks = self.get_tracks(row.timeline_id)
        return TimelineV1(
            timeline_id=row.timeline_id,
            workflow_id=row.workflow_id,
            duration_seconds=row.duration_seconds,
            fps=row.fps,
            ducking=_parse_ducking(row.ducking_json),
            tracks=tuple(tracks),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _hydrate_track(self, row: TimelineTrackRow) -> TimelineTrackV1:
        clips = self.get_clips_for_track(row.track_id)
        return TimelineTrackV1(
            track_id=row.track_id,
            timeline_id=row.timeline_id,
            type=row.type,
            name=row.name,
            muted=row.muted,
            volume=row.volume,
            locked=row.locked,
            display_order=row.display_order,
            clips=tuple(clips),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _hydrate_clip(self, row: TimelineClipRow) -> TimelineClipV1:
        return TimelineClipV1(
            clip_id=row.clip_id,
            track_id=row.track_id,
            asset_id=row.asset_id,
            asset_version_id=row.asset_version_id,
            source_node_id=row.source_node_id,
            start_time=row.start_time,
            duration=row.duration,
            source_start=row.source_start,
            source_duration=row.source_duration,
            fade_in=row.fade_in,
            fade_out=row.fade_out,
            transition_in_type=row.transition_in_type,
            transition_in_duration=row.transition_in_duration,
            transition_out_type=row.transition_out_type,
            transition_out_duration=row.transition_out_duration,
            bound_character_id=row.bound_character_id,
            label=row.label,
            color=row.color,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
