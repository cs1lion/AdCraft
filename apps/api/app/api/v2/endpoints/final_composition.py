"""V2 final-composition timeline endpoints (editor-facing surface).

Serves the timeline editor API that the Agent Canvas editing workbench calls:
the canonical workflow timeline (ADR-independent service layer,
``v2_final_composition_timeline``) plus the durable detached render service
(``v2_final_composition_render_service``).

Concurrency: every mutation carries ``expected_version`` in its body; the
service rejects stale writes with ``409 v2_timeline_version_conflict``. This is
the editor's optimistic-lock contract (distinct from the ADR-0007 timeline's
HTTP ETag/If-Match contract).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.core.config import Settings, get_settings
from app.schemas.workflow_v2 import (
    WorkflowV2TimelineClipCreateRequest,
    WorkflowV2TimelineClipDeleteRequest,
    WorkflowV2TimelineClipMutationResponse,
    WorkflowV2TimelineRenderRequest,
    WorkflowV2TimelineRenderStartResponse,
    WorkflowV2TimelineRenderStateResponse,
    WorkflowV2TimelineResponse,
    WorkflowV2TimelineSourceImportRequest,
    WorkflowV2TimelineSourceImportResponse,
    WorkflowV2TimelineUpdateRequest,
    WorkflowV2TimelineUpdateResponse,
)
from app.services.v2_final_composition_render_service import (
    V2FinalCompositionRenderService,
)
from app.services.v2_final_composition_timeline import (
    V2FinalCompositionTimelineError,
    V2FinalCompositionTimelineService,
)


router = APIRouter(prefix="/workflows", tags=["v2-final-composition"])


def get_timeline_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2FinalCompositionTimelineService:
    """Dependency: the final-composition timeline service for this request."""
    return V2FinalCompositionTimelineService(settings)


def get_render_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> V2FinalCompositionRenderService:
    """Dependency: the durable final-composition render service for this request."""
    return V2FinalCompositionRenderService(settings)


def _raise_service_error(exc: V2FinalCompositionTimelineError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": str(exc),
            "details": exc.details,
        },
    )


@router.get(
    "/{workflow_id}/final-composition/timeline",
    response_model=WorkflowV2TimelineResponse,
    summary="Get the final-composition timeline (auto-creates the system default)",
)
def get_final_timeline(
    workflow_id: Annotated[str, Path(min_length=1)],
    service: Annotated[V2FinalCompositionTimelineService, Depends(get_timeline_service)],
) -> WorkflowV2TimelineResponse:
    try:
        return service.get_timeline(workflow_id)
    except V2FinalCompositionTimelineError as exc:
        _raise_service_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load final-composition timeline: {str(exc)[:200]}",
        ) from exc


@router.patch(
    "/{workflow_id}/final-composition/timeline",
    response_model=WorkflowV2TimelineUpdateResponse,
    summary="Save the final-composition timeline (optimistic version lock)",
)
def save_final_timeline(
    workflow_id: Annotated[str, Path(min_length=1)],
    request: WorkflowV2TimelineUpdateRequest,
    service: Annotated[V2FinalCompositionTimelineService, Depends(get_timeline_service)],
) -> WorkflowV2TimelineUpdateResponse:
    try:
        return service.save_timeline(workflow_id, request)
    except V2FinalCompositionTimelineError as exc:
        _raise_service_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save final-composition timeline: {str(exc)[:200]}",
        ) from exc


@router.post(
    "/{workflow_id}/final-composition/timeline/clips",
    response_model=WorkflowV2TimelineClipMutationResponse,
    summary="Create a timeline clip from a workflow or library asset",
)
def create_final_timeline_clip(
    workflow_id: Annotated[str, Path(min_length=1)],
    request: WorkflowV2TimelineClipCreateRequest,
    service: Annotated[V2FinalCompositionTimelineService, Depends(get_timeline_service)],
) -> WorkflowV2TimelineClipMutationResponse:
    try:
        return service.create_compatibility_clip(workflow_id, request)
    except V2FinalCompositionTimelineError as exc:
        _raise_service_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create timeline clip: {str(exc)[:200]}",
        ) from exc


@router.delete(
    "/{workflow_id}/final-composition/timeline/clips/{clip_id}",
    response_model=WorkflowV2TimelineClipMutationResponse,
    summary="Delete a timeline clip",
)
def delete_final_timeline_clip(
    workflow_id: Annotated[str, Path(min_length=1)],
    clip_id: Annotated[str, Path(min_length=1)],
    request: WorkflowV2TimelineClipDeleteRequest,
    service: Annotated[V2FinalCompositionTimelineService, Depends(get_timeline_service)],
) -> WorkflowV2TimelineClipMutationResponse:
    try:
        return service.delete_compatibility_clip(workflow_id, clip_id, request)
    except V2FinalCompositionTimelineError as exc:
        _raise_service_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete timeline clip: {str(exc)[:200]}",
        ) from exc


@router.post(
    "/{workflow_id}/final-composition/timeline/sources",
    response_model=WorkflowV2TimelineSourceImportResponse,
    summary="Import a library asset as a timeline source (drag-in entry)",
)
def import_final_timeline_source(
    workflow_id: Annotated[str, Path(min_length=1)],
    request: WorkflowV2TimelineSourceImportRequest,
    service: Annotated[V2FinalCompositionTimelineService, Depends(get_timeline_service)],
) -> WorkflowV2TimelineSourceImportResponse:
    try:
        return service.import_library_source(workflow_id, request)
    except V2FinalCompositionTimelineError as exc:
        _raise_service_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import timeline source: {str(exc)[:200]}",
        ) from exc


@router.post(
    "/{workflow_id}/final-composition/render",
    response_model=WorkflowV2TimelineRenderStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start (or reuse) a durable final-composition render",
)
def start_final_render(
    workflow_id: Annotated[str, Path(min_length=1)],
    request: WorkflowV2TimelineRenderRequest,
    service: Annotated[V2FinalCompositionRenderService, Depends(get_render_service)],
) -> WorkflowV2TimelineRenderStartResponse:
    try:
        return service.start_render(workflow_id, request)
    except V2FinalCompositionTimelineError as exc:
        _raise_service_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start final-composition render: {str(exc)[:200]}",
        ) from exc


@router.get(
    "/{workflow_id}/final-composition/renders/{render_id}",
    response_model=WorkflowV2TimelineRenderStateResponse,
    summary="Poll a final-composition render's durable state",
)
def get_final_render_state(
    workflow_id: Annotated[str, Path(min_length=1)],
    render_id: Annotated[str, Path(min_length=1)],
    service: Annotated[V2FinalCompositionRenderService, Depends(get_render_service)],
) -> WorkflowV2TimelineRenderStateResponse:
    try:
        return service.load_render_state(workflow_id, render_id)
    except V2FinalCompositionTimelineError as exc:
        _raise_service_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load render state: {str(exc)[:200]}",
        ) from exc


@router.post(
    "/{workflow_id}/final-composition/renders/{render_id}/cancel",
    response_model=WorkflowV2TimelineRenderStateResponse,
    summary="Request cancellation of a final-composition render",
)
def cancel_final_render(
    workflow_id: Annotated[str, Path(min_length=1)],
    render_id: Annotated[str, Path(min_length=1)],
    service: Annotated[V2FinalCompositionRenderService, Depends(get_render_service)],
) -> WorkflowV2TimelineRenderStateResponse:
    try:
        return service.cancel_render(workflow_id, render_id)
    except V2FinalCompositionTimelineError as exc:
        _raise_service_error(exc)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel render: {str(exc)[:200]}",
        ) from exc
