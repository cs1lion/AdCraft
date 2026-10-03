"""Repository for Timeline persistence (ADR 0007).

Handles CRUD for timelines, tracks, and clips, plus auto-creation
of default timelines with 6 standard tracks.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.errors import V2PersistenceError
from app.persistence.models import (
    TimelineClipRow,
    TimelineRow,
    TimelineTrackRow,
)
from app.schemas.timeline import (
    TimelineClipV1,
    TimelineDuckingConfigV1,
    TimelineSubtitleStyleV1,
    TimelineTrackV1,
    TimelineV1,
    TimelineVolumeKeyframeV1,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class NodeSubtitleCue:
    """One timed subtitle line sourced from a text/script node output asset."""

    start_seconds: float
    end_seconds: float
    text: str


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


def _parse_subtitle_style(raw: str | None) -> TimelineSubtitleStyleV1 | None:
    """Deserialize a stored per-cue subtitle style blob; fail open to None."""
    if not raw:
        return None
    try:
        return TimelineSubtitleStyleV1.model_validate(json.loads(raw))
    except (ValueError, TypeError):
        logger.warning("Corrupt subtitle style blob, ignoring style: %s", raw)
        return None


def _dump_volume_keyframes(
    keyframes: Sequence[TimelineVolumeKeyframeV1] | None,
) -> str | None:
    if not keyframes:
        return None
    return json.dumps(
        [
            {"time_seconds": point.time_seconds, "value": point.value}
            for point in keyframes
        ]
    )


def _parse_volume_keyframes(raw: str | None) -> tuple[TimelineVolumeKeyframeV1, ...]:
    """Deserialize a stored envelope blob; fail open to a flat clip."""
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
        points = tuple(TimelineVolumeKeyframeV1.model_validate(item) for item in payload)
        return tuple(sorted(points, key=lambda point: point.time_seconds))
    except (ValueError, TypeError):
        logger.warning("Corrupt volume keyframe blob, ignoring envelope: %s", raw)
        return ()


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
        subtitle_burn_in: bool | None = None,
        ducking: TimelineDuckingConfigV1 | None | object = _UNSET,
    ) -> TimelineV1:
        row = self._session.execute(
            select(TimelineRow).where(TimelineRow.timeline_id == timeline_id)
        ).scalar_one()

        if duration_seconds is not None:
            row.duration_seconds = duration_seconds
        if fps is not None:
            row.fps = fps
        if subtitle_burn_in is not None:
            row.subtitle_burn_in = subtitle_burn_in
        if ducking is not _UNSET:
            row.ducking_json = (
                json.dumps(ducking.model_dump(mode="json"))
                if ducking is not None
                else None
            )
        row.updated_at = _utc_now_iso()
        self._session.flush()
        return self._hydrate_timeline(row)

    def _begin_scoped_write(self, workflow_id: str | None) -> None:
        """Keep ownership lookup and mutation in the same write transaction.

        SQLite's legacy driver does not BEGIN for SELECT and ignores FOR UPDATE.
        Reserve its writer before checking scope; other databases lock joined rows.
        Never commit here: the caller owns commit/rollback.
        """
        if workflow_id is None:
            return
        connection = self._session.connection()
        if connection.dialect.name == "sqlite":
            driver = connection.connection.driver_connection
            if not driver.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")

    def _track_for_write(
        self, track_id: str, workflow_id: str | None = None,
    ) -> TimelineTrackRow:
        query = select(TimelineTrackRow).where(TimelineTrackRow.track_id == track_id)
        if workflow_id is not None:
            query = query.join(TimelineRow).where(TimelineRow.workflow_id == workflow_id)
        row = self._session.execute(query.with_for_update()).scalar_one_or_none()
        if row is None:
            raise V2PersistenceError(
                "timeline_track_not_found", "Track was not found on this workflow.",
                stage="timeline_write",
            )
        return row

    def _clip_for_write(
        self, clip_id: str, workflow_id: str | None = None,
    ) -> TimelineClipRow:
        query = select(TimelineClipRow).where(TimelineClipRow.clip_id == clip_id)
        if workflow_id is not None:
            query = query.join(TimelineTrackRow).join(TimelineRow).where(
                TimelineRow.workflow_id == workflow_id,
            )
        row = self._session.execute(query.with_for_update()).scalar_one_or_none()
        if row is None:
            raise V2PersistenceError(
                "timeline_clip_not_found", "Clip was not found on this workflow.",
                stage="timeline_write",
            )
        return row

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
        workflow_id: str | None = None,
    ) -> TimelineTrackV1:
        self._begin_scoped_write(workflow_id)
        row = self._track_for_write(track_id, workflow_id)

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
        volume_keyframes: Sequence[TimelineVolumeKeyframeV1] | None = None,
        label: str | None = None,
        color: str | None = None,
        subtitle_text: str | None = None,
        subtitle_style: TimelineSubtitleStyleV1 | None = None,
        workflow_id: str | None = None,
    ) -> TimelineClipV1:
        self._begin_scoped_write(workflow_id)
        if workflow_id is not None:
            self._track_for_write(track_id, workflow_id)
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
            volume_keyframes_json=_dump_volume_keyframes(volume_keyframes),
            label=label,
            color=color,
            subtitle_text=subtitle_text,
            subtitle_style_json=(
                json.dumps(subtitle_style.model_dump(mode="json"))
                if subtitle_style is not None
                else None
            ),
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
            self._grow_timeline_duration(track_row.timeline_id)

        return self._hydrate_clip(row)

    def _grow_timeline_duration(self, timeline_id: str) -> None:
        """Extend ``duration_seconds`` to the latest clip end (never shrink)."""
        all_clips = self._session.execute(
            select(TimelineClipRow)
            .join(TimelineTrackRow, TimelineClipRow.track_id == TimelineTrackRow.track_id)
            .where(TimelineTrackRow.timeline_id == timeline_id)
        ).scalars().all()
        if not all_clips:
            return
        max_end = max(c.start_time + c.duration for c in all_clips)
        timeline_row = self._session.execute(
            select(TimelineRow).where(TimelineRow.timeline_id == timeline_id)
        ).scalar_one_or_none()
        if timeline_row is not None and max_end > timeline_row.duration_seconds:
            timeline_row.duration_seconds = max_end
            timeline_row.updated_at = _utc_now_iso()

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

    def get_latest_node_clip(
        self,
        timeline_id: str,
        source_node_id: str,
    ) -> TimelineClipV1 | None:
        """Return the most recently updated clip originating from one node.

        Scoped to one timeline (joined through the clip's track) so a node
        rerun can never touch clips belonging to another timeline.
        """
        row = self._session.execute(
            select(TimelineClipRow)
            .join(TimelineTrackRow, TimelineClipRow.track_id == TimelineTrackRow.track_id)
            .where(
                TimelineTrackRow.timeline_id == timeline_id,
                TimelineClipRow.source_node_id == source_node_id,
            )
            .order_by(TimelineClipRow.updated_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return self._hydrate_clip(row) if row is not None else None

    def upsert_auto_clip_for_node(
        self,
        *,
        timeline_id: str,
        source_node_id: str,
        track_id: str,
        duration: float,
        asset_id: str | None,
        asset_version_id: str | None,
        label: str | None,
    ) -> tuple[TimelineClipV1, bool]:
        """Idempotently place a node's media on the timeline.

        A node rerun refreshes the existing clip in place (asset pointers and
        duration only); the user's arrangement — start time, trim, fades,
        label — is preserved. New nodes append after the track's last clip.
        Returns ``(clip, created)``.
        """
        existing = self._session.execute(
            select(TimelineClipRow)
            .join(TimelineTrackRow, TimelineClipRow.track_id == TimelineTrackRow.track_id)
            .where(
                TimelineTrackRow.timeline_id == timeline_id,
                TimelineClipRow.source_node_id == source_node_id,
            )
            .order_by(TimelineClipRow.updated_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            existing.track_id = track_id
            existing.asset_id = asset_id
            existing.asset_version_id = asset_version_id
            existing.duration = duration
            existing.updated_at = _utc_now_iso()
            self._session.flush()
            self._grow_timeline_duration(timeline_id)
            return self._hydrate_clip(existing), False

        created = self.add_clip(
            track_id=track_id,
            start_time=self.get_next_start_time_for_track(track_id),
            duration=duration,
            asset_id=asset_id,
            asset_version_id=asset_version_id,
            source_node_id=source_node_id,
            label=label,
        )
        return created, True

    def sync_node_subtitle_clips(
        self,
        *,
        timeline_id: str,
        source_node_id: str,
        track_id: str,
        cues: Sequence[NodeSubtitleCue],
        asset_id: str | None,
        asset_version_id: str | None,
        label: str,
    ) -> tuple[TimelineClipV1, ...]:
        """Reconcile a node's subtitle cues onto its track (ordinal matching).

        The node owns all clips carrying its ``source_node_id`` on this track;
        manual clips (no source node) are never touched. Existing clips match
        cues by order (sorted start time): matched clips refresh text, timing
        and asset pointers while preserving the user's label and subtitle
        style; extra cues are appended; surplus clips are deleted.
        """
        rows = list(
            self._session.execute(
                select(TimelineClipRow)
                .join(TimelineTrackRow, TimelineClipRow.track_id == TimelineTrackRow.track_id)
                .where(
                    TimelineTrackRow.timeline_id == timeline_id,
                    TimelineClipRow.track_id == track_id,
                    TimelineClipRow.source_node_id == source_node_id,
                )
                .order_by(TimelineClipRow.start_time, TimelineClipRow.clip_id)
            ).scalars()
        )
        ordered_cues = sorted(cues, key=lambda cue: cue.start_seconds)
        shared = min(len(rows), len(ordered_cues))
        now = _utc_now_iso()

        for index in range(shared):
            row = rows[index]
            cue = ordered_cues[index]
            row.asset_id = asset_id
            row.asset_version_id = asset_version_id
            row.start_time = max(cue.start_seconds, 0.0)
            row.duration = max(cue.end_seconds - cue.start_seconds, 0.001)
            row.subtitle_text = cue.text
            row.updated_at = now

        for offset, cue in enumerate(ordered_cues[shared:], start=1):
            self.add_clip(
                track_id=track_id,
                start_time=max(cue.start_seconds, 0.0),
                duration=max(cue.end_seconds - cue.start_seconds, 0.001),
                asset_id=asset_id,
                asset_version_id=asset_version_id,
                source_node_id=source_node_id,
                subtitle_text=cue.text,
                label=f"{label} {shared + offset}",
            )

        for row in rows[shared:]:
            self._session.delete(row)

        self._session.flush()
        self._grow_timeline_duration(timeline_id)
        final_rows = list(
            self._session.execute(
                select(TimelineClipRow)
                .join(TimelineTrackRow, TimelineClipRow.track_id == TimelineTrackRow.track_id)
                .where(
                    TimelineTrackRow.timeline_id == timeline_id,
                    TimelineClipRow.track_id == track_id,
                    TimelineClipRow.source_node_id == source_node_id,
                )
                .order_by(TimelineClipRow.start_time, TimelineClipRow.clip_id)
            ).scalars()
        )
        return tuple(self._hydrate_clip(row) for row in final_rows)

    def update_clip(
        self,
        clip_id: str,
        *,
        start_time: float | None = None,
        duration: float | None = None,
        source_start: float | None = None,
        asset_id: str | None | object = _UNSET,
        asset_version_id: str | None | object = _UNSET,
        source_node_id: str | None | object = _UNSET,
        source_duration: float | None | object = _UNSET,
        fade_in: float | None | object = _UNSET,
        fade_out: float | None | object = _UNSET,
        volume_keyframes: Sequence[TimelineVolumeKeyframeV1] | None | object = _UNSET,
        transition_in_type: str | None | object = _UNSET,
        transition_in_duration: float | None | object = _UNSET,
        transition_out_type: str | None | object = _UNSET,
        transition_out_duration: float | None | object = _UNSET,
        bound_character_id: str | None | object = _UNSET,
        label: str | None | object = _UNSET,
        color: str | None | object = _UNSET,
        subtitle_text: str | None | object = _UNSET,
        subtitle_style: TimelineSubtitleStyleV1 | None | object = _UNSET,
        workflow_id: str | None = None,
    ) -> TimelineClipV1:
        self._begin_scoped_write(workflow_id)
        row = self._clip_for_write(clip_id, workflow_id)

        if start_time is not None:
            row.start_time = start_time
        if duration is not None:
            row.duration = duration
        if source_start is not None:
            row.source_start = source_start
        # Nullable fields use the _UNSET sentinel: omitted leaves the stored
        # value untouched, while an explicit None clears the column.
        if asset_id is not _UNSET:
            row.asset_id = asset_id
        if asset_version_id is not _UNSET:
            row.asset_version_id = asset_version_id
        if source_node_id is not _UNSET:
            row.source_node_id = source_node_id
        if source_duration is not _UNSET:
            row.source_duration = source_duration
        if fade_in is not _UNSET:
            row.fade_in = fade_in
        if fade_out is not _UNSET:
            row.fade_out = fade_out
        if volume_keyframes is not _UNSET:
            row.volume_keyframes_json = _dump_volume_keyframes(volume_keyframes)
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
        if subtitle_text is not _UNSET:
            row.subtitle_text = subtitle_text
        if subtitle_style is not _UNSET:
            row.subtitle_style_json = (
                json.dumps(subtitle_style.model_dump(mode="json"))
                if subtitle_style is not None
                else None
            )
        row.updated_at = _utc_now_iso()
        self._session.flush()
        return self._hydrate_clip(row)

    def move_clip(
        self,
        clip_id: str,
        *,
        new_track_id: str | None = None,
        new_start_time: float,
        workflow_id: str | None = None,
    ) -> TimelineClipV1:
        self._begin_scoped_write(workflow_id)
        row = self._clip_for_write(clip_id, workflow_id)

        if new_track_id is not None and new_track_id != row.track_id:
            target_track = self._session.execute(
                select(TimelineTrackRow).where(TimelineTrackRow.track_id == new_track_id)
            ).scalar_one_or_none()
            current_track = self._session.execute(
                select(TimelineTrackRow).where(TimelineTrackRow.track_id == row.track_id)
            ).scalar_one()
            if (
                target_track is None
                or target_track.timeline_id != current_track.timeline_id
            ):
                raise V2PersistenceError(
                    "timeline_track_not_found",
                    "Target track does not exist on this timeline.",
                    stage="move_clip",
                    details={"track_id": new_track_id},
                )
            row.track_id = new_track_id
        row.start_time = new_start_time
        row.updated_at = _utc_now_iso()
        self._session.flush()
        return self._hydrate_clip(row)

    def delete_clip(self, clip_id: str, *, workflow_id: str | None = None) -> None:
        self._begin_scoped_write(workflow_id)
        row = self._clip_for_write(clip_id, workflow_id)
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
            subtitle_burn_in=row.subtitle_burn_in,
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
            volume_keyframes=_parse_volume_keyframes(row.volume_keyframes_json),
            transition_in_type=row.transition_in_type,
            transition_in_duration=row.transition_in_duration,
            transition_out_type=row.transition_out_type,
            transition_out_duration=row.transition_out_duration,
            bound_character_id=row.bound_character_id,
            subtitle_text=row.subtitle_text,
            subtitle_style=_parse_subtitle_style(row.subtitle_style_json),
            label=row.label,
            color=row.color,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
