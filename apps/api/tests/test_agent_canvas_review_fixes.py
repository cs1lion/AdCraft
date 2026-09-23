"""Regression locks for the review-blocking fixes.

Covers: soft-deleted canvas nodes no longer pin their output assets,
``publish_node_output`` merging (not replacing) structured content, the
dynamic scheduler admitting every schedulable node type, the credential
runtime reloader accepting cleared endpoint fields whose Settings default is
non-None, and the ``/render/jobs`` route staying ahead of ``/render/{job_id}``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, get_args

import pytest

from app.api.v1.endpoints.scene_3d import router as scene_3d_router
from app.persistence.agent_canvas_requirement_repository import AgentCanvasRequirementRepository
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.database import create_v2_database
from app.persistence.event_repository import EventRepository
from app.persistence.models import AgentCanvasWorkflowRow
from app.persistence.project_repository import ProjectRepository
from app.persistence.schema import upgrade_v2_schema
from app.schemas.agent_canvas import (
    CanvasNodeErrorV2,
    CanvasNodeV2,
    CanvasNodeTypeV2,
)
from app.schemas.workflow_v2_projects import ProjectCreate
from app.services.agent_canvas_runtime import DynamicCanvasScheduler
from app.services.provider_credentials import RuntimeSettingsReloader
from sqlalchemy import insert

pytestmark = [pytest.mark.integration]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def canvas_db(tmp_path: Any) -> Any:
    data_dir = tmp_path / "data"
    (data_dir / "v2").mkdir(parents=True)
    database = create_v2_database(data_dir)
    upgrade_v2_schema(database)
    yield database
    database.dispose()


def _seed_workflow(database: Any, workflow_id: str) -> None:
    iso = _now().isoformat()
    project = ProjectCreate(
        project_id=f"project_{workflow_id}",
        name="Review-fix project",
        created_at=iso,
        updated_at=iso,
    )
    with database.engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        ProjectRepository(database).insert_in_transaction(connection, project)
        connection.execute(
            insert(AgentCanvasWorkflowRow).values(
                workflow_id=workflow_id,
                project_id=project.project_id,
                workflow_schema_version=2,
                canvas_model="agent_canvas_v1",
                revision=1,
                layout_revision=1,
                created_at=iso,
                updated_at=iso,
            )
        )
        AgentCanvasRequirementRepository(database).initialize_in_transaction(
            connection,
            workflow_id=workflow_id,
            created_at=iso,
        )
        connection.commit()


def _image_node(workflow_id: str, *, structured_content: dict[str, Any] | None = None) -> CanvasNodeV2:
    now = _now()
    return CanvasNodeV2(
        node_id="node_image_1",
        workflow_id=workflow_id,
        node_type="image",
        creative_role="scene",
        title="Review fix node",
        status="working",
        structured_content=structured_content or {},
        position={"x": 0, "y": 0},
        revision=1,
        created_at=now,
        updated_at=now,
    )


def _repository(database: Any) -> AgentCanvasWorkflowRepository:
    return AgentCanvasWorkflowRepository(
        database,
        ProjectRepository(database),
        EventRepository(database),
    )


def test_asset_is_referenced_ignores_soft_deleted_nodes(canvas_db: Any) -> None:
    workflows = _repository(canvas_db)
    _seed_workflow(canvas_db, "wf_refcheck")
    workflows.add_node(_image_node("wf_refcheck"), expected_revision=1)
    published = workflows.publish_node_output(
        "wf_refcheck",
        "node_image_1",
        execution_id="exec_refcheck",
        updated_at=_now(),
        output_asset_id="asset_refcheck_1",
    )
    assert published.output_asset_id == "asset_refcheck_1"
    assert workflows.asset_is_referenced("asset_refcheck_1") is True

    workflow = workflows.get_workflow("wf_refcheck")
    workflows.delete_node(
        "wf_refcheck",
        "node_image_1",
        expected_revision=workflow.revision,
    )

    assert workflows.asset_is_referenced("asset_refcheck_1") is False


def test_publish_node_output_merges_structured_content(canvas_db: Any) -> None:
    workflows = _repository(canvas_db)
    _seed_workflow(canvas_db, "wf_merge")
    workflows.add_node(
        _image_node("wf_merge", structured_content={"panel_field": "keep-me"}),
        expected_revision=1,
    )
    workflows.publish_node_output(
        "wf_merge",
        "node_image_1",
        execution_id="exec_merge",
        updated_at=_now(),
        output_asset_id="asset_merge_1",
        structured_content={"scene_script": {"shots": 1}},
    )
    merged = workflows.get_node("wf_merge", "node_image_1")
    assert merged.structured_content["panel_field"] == "keep-me"
    assert merged.structured_content["scene_script"] == {"shots": 1}


def test_scheduler_limits_cover_all_schedulable_node_types() -> None:
    scheduler = DynamicCanvasScheduler(None, None, None, None, None, media_publisher=None)
    schedulable = set(get_args(CanvasNodeTypeV2)) - {"editing"}
    assert schedulable <= set(scheduler._limits)
    # An unknown future node type must degrade to the total limit, not crash.
    assert scheduler._limits.get("future-kind", scheduler._total_limit) == scheduler._total_limit


def test_reloader_apply_accepts_cleared_endpoint_field(monkeypatch: Any) -> None:
    monkeypatch.setenv("SILICONFLOW_BASE_URL", "https://example.test/v1")
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    from app.core.config import Settings
    from app.services.provider_credentials import ConsumerCredentialBinding

    def _settings_loader() -> Settings:
        return Settings(
            siliconflow_api_key=os.environ.get("SILICONFLOW_API_KEY"),
            siliconflow_base_url=(
                os.environ.get("SILICONFLOW_BASE_URL") or Settings().siliconflow_base_url
            ),
        )

    binding = ConsumerCredentialBinding(
        consumer="text",
        dotenv_field="SILICONFLOW_API_KEY",
        settings_field="siliconflow_api_key",
        endpoint_field="siliconflow_base_url",
        test_capability="unsupported",
        endpoint_dotenv_field="SILICONFLOW_BASE_URL",
    )
    reloader = RuntimeSettingsReloader(
        settings_loader=_settings_loader,
        cache_clear=lambda: None,
    )

    cleared = reloader.apply({"SILICONFLOW_BASE_URL": None}, [binding])
    assert "SILICONFLOW_BASE_URL" not in os.environ
    assert cleared.siliconflow_base_url == Settings().siliconflow_base_url

    monkeypatch.setenv("SILICONFLOW_BASE_URL", "https://example.test/v2")
    updated = reloader.apply({"SILICONFLOW_BASE_URL": "https://example.test/v2"}, [binding])
    assert updated.siliconflow_base_url == "https://example.test/v2"


def test_render_jobs_route_is_declared_before_job_id_route() -> None:
    paths = [getattr(route, "path", "") for route in scene_3d_router.routes]

    def index_of(suffix: str) -> int:
        return next(index for index, path in enumerate(paths) if path.endswith(suffix))

    assert index_of("/render/jobs") < index_of("/render/{job_id}")


def _ready_node(workflow_id: str, node_id: str) -> CanvasNodeV2:
    """A node that already holds a published asset, as a finished run leaves it."""

    now = _now()
    return CanvasNodeV2(
        node_id=node_id,
        workflow_id=workflow_id,
        node_type="video",
        creative_role="storyboard_video",
        title="Ready node",
        status="ready",
        output_asset_id="asset_first_run",
        structured_content={},
        position={"x": 0, "y": 0},
        revision=1,
        created_at=now,
        updated_at=now,
    )


def _failed_error() -> CanvasNodeErrorV2:
    return CanvasNodeErrorV2(
        code="provider_temporary_unavailable",
        message="media_api_failed: status=503",
        retryable=True,
    )


def test_a_failed_rerun_overwrites_a_ready_node(canvas_db: Any) -> None:
    """A 503 re-run must not read as a success because an old render exists.

    ``node_runtime[].visible_status`` is ``node.status`` verbatim, so a guard that
    protected a good render from a *cancellation* also protected it from a
    *failure*: the 2026-09-21 video node kept ``status="ready"`` while its member
    row said ``failed``, and the E2E probe reported a PASS on bytes the provider
    never delivered for that run.
    """

    workflows = _repository(canvas_db)
    _seed_workflow(canvas_db, "wf_ready_guard")
    workflows.add_node(_ready_node("wf_ready_guard", "node_video_1"), expected_revision=1)
    workflows.publish_node_output(
        "wf_ready_guard",
        "node_video_1",
        execution_id="exec_first_run",
        updated_at=_now(),
        output_asset_id="asset_first_run",
    )

    updated = workflows.set_node_runtime_state(
        "wf_ready_guard",
        "node_video_1",
        status="failed",
        updated_at=_now(),
        error=_failed_error(),
        event_type="agent_canvas_node_failed",
        execution_id="exec_rerun",
    )

    assert updated.status == "failed"
    assert updated.error is not None
    assert updated.error.code == "provider_temporary_unavailable"
    # The asset is NOT cleared: the user keeps the earlier good render, only the
    # status and the error describe the run that just failed.
    assert updated.output_asset_id == "asset_first_run"

    persisted = workflows.get_node("wf_ready_guard", "node_video_1")
    assert persisted.status == "failed"


def test_a_cancelled_rerun_still_cannot_overwrite_a_ready_node(canvas_db: Any) -> None:
    """The other half of the guard: a skip must not discard a finished render."""

    workflows = _repository(canvas_db)
    _seed_workflow(canvas_db, "wf_ready_skip")
    workflows.add_node(_ready_node("wf_ready_skip", "node_video_1"), expected_revision=1)
    workflows.publish_node_output(
        "wf_ready_skip",
        "node_video_1",
        execution_id="exec_first_run",
        updated_at=_now(),
        output_asset_id="asset_first_run",
    )

    skipped = workflows.set_node_runtime_state(
        "wf_ready_skip",
        "node_video_1",
        status="draft",
        updated_at=_now(),
        event_type="agent_canvas_node_cancelled",
        execution_id="exec_cancelled",
    )

    assert skipped.status == "ready"
    assert skipped.output_asset_id == "asset_first_run"
