"""V2 Timeline orchestration endpoints (ADR 0007).

Timeline is the orchestration layer above nodes: it defines when each
asset (video / voice / bgm / sfx / camera / subtitle) plays on a
time-axis, and how clips are trimmed / transitioned / mixed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.persistence.database import create_v2_database
from app.persistence.errors import V2PersistenceError
from app.persistence.timeline_repository import TimelineRepository
from app.schemas.timeline import (
    TimelineClipCreateV1,
    TimelineClipMoveV1,
    TimelineClipUpdateV1,
    TimelineClipV1,
    TimelineTrackUpdateV1,
    TimelineTrackV1,
    TimelineUpdateV1,
    TimelineV1,
)


router = APIRouter(prefix="/workflows", tags=["v2-timeline"])


def get_timeline_repository(
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Dependency: build a TimelineRepository for the request, with proper session cleanup."""
    database = create_v2_database(settings.media_data_dir)
    session: Session = database.session_factory()
    try:
        repo = TimelineRepository(session)
        yield repo
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# --- Timeline ---


@router.get(
    "/{workflow_id}/timeline",
    response_model=TimelineV1,
    status_code=status.HTTP_200_OK,
    summary="Get the timeline for a workflow (auto-creates default if missing)",
)
def get_timeline(
    workflow_id: Annotated[str, Path(min_length=1)],
    repo: Annotated[TimelineRepository, Depends(get_timeline_repository)],
) -> TimelineV1:
    try:
        return repo.get_by_workflow_id(workflow_id)
    except V2PersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code, "message": "Timeline persistence unavailable."},
        ) from exc


@router.patch(
    "/{workflow_id}/timeline",
    response_model=TimelineV1,
    status_code=status.HTTP_200_OK,
    summary="Update timeline metadata (duration / fps)",
)
def update_timeline(
    workflow_id: Annotated[str, Path(min_length=1)],
    payload: TimelineUpdateV1,
    repo: Annotated[TimelineRepository, Depends(get_timeline_repository)],
) -> TimelineV1:
    timeline = repo.get_by_workflow_id(workflow_id)
    return repo.update_timeline(
        timeline.timeline_id,
        duration_seconds=payload.duration_seconds,
        fps=payload.fps,
        # Explicit-null semantics: only forward ducking when the client sent
        # the field at all (null resets to renderer auto-defaults).
        **(
            {"ducking": payload.ducking}
            if "ducking" in payload.model_fields_set
            else {}
        ),
    )


# --- Tracks ---


@router.get(
    "/{workflow_id}/timeline/tracks",
    response_model=list[TimelineTrackV1],
    status_code=status.HTTP_200_OK,
    summary="List all tracks in the timeline",
)
def list_tracks(
    workflow_id: Annotated[str, Path(min_length=1)],
    repo: Annotated[TimelineRepository, Depends(get_timeline_repository)],
) -> list[TimelineTrackV1]:
    timeline = repo.get_by_workflow_id(workflow_id)
    return repo.get_tracks(timeline.timeline_id)


@router.patch(
    "/{workflow_id}/timeline/tracks/{track_id}",
    response_model=TimelineTrackV1,
    status_code=status.HTTP_200_OK,
    summary="Update a track (name / muted / volume / locked / display_order)",
)
def update_track(
    workflow_id: Annotated[str, Path(min_length=1)],
    track_id: Annotated[str, Path(min_length=1)],
    payload: TimelineTrackUpdateV1,
    repo: Annotated[TimelineRepository, Depends(get_timeline_repository)],
) -> TimelineTrackV1:
    return repo.update_track(
        track_id,
        name=payload.name,
        muted=payload.muted,
        volume=payload.volume,
        locked=payload.locked,
        display_order=payload.display_order,
    )


# --- Clips ---


@router.post(
    "/{workflow_id}/timeline/clips",
    response_model=TimelineClipV1,
    status_code=status.HTTP_201_CREATED,
    summary="Manually add a clip to a track",
)
def create_clip(
    workflow_id: Annotated[str, Path(min_length=1)],
    payload: TimelineClipCreateV1,
    repo: Annotated[TimelineRepository, Depends(get_timeline_repository)],
) -> TimelineClipV1:
    return repo.add_clip(
        track_id=payload.track_id,
        start_time=payload.start_time,
        duration=payload.duration,
        asset_id=payload.asset_id,
        asset_version_id=payload.asset_version_id,
        source_node_id=payload.source_node_id,
        source_start=payload.source_start,
        source_duration=payload.source_duration,
        fade_in=payload.fade_in,
        fade_out=payload.fade_out,
        label=payload.label,
        color=payload.color,
    )


@router.patch(
    "/{workflow_id}/timeline/clips/{clip_id}",
    response_model=TimelineClipV1,
    status_code=status.HTTP_200_OK,
    summary="Update a clip (position / duration / trimming / fades / transitions)",
)
def update_clip(
    workflow_id: Annotated[str, Path(min_length=1)],
    clip_id: Annotated[str, Path(min_length=1)],
    payload: TimelineClipUpdateV1,
    repo: Annotated[TimelineRepository, Depends(get_timeline_repository)],
) -> TimelineClipV1:
    # Non-nullable positional fields: None simply means "leave untouched".
    updates: dict[str, object] = {
        "start_time": payload.start_time,
        "duration": payload.duration,
        "source_start": payload.source_start,
    }
    # Nullable fields follow explicit-null semantics: only forward them when
    # the client sent the field (JSON null clears a previously stored value).
    for nullable_field in (
        "source_node_id",
        "source_duration",
        "fade_in",
        "fade_out",
        "transition_in_type",
        "transition_in_duration",
        "transition_out_type",
        "transition_out_duration",
        "bound_character_id",
        "label",
        "color",
    ):
        if nullable_field in payload.model_fields_set:
            updates[nullable_field] = getattr(payload, nullable_field)
    return repo.update_clip(clip_id, **updates)


@router.post(
    "/{workflow_id}/timeline/clips/{clip_id}/move",
    response_model=TimelineClipV1,
    status_code=status.HTTP_200_OK,
    summary="Move a clip to a new track and/or start time",
)
def move_clip(
    workflow_id: Annotated[str, Path(min_length=1)],
    clip_id: Annotated[str, Path(min_length=1)],
    payload: TimelineClipMoveV1,
    repo: Annotated[TimelineRepository, Depends(get_timeline_repository)],
) -> TimelineClipV1:
    try:
        return repo.move_clip(
            clip_id,
            new_track_id=payload.track_id,
            new_start_time=payload.start_time,
        )
    except V2PersistenceError as exc:
        if exc.code == "timeline_track_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        raise


@router.delete(
    "/{workflow_id}/timeline/clips/{clip_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a clip from the timeline",
)
def delete_clip(
    workflow_id: Annotated[str, Path(min_length=1)],
    clip_id: Annotated[str, Path(min_length=1)],
    repo: Annotated[TimelineRepository, Depends(get_timeline_repository)],
) -> None:
    repo.delete_clip(clip_id)
