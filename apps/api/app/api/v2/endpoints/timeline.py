"""V2 Timeline orchestration endpoints (ADR 0007).

Timeline is the orchestration layer above nodes: it defines when each
asset (video / voice / bgm / sfx / camera / subtitle) plays on a
time-axis, and how clips are trimmed / transitioned / mixed.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path as FilePath
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.database import create_v2_database
from app.persistence.errors import V2PersistenceError
from app.persistence.timeline_repository import TimelineRepository
from app.schemas.timeline import (
    TimelineBeatAnalysisV1,
    TimelineClipCreateV1,
    TimelineClipMoveV1,
    TimelineClipUpdateV1,
    TimelineClipV1,
    TimelineTrackUpdateV1,
    TimelineTrackV1,
    TimelineUpdateV1,
    TimelineV1,
)
from app.services.timeline_beat_analysis import BeatAnalysisError, BeatAnalyzer
from app.services.timeline_subtitle_writer import clips_to_ass, clips_to_srt
from app.services.v2_storage_adapter import StorageAdapter


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


@contextmanager
def _timeline_write_errors():
    """Hide missing and foreign-workflow IDs behind the same HTTP 404."""
    try:
        yield
    except V2PersistenceError as exc:
        if exc.code in {"timeline_track_not_found", "timeline_clip_not_found"}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        raise


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
        subtitle_burn_in=payload.subtitle_burn_in,
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
    with _timeline_write_errors():
        return repo.update_track(
            track_id,
            workflow_id=workflow_id,
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
    with _timeline_write_errors():
        return repo.add_clip(
            workflow_id=workflow_id,
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
            volume_keyframes=payload.volume_keyframes,
            label=payload.label,
            color=payload.color,
            subtitle_text=payload.subtitle_text,
            subtitle_style=payload.subtitle_style,
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
        "volume_keyframes",
        "transition_in_type",
        "transition_in_duration",
        "transition_out_type",
        "transition_out_duration",
        "bound_character_id",
        "label",
        "color",
        "subtitle_text",
        "subtitle_style",
    ):
        if nullable_field in payload.model_fields_set:
            updates[nullable_field] = getattr(payload, nullable_field)
    with _timeline_write_errors():
        return repo.update_clip(clip_id, workflow_id=workflow_id, **updates)


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
    with _timeline_write_errors():
        return repo.move_clip(
            clip_id,
            workflow_id=workflow_id,
            new_track_id=payload.track_id,
            new_start_time=payload.start_time,
        )


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
    with _timeline_write_errors():
        repo.delete_clip(clip_id, workflow_id=workflow_id)


# --- Subtitle export ---


@router.get(
    "/{workflow_id}/timeline/subtitles",
    summary="Download subtitle-track cues as an SRT or ASS sidecar file",
)
def export_timeline_subtitles(
    workflow_id: Annotated[str, Path(min_length=1)],
    repo: Annotated[TimelineRepository, Depends(get_timeline_repository)],
    subtitle_format: Literal["srt", "ass"] = Query(
        "srt",
        alias="format",
        description="Subtitle document format: srt (plain) or ass (styled).",
    ),
) -> Response:
    timeline = repo.get_by_workflow_id(workflow_id)
    # Muted subtitle tracks are excluded from exports, mirroring burn-in.
    subtitle_clips = [
        clip
        for track in timeline.tracks
        if track.type == "subtitle" and not track.muted
        for clip in track.clips
    ]
    if subtitle_format == "ass":
        content = clips_to_ass(subtitle_clips)
        media_type = "text/x-ass; charset=utf-8"
        filename = "subtitles.ass"
    else:
        content = clips_to_srt(subtitle_clips)
        media_type = "application/x-subrip; charset=utf-8"
        filename = "subtitles.srt"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Beat analysis (Phase 4.4) ---


@dataclass
class BeatAnalysisTools:
    """Resolves a clip's asset to a local file and runs DSP analysis on it."""

    assets: V2AssetLibraryRepository
    storage: StorageAdapter
    analyzer: BeatAnalyzer

    def resolve_asset_path(self, asset_id: str) -> FilePath:
        version = self.assets.find_version(asset_id=asset_id)
        if version is None:
            raise V2PersistenceError(
                "asset_not_found",
                "Asset was not found.",
                stage="timeline_beat_analysis",
            )
        path = self.storage.resolve_local_path(version.storage_key)
        if not path.is_file():
            raise V2PersistenceError(
                "asset_not_ready",
                "Asset content is unavailable.",
                stage="timeline_beat_analysis",
            )
        return path


def get_beat_analysis_tools(
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Dependency: asset lookup + storage + the numpy/ffmpeg beat analyzer."""
    database = create_v2_database(settings.media_data_dir)
    yield BeatAnalysisTools(
        assets=V2AssetLibraryRepository(database),
        storage=StorageAdapter(settings.media_data_dir),
        analyzer=BeatAnalyzer(settings.ffmpeg_path),
    )


@router.get(
    "/{workflow_id}/timeline/clips/{clip_id}/beats",
    response_model=TimelineBeatAnalysisV1,
    status_code=status.HTTP_200_OK,
    summary="Detect BPM and asset-relative beat times for an audio clip",
)
def analyze_clip_beats(
    workflow_id: Annotated[str, Path(min_length=1)],
    clip_id: Annotated[str, Path(min_length=1)],
    repo: Annotated[TimelineRepository, Depends(get_timeline_repository)],
    tools: Annotated[BeatAnalysisTools, Depends(get_beat_analysis_tools)],
) -> TimelineBeatAnalysisV1:
    try:
        timeline = repo.get_by_workflow_id(workflow_id)
    except V2PersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code, "message": "Timeline persistence unavailable."},
        ) from exc

    clip = next(
        (
            candidate
            for track in timeline.tracks
            for candidate in track.clips
            if candidate.clip_id == clip_id
        ),
        None,
    )
    if clip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "timeline_clip_not_found", "message": "Clip was not found."},
        )
    if not clip.asset_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "beat_analysis_no_asset",
                "message": "Clip has no linked audio asset.",
            },
        )

    try:
        media_path = tools.resolve_asset_path(clip.asset_id)
        analysis = tools.analyzer.analyze(str(media_path))
    except V2PersistenceError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code == "asset_not_found"
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except BeatAnalysisError as exc:
        status_code = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if exc.code in {"beat_analysis_too_short", "beat_analysis_indeterminate"}
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    return TimelineBeatAnalysisV1(
        bpm=analysis.bpm,
        beats=analysis.beats,
        confidence=analysis.confidence,
    )
