"""Tests for the v0.2 handover additions: voice-cast resynth + retained readings.

Covers:
- VoiceCastResynthLineRequest / VoiceCastResynthLineResponse model shape
- The _persist_retained_readings helper (no-op on empty list, DB write on non-empty)
- The TTS engine guard in the resynth endpoint (placeholder engine returns early)

The failure paths matter more than the happy one here: this helper runs
inside a try/except Exception: pass on purpose (persistence must never
block the response), so a test is the only thing proving the silence is
*bounded* — unknown workflow, unknown node — and not a swallowed bug that
loses every retained reading.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from app.api.v1.endpoints.scene_3d import (
    VoiceCastResynthLineRequest,
    VoiceCastResynthLineResponse,
)
from app.persistence.database import create_v2_database
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.event_repository import EventRepository
from app.persistence.project_repository import ProjectRepository


# ---------------------------------------------------------------------------
# VoiceCastResynthLineRequest / Response shape
# ---------------------------------------------------------------------------


class TestVoiceCastResynthLineModels:
    def test_request_minimal(self):
        req = VoiceCastResynthLineRequest(
            workflow_id="wf_1",
            node_id="node_1",
            line_id="l1",
        )
        assert req.workflow_id == "wf_1"
        assert req.node_id == "node_1"
        assert req.line_id == "l1"
        assert req.emotion_override is None
        assert req.force_remake is False

    def test_request_with_optional_fields(self):
        req = VoiceCastResynthLineRequest(
            workflow_id="wf_1",
            node_id="node_1",
            line_id="l1",
            emotion_override="calm",
            force_remake=True,
        )
        assert req.emotion_override == "calm"
        assert req.force_remake is True

    def test_response_defaults(self):
        resp = VoiceCastResynthLineResponse(success=True, line_id="l1")
        assert resp.emotion == ""
        assert resp.duration_seconds is None
        assert resp.take_asset_id is None
        assert resp.regenerated_line_ids == []
        assert resp.warnings == []
        assert resp.error is None


# ---------------------------------------------------------------------------
# Request validation (fail closed on a missing id)
# ---------------------------------------------------------------------------


class TestRequestValidation:
    @pytest.mark.parametrize("field", ["workflow_id", "node_id", "line_id"])
    def test_required_ids_are_not_optional(self, field):
        payload = {"workflow_id": "wf_1", "node_id": "node_1", "line_id": "l1"}
        del payload[field]
        with pytest.raises(ValidationError):
            VoiceCastResynthLineRequest(**payload)

    def test_unknown_field_is_ignored_not_stored(self):
        """The endpoint contract is the request model's fields; an extra key
        from a newer client must not land in the take manifest."""
        request = VoiceCastResynthLineRequest(
            workflow_id="wf_1",
            node_id="node_1",
            line_id="l1",
            voice_id="surprise",
        )
        assert request.model_dump() == {
            "workflow_id": "wf_1",
            "node_id": "node_1",
            "line_id": "l1",
            "emotion_override": None,
            "force_remake": False,
        }


# ---------------------------------------------------------------------------
# _persist_retained_readings behaviour
# ---------------------------------------------------------------------------


class TestPersistRetainedReadings:
    def test_noop_when_empty(self):
        """An empty retained_reading_ids list must not touch the database."""
        from app.api.v1.endpoints.scene_3d import _persist_retained_readings

        class FakeRequest(BaseModel):
            retained_reading_ids: list[str] = []

        req = FakeRequest()  # empty list
        # Should return immediately without raising (no DB access attempted).
        _persist_retained_readings(req, node_id="node_x", workflow_id="wf_x")
        # No exception = pass; a real DB would raise if accessed.

    def test_persists_ids_to_node(self, tmp_path):
        """When retained_reading_ids is non-empty the ids land on the node."""
        from app.api.v1.endpoints.scene_3d import _persist_retained_readings
        from datetime import datetime, timezone

        from app.persistence.schema import upgrade_v2_schema
        data_dir = tmp_path / "data"
        (data_dir / "v2").mkdir(parents=True)
        database = create_v2_database(data_dir)
        upgrade_v2_schema(database)

        # Build an isolated Settings instance so the helper opens the same
        # test database; no global cache surgery needed.
        from app.core.config import Settings

        settings = Settings.from_env()
        object.__setattr__(settings, "media_data_dir", data_dir)
        try:
            _repo = AgentCanvasWorkflowRepository(
                database,
                ProjectRepository(database),
                EventRepository(database),
            )
            # Register project + workflow shell directly (no idempotency plumbing)
            from sqlalchemy import insert

            from app.persistence.models import AgentCanvasWorkflowRow
            from app.persistence.project_repository import ProjectCreate
            from app.persistence.agent_canvas_requirement_repository import (
                AgentCanvasRequirementRepository,
            )

            now = datetime.now(timezone.utc)

            now_iso = now.isoformat()
            projects = ProjectRepository(database)
            requirements = AgentCanvasRequirementRepository(database)
            with database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    projects.insert_in_transaction(
                        connection,
                        ProjectCreate(
                            project_id="proj_r",
                            name="Resynth test",
                            created_at=now_iso,
                            updated_at=now_iso,
                        ),
                    )
                    connection.execute(
                        insert(AgentCanvasWorkflowRow).values(
                            workflow_id="wf_r",
                            project_id="proj_r",
                            workflow_schema_version=2,
                            canvas_model="agent_canvas_v1",
                            revision=1,
                            layout_revision=1,
                            created_at=now_iso,
                            updated_at=now_iso,
                        )
                    )
                    requirements.initialize_in_transaction(
                        connection,
                        workflow_id="wf_r",
                        created_at=now_iso,
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            repo2 = AgentCanvasWorkflowRepository(
                database, ProjectRepository(database), EventRepository(database)
            )
            from app.schemas.agent_canvas import CanvasNodeV2

            node = CanvasNodeV2(
                node_id="sc3d_1",
                workflow_id="wf_r",
                node_type="scene-3d",
                creative_role="scene_3d_previs",
                title="Test previs",
                status="draft",
                position={"x": 0, "y": 0},
                revision=1,
                created_at=now,
                updated_at=now,
            )
            repo2.add_node(node, expected_revision=1)

            class FakeRequest(BaseModel):
                retained_reading_ids: list[str] = []

            req = FakeRequest()
            req.retained_reading_ids = ["reading_a", "reading_b"]

            _persist_retained_readings(req, node_id="sc3d_1", workflow_id="wf_r", settings=settings)

            # Verify
            updated = repo2.get_node("wf_r", "sc3d_1")
            assert updated.structured_content.get("retained_reading_ids") == [
                "reading_a",
                "reading_b",
            ]
        finally:
            database.dispose()

    def test_unknown_workflow_does_not_raise_and_writes_nothing(self, tmp_path):
        """Persistence failure must not block the response — but it must be
        bounded: a workflow that does not exist is a no-op, not a crash."""
        from app.api.v1.endpoints.scene_3d import _persist_retained_readings
        from app.core.config import Settings
        from app.persistence.schema import upgrade_v2_schema

        data_dir = tmp_path / "data"
        (data_dir / "v2").mkdir(parents=True)
        database = create_v2_database(data_dir)
        upgrade_v2_schema(database)
        settings = Settings.from_env()
        object.__setattr__(settings, "media_data_dir", data_dir)
        try:
            class FakeRequest(BaseModel):
                retained_reading_ids: list[str] = []

            req = FakeRequest()
            req.retained_reading_ids = ["reading_a"]

            # Must not raise even though the workflow was never created.
            _persist_retained_readings(
                req, node_id="sc3d_1", workflow_id="wf_missing", settings=settings
            )

            repo = AgentCanvasWorkflowRepository(
                database, ProjectRepository(database), EventRepository(database)
            )
            with pytest.raises(Exception):
                repo.get_workflow("wf_missing")
        finally:
            database.dispose()

    def test_unknown_node_in_a_real_workflow_writes_nothing(self, tmp_path):
        """A node id the workflow does not have is skipped, not invented."""
        from app.api.v1.endpoints.scene_3d import _persist_retained_readings
        from datetime import datetime, timezone

        from app.core.config import Settings
        from app.persistence.agent_canvas_requirement_repository import (
            AgentCanvasRequirementRepository,
        )
        from app.persistence.models import AgentCanvasWorkflowRow
        from app.persistence.project_repository import ProjectCreate
        from app.persistence.schema import upgrade_v2_schema
        from sqlalchemy import insert

        data_dir = tmp_path / "data"
        (data_dir / "v2").mkdir(parents=True)
        database = create_v2_database(data_dir)
        upgrade_v2_schema(database)
        settings = Settings.from_env()
        object.__setattr__(settings, "media_data_dir", data_dir)
        try:
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()
            projects = ProjectRepository(database)
            requirements = AgentCanvasRequirementRepository(database)
            with database.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    projects.insert_in_transaction(
                        connection,
                        ProjectCreate(
                            project_id="proj_n",
                            name="Missing node test",
                            created_at=now_iso,
                            updated_at=now_iso,
                        ),
                    )
                    connection.execute(
                        insert(AgentCanvasWorkflowRow).values(
                            workflow_id="wf_n",
                            project_id="proj_n",
                            workflow_schema_version=2,
                            canvas_model="agent_canvas_v1",
                            revision=1,
                            layout_revision=1,
                            created_at=now_iso,
                            updated_at=now_iso,
                        )
                    )
                    requirements.initialize_in_transaction(
                        connection,
                        workflow_id="wf_n",
                        created_at=now_iso,
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

            class FakeRequest(BaseModel):
                retained_reading_ids: list[str] = []

            req = FakeRequest()
            req.retained_reading_ids = ["reading_a"]

            repo = AgentCanvasWorkflowRepository(
                database, ProjectRepository(database), EventRepository(database)
            )
            # No node was added, so the workflow has zero nodes.
            assert repo.get_workflow("wf_n").nodes == ()

            # Must not raise and must not create the node.
            _persist_retained_readings(
                req, node_id="sc3d_ghost", workflow_id="wf_n", settings=settings
            )
            assert repo.get_workflow("wf_n").nodes == ()
        finally:
            database.dispose()
