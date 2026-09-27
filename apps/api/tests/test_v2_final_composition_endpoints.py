"""HTTP tests for the v2 final-composition timeline endpoints.

Two layers:
- Fake-service tests lock routing, serialization and the service-error ->
  HTTP mapping for every route (fast, deterministic).
- Real-service integration tests exercise GET/PATCH against a temp data dir
  (auto-create, idempotent reload, optimistic version conflict) plus the
  render lifecycle in mock media mode (start -> poll -> cancel).

The v2 final-composition surface previously 404'd while the frontend client
already called it (v2Client.ts final-composition methods); these tests are the
contract for that surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v2.endpoints import final_composition as fc_endpoint
from app.schemas.workflow_v2 import (
    WorkflowV2Timeline,
    WorkflowV2TimelineClipCreateRequest,
    WorkflowV2TimelineClipDeleteRequest,
    WorkflowV2TimelineClipMutationResponse,
    WorkflowV2TimelineRenderRequest,
    WorkflowV2TimelineRenderStartResponse,
    WorkflowV2TimelineRenderStateResponse,
    WorkflowV2TimelineResponse,
    WorkflowV2TimelineSourceImportRequest,
    WorkflowV2TimelineSourceImportResponse,
    WorkflowV2TimelineTrack,
    WorkflowV2TimelineUpdateRequest,
    WorkflowV2TimelineUpdateResponse,
    WorkflowV2,
)
from app.services.v2_final_composition_timeline import (
    V2FinalCompositionTimelineError,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeTimelineService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.error: V2FinalCompositionTimelineError | None = None

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    def get_timeline(self, workflow_id: str) -> WorkflowV2TimelineResponse:
        self.calls.append(("get_timeline", workflow_id))
        self._raise()
        return _timeline_response(workflow_id)

    def save_timeline(
        self, workflow_id: str, request: WorkflowV2TimelineUpdateRequest
    ) -> WorkflowV2TimelineUpdateResponse:
        self.calls.append(("save_timeline", (workflow_id, request)))
        self._raise()
        return WorkflowV2TimelineUpdateResponse(
            workflow_id=workflow_id,
            timeline=request.timeline,
            changed_clip_ids=[],
            runtime={},
        )

    def create_compatibility_clip(
        self, workflow_id: str, request: WorkflowV2TimelineClipCreateRequest
    ) -> WorkflowV2TimelineClipMutationResponse:
        self.calls.append(("create_clip", (workflow_id, request)))
        self._raise()
        return _clip_mutation(workflow_id)

    def delete_compatibility_clip(
        self, workflow_id: str, clip_id: str, request: WorkflowV2TimelineClipDeleteRequest
    ) -> WorkflowV2TimelineClipMutationResponse:
        self.calls.append(("delete_clip", (workflow_id, clip_id, request)))
        self._raise()
        return WorkflowV2TimelineClipMutationResponse(
            workflow=_workflow(workflow_id),
            removed_clip_id=clip_id,
        )

    def import_library_source(
        self, workflow_id: str, request: WorkflowV2TimelineSourceImportRequest
    ) -> WorkflowV2TimelineSourceImportResponse:
        self.calls.append(("import_source", (workflow_id, request)))
        self._raise()
        from app.schemas.workflow_v2 import WorkflowV2TimelineSource

        return WorkflowV2TimelineSourceImportResponse(
            workflow_id=workflow_id,
            source=WorkflowV2TimelineSource(
                asset_id="asset_1",
                version_id="ver_1",
                media_type=request.expected_media_type,
                display_name="library clip",
                origin="asset_library",
            ),
        )


class _FakeRenderService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.error: V2FinalCompositionTimelineError | None = None

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    def start_render(
        self, workflow_id: str, request: WorkflowV2TimelineRenderRequest
    ) -> WorkflowV2TimelineRenderStartResponse:
        self.calls.append(("start_render", (workflow_id, request)))
        self._raise()
        return WorkflowV2TimelineRenderStartResponse(
            workflow_id=workflow_id,
            render_id="render_abc123",
            status="queued",
            timeline_id=request.timeline_id,
            timeline_version=request.timeline_version,
            events_cursor=7,
        )

    def load_render_state(
        self, workflow_id: str, render_id: str
    ) -> WorkflowV2TimelineRenderStateResponse:
        self.calls.append(("load_render_state", (workflow_id, render_id)))
        self._raise()
        return _render_state(workflow_id, render_id, status="running")

    def cancel_render(
        self, workflow_id: str, render_id: str
    ) -> WorkflowV2TimelineRenderStateResponse:
        self.calls.append(("cancel_render", (workflow_id, render_id)))
        self._raise()
        return _render_state(workflow_id, render_id, status="cancelled")


def _workflow(workflow_id: str) -> WorkflowV2:
    from app.services.agent_trace import utc_now

    now = utc_now().isoformat()
    return WorkflowV2(
        workflow_id=workflow_id,
        name="final composition test",
        prompt="final composition test workflow",
        created_at=now,
        updated_at=now,
    )


def _timeline(version: int = 3) -> WorkflowV2Timeline:
    return WorkflowV2Timeline(
        timeline_id="tl-1",
        version=version,
        duration_seconds=0,
        tracks=[WorkflowV2TimelineTrack(track_id="track-video", track_type="video", order=1)],
        clips=[],
    )


def _timeline_response(workflow_id: str) -> WorkflowV2TimelineResponse:
    return WorkflowV2TimelineResponse(
        workflow_id=workflow_id,
        item_id="item-1",
        timeline=_timeline(),
        source="saved",
        runtime={},
        available_sources=[],
        stale_clip_ids=[],
        missing_source_clip_ids=[],
    )


def _clip_mutation(workflow_id: str) -> WorkflowV2TimelineClipMutationResponse:
    return WorkflowV2TimelineClipMutationResponse(
        workflow=_workflow(workflow_id),
        clip={"clip_id": "clip-1"},
    )


def _render_state(
    workflow_id: str, render_id: str, *, status: str
) -> WorkflowV2TimelineRenderStateResponse:
    return WorkflowV2TimelineRenderStateResponse(
        workflow_id=workflow_id,
        render_id=render_id,
        slot_id="final-composition:final_video",
        status=status,  # type: ignore[arg-type]
        timeline_id="tl-1",
        timeline_version=3,
        events_cursor=7,
        created_at="2026-09-25T00:00:00+00:00",
        updated_at="2026-09-25T00:00:00+00:00",
    )


@pytest.fixture
def fakes():
    timeline_service = _FakeTimelineService()
    render_service = _FakeRenderService()
    app = FastAPI()
    app.include_router(fc_endpoint.router)
    app.dependency_overrides[fc_endpoint.get_timeline_service] = lambda: timeline_service
    app.dependency_overrides[fc_endpoint.get_render_service] = lambda: render_service
    return TestClient(app), timeline_service, render_service


# ---------------------------------------------------------------------------
# Routing + serialization (fakes)
# ---------------------------------------------------------------------------


def test_get_timeline_returns_service_payload(fakes) -> None:
    client, service, _render = fakes
    response = client.get("/workflows/wf-1/final-composition/timeline")

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == "wf-1"
    assert body["node_id"] == "final-composition"
    assert body["timeline"]["timeline_id"] == "tl-1"
    assert body["source"] == "saved"
    assert service.calls == [("get_timeline", "wf-1")]


def test_save_timeline_forwards_request(fakes) -> None:
    client, service, _render = fakes
    payload = {
        "expected_version": 3,
        "timeline": _timeline().model_dump(mode="json"),
    }
    response = client.patch("/workflows/wf-1/final-composition/timeline", json=payload)

    assert response.status_code == 200
    assert response.json()["timeline"]["version"] == 3
    _workflow_id, request = service.calls[0][1]
    assert _workflow_id == "wf-1"
    assert request.expected_version == 3


def test_create_clip_returns_mutation_response(fakes) -> None:
    client, service, _render = fakes
    payload = {
        "source_asset_id": "asset_1",
        "source_version_id": "ver_1",
        "clip_type": "video",
        "start_time": 0,
        "duration": 3.0,
    }
    response = client.post(
        "/workflows/wf-1/final-composition/timeline/clips", json=payload
    )

    assert response.status_code == 200
    body = response.json()
    assert body["clip"]["clip_id"] == "clip-1"
    assert body["removed_clip_id"] is None
    _workflow_id, request = service.calls[0][1]
    assert request.clip_type == "video"
    assert request.duration == 3.0


def test_delete_clip_returns_mutation_response(fakes) -> None:
    client, service, _render = fakes
    response = client.request(
        "DELETE",
        "/workflows/wf-1/final-composition/timeline/clips/clip-9",
        json={"expected_version": 4},
    )

    assert response.status_code == 200
    assert response.json()["removed_clip_id"] == "clip-9"
    assert service.calls[0][0] == "delete_clip"
    assert service.calls[0][1][1] == "clip-9"


def test_import_source_returns_library_source(fakes) -> None:
    client, service, _render = fakes
    response = client.post(
        "/workflows/wf-1/final-composition/timeline/sources",
        json={
            "library_entity_id": "ent-1",
            "library_asset_id": "asset-1",
            "expected_media_type": "audio",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"]["asset_id"] == "asset_1"
    assert body["source"]["media_type"] == "audio"
    assert body["source"]["origin"] == "asset_library"


def test_start_render_is_accepted(fakes) -> None:
    client, _service, render = fakes
    response = client.post(
        "/workflows/wf-1/final-composition/render",
        json={"timeline_id": "tl-1", "timeline_version": 3},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["render_id"] == "render_abc123"
    assert body["status"] == "queued"
    assert body["events_cursor"] == 7


def test_get_render_state_returns_durable_state(fakes) -> None:
    client, _service, render = fakes
    response = client.get("/workflows/wf-1/final-composition/renders/render_abc123")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["render_id"] == "render_abc123"


def test_cancel_render_returns_terminal_state(fakes) -> None:
    client, _service, render = fakes
    response = client.post(
        "/workflows/wf-1/final-composition/renders/render_abc123/cancel"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Service error -> HTTP mapping (fakes)
# ---------------------------------------------------------------------------


def test_version_conflict_maps_to_409(fakes) -> None:
    client, service, _render = fakes
    service.error = V2FinalCompositionTimelineError(
        "v2_timeline_version_conflict",
        "Timeline version does not match expected_version.",
        status_code=409,
    )
    response = client.patch(
        "/workflows/wf-1/final-composition/timeline",
        json={
            "expected_version": 99,
            "timeline": _timeline().model_dump(mode="json"),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "v2_timeline_version_conflict"


def test_missing_clip_maps_to_404(fakes) -> None:
    client, service, _render = fakes
    service.error = V2FinalCompositionTimelineError(
        "v2_timeline_invalid_clip",
        "Timeline clip not found: clip-x",
        status_code=404,
    )
    response = client.request(
        "DELETE", "/workflows/wf-1/final-composition/timeline/clips/clip-x", json={}
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "v2_timeline_invalid_clip"


def test_unsupported_media_maps_to_422(fakes) -> None:
    client, service, _render = fakes
    service.error = V2FinalCompositionTimelineError(
        "v2_timeline_unsupported_source_media",
        "Library asset media_type does not match expected_media_type.",
        status_code=422,
        details={"expected": "video", "actual": "audio"},
    )
    response = client.post(
        "/workflows/wf-1/final-composition/timeline/sources",
        json={
            "library_entity_id": "ent-1",
            "library_asset_id": "asset-1",
            "expected_media_type": "video",
        },
    )

    assert response.status_code == 422
    body = response.json()["detail"]
    assert body["code"] == "v2_timeline_unsupported_source_media"
    assert body["details"]["actual"] == "audio"


def test_active_render_conflict_maps_to_409(fakes) -> None:
    client, _service, render = fakes
    render.error = V2FinalCompositionTimelineError(
        "v2_timeline_render_already_active",
        "Render already active: render_old",
        status_code=409,
    )
    response = client.post(
        "/workflows/wf-1/final-composition/render",
        json={"timeline_id": "tl-1", "timeline_version": 3},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "v2_timeline_render_already_active"


# ---------------------------------------------------------------------------
# Real-service integration
# ---------------------------------------------------------------------------


@pytest.fixture
def real_client(tmp_path: Path):
    from app.core.config import Settings
    from app.persistence.database import create_v2_database
    from app.persistence.schema import upgrade_v2_schema
    from app.services.v2_workflow_authoring import create_workflow_authoring_runtime

    from tests.helpers.v2_factories import make_v2_workflow

    settings = Settings(
        agent_runtime_mode="fake",
        media_mode="mock",
        final_composition_render_mode="timeline_editor",
        media_data_dir=tmp_path / "data",
    )
    (settings.media_data_dir / "v2").mkdir(parents=True, exist_ok=True)
    database = create_v2_database(settings.media_data_dir)
    try:
        upgrade_v2_schema(database)
    finally:
        database.dispose()

    workflow = make_v2_workflow(settings.media_data_dir, workflow_id="wf-final", save=False)
    runtime = create_workflow_authoring_runtime(settings.media_data_dir)
    try:
        runtime.service.create_planned_workflow(workflow)
    finally:
        runtime.database.dispose()

    app = FastAPI()
    app.include_router(fc_endpoint.router)
    app.dependency_overrides[fc_endpoint.get_timeline_service] = (
        lambda: _real_timeline_service(settings)
    )
    app.dependency_overrides[fc_endpoint.get_render_service] = (
        lambda: _real_render_service(settings)
    )
    client = TestClient(app)
    yield client, settings


def _real_timeline_service(settings):
    from app.services.v2_final_composition_timeline import (
        V2FinalCompositionTimelineService,
    )

    return V2FinalCompositionTimelineService(settings)


def _real_render_service(settings):
    from app.services.v2_final_composition_render_service import (
        V2FinalCompositionRenderService,
    )

    return V2FinalCompositionRenderService(settings)


@pytest.mark.integration
def test_real_get_timeline_auto_creates_then_reloads(real_client) -> None:
    client, _settings = real_client

    first = client.get("/workflows/wf-final/final-composition/timeline")
    assert first.status_code == 200
    body = first.json()
    assert body["source"] == "default"
    assert body["workflow_id"] == "wf-final"
    assert body["timeline"]["version"] == 1
    # Tracks are derived from selected assets; a workflow with no generated
    # media yet legitimately starts track-less — the contract is the stable
    # timeline identity, not the track count.
    assert isinstance(body["timeline"]["tracks"], list)

    second = client.get("/workflows/wf-final/final-composition/timeline")
    assert second.status_code == 200
    assert second.json()["source"] == "saved"
    assert second.json()["timeline"]["timeline_id"] == body["timeline"]["timeline_id"]


@pytest.mark.integration
def test_real_save_timeline_version_conflict_then_success(real_client) -> None:
    client, _settings = real_client

    current = client.get("/workflows/wf-final/final-composition/timeline").json()["timeline"]

    conflict = client.patch(
        "/workflows/wf-final/final-composition/timeline",
        json={"expected_version": 99, "timeline": current},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "v2_timeline_version_conflict"

    saved = client.patch(
        "/workflows/wf-final/final-composition/timeline",
        json={"expected_version": current["version"], "timeline": current},
    )
    assert saved.status_code == 200
    assert saved.json()["timeline"]["version"] == current["version"] + 1

    reloaded = client.get("/workflows/wf-final/final-composition/timeline").json()["timeline"]
    assert reloaded["version"] == current["version"] + 1


@pytest.mark.integration
def test_real_render_lifecycle_start_poll_cancel(real_client) -> None:
    client, _settings = real_client
    timeline = client.get("/workflows/wf-final/final-composition/timeline").json()["timeline"]

    started = client.post(
        "/workflows/wf-final/final-composition/render",
        json={"timeline_id": timeline["timeline_id"], "timeline_version": timeline["version"]},
    )
    assert started.status_code == 202
    render_id = started.json()["render_id"]

    state = client.get(f"/workflows/wf-final/final-composition/renders/{render_id}")
    assert state.status_code == 200
    assert state.json()["status"] in {"queued", "running", "completed", "failed"}
    assert state.json()["timeline_id"] == timeline["timeline_id"]

    cancelled = client.post(
        f"/workflows/wf-final/final-composition/renders/{render_id}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] in {"cancelled", "cancellation_requested", "completed"}

    # Cancellation is idempotent from the service's perspective: re-cancelling a
    # terminal/requested state returns the durable state, not an error.
    again = client.post(f"/workflows/wf-final/final-composition/renders/{render_id}/cancel")
    assert again.status_code == 200
