"""Workflow-scoped HTTP writes must not mutate foreign timelines (ADR 0007).

Use only a temporary database and a minimal router app, never application lifespan.
The dotenv loader is stubbed before importing the endpoint/config module.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.persistence.database import create_v2_database
from app.persistence.models import AgentCanvasWorkflowRow, ProjectRow
from app.persistence.timeline_repository import TimelineRepository

pytestmark = pytest.mark.integration
_TS = "2026-09-17T00:00:00+00:00"


@pytest.fixture
def scope_context(v2_media_data_dir):
    with patch("dotenv.load_dotenv", return_value=False):
        from app.api.v2.endpoints import timeline as endpoint

    database = create_v2_database(v2_media_data_dir)
    with database.session_factory() as session:
        for workflow_id in ("A", "B"):
            session.add(ProjectRow(
                project_id=f"project-{workflow_id}", name=workflow_id,
                created_at=_TS, updated_at=_TS,
            ))
        session.flush()
        for workflow_id in ("A", "B"):
            session.add(AgentCanvasWorkflowRow(
                workflow_id=workflow_id, project_id=f"project-{workflow_id}",
                created_at=_TS, updated_at=_TS,
            ))
        session.flush()
        repo = TimelineRepository(session)
        timelines = {wf: repo.get_by_workflow_id(wf) for wf in ("A", "B")}
        clips = {wf: repo.add_clip(
            track_id=timelines[wf].tracks[0].track_id,
            start_time=1, duration=2, label=f"clip-{wf}",
        ) for wf in ("A", "B")}
        session.commit()

    def repository():
        with database.session_factory() as session:
            try:
                yield TimelineRepository(session)
                session.commit()
            except Exception:
                session.rollback()
                raise

    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[endpoint.get_timeline_repository] = repository
    with TestClient(app) as client:
        yield client, database, timelines, clips
    database.dispose()


def _snapshot(database):
    with database.session_factory() as session:
        repo = TimelineRepository(session)
        return {wf: repo.get_by_workflow_id(wf).model_dump() for wf in ("A", "B")}


def _request(client, operation, workflow, track_id, clip_id, target=None):
    root = f"/workflows/{workflow}/timeline"
    if operation == "track":
        return client.patch(f"{root}/tracks/{track_id}", json={"name": "changed", "muted": True})
    if operation == "create":
        return client.post(f"{root}/clips", json={
            "track_id": track_id, "start_time": 50, "duration": 2,
        })
    if operation == "update":
        return client.patch(f"{root}/clips/{clip_id}", json={"label": "changed", "duration": 9})
    if operation == "delete":
        return client.delete(f"{root}/clips/{clip_id}")
    payload = {"start_time": 8}
    if target is not None:
        payload["track_id"] = target
    return client.post(f"{root}/clips/{clip_id}/move", json=payload)


@pytest.mark.parametrize("operation", ["track", "create", "update", "move", "delete"])
@pytest.mark.parametrize("foreign", [True, False], ids=["A-url-B-id", "missing-id"])
def test_rejected_writes_preserve_both_workflows(scope_context, operation, foreign):
    client, database, timelines, clips = scope_context
    before = _snapshot(database)
    track_id = timelines["B"].tracks[0].track_id if foreign else "missing-track"
    clip_id = clips["B"].clip_id if foreign else "missing-clip"
    response = _request(client, operation, "A", track_id, clip_id)
    assert response.status_code == 404, response.text
    expected = "timeline_track_not_found" if operation in {"track", "create"} else "timeline_clip_not_found"
    assert response.json()["detail"]["code"] == expected
    # Includes every field: clip count, duration, timestamps, labels and placement.
    assert _snapshot(database) == before


@pytest.mark.parametrize("source", ["A", "B"])
def test_move_wrong_target_or_wrong_source_is_atomic(scope_context, source):
    client, database, timelines, clips = scope_context
    before = _snapshot(database)
    # A source -> B target retains the original same-timeline guard.
    # B source -> B target used to bypass the A URL entirely.
    response = _request(
        client, "move", "A", timelines[source].tracks[0].track_id,
        clips[source].clip_id, target=timelines["B"].tracks[1].track_id,
    )
    assert response.status_code == 404, response.text
    expected = "timeline_track_not_found" if source == "A" else "timeline_clip_not_found"
    assert response.json()["detail"]["code"] == expected
    assert _snapshot(database) == before


@pytest.mark.parametrize("operation", ["track", "create", "update", "move", "delete"])
def test_owned_http_writes_succeed_without_changing_other_workflow(scope_context, operation):
    client, database, timelines, clips = scope_context
    before = _snapshot(database)
    response = _request(
        client, operation, "A", timelines["A"].tracks[0].track_id,
        clips["A"].clip_id,
        target=timelines["A"].tracks[1].track_id if operation == "move" else None,
    )
    assert response.status_code == {"create": 201, "delete": 204}.get(operation, 200), response.text
    after = _snapshot(database)
    assert after["B"] == before["B"]
    assert after["A"] != before["A"]
    if operation == "move":
        assert response.json()["track_id"] == timelines["A"].tracks[1].track_id
        assert response.json()["start_time"] == 8


def test_sqlite_reserves_writer_before_scope_lookup(scope_context):
    from sqlalchemy import event

    _, database, timelines, _ = scope_context
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", record)
    try:
        with database.session_factory() as session:
            TimelineRepository(session).update_track(
                timelines["A"].tracks[0].track_id, workflow_id="A", name="reserved",
            )
            assert session.connection().connection.driver_connection.in_transaction
            # Ownership predicate is read only AFTER SQLite reserves its writer.
            assert statements[0] == "BEGIN IMMEDIATE"
            assert "timelines.workflow_id" in statements[1]
            session.rollback()
    finally:
        event.remove(database.engine, "before_cursor_execute", record)


def test_scoped_write_uses_existing_transaction_without_nested_begin(scope_context):
    _, database, timelines, clips = scope_context
    before = _snapshot(database)
    with database.session_factory() as session:
        repo = TimelineRepository(session)
        # Legacy/internal callers can still omit workflow_id.
        repo.update_clip(clips["A"].clip_id, label="pending-internal-edit")
        repo.update_track(timelines["A"].tracks[0].track_id, workflow_id="A", name="pending")
        session.rollback()
    assert _snapshot(database) == before
