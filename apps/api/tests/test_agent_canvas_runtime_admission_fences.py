"""Durable cancellation and idempotency admission locks; no providers are invoked."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import insert, update

from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.agent_canvas_requirement_repository import AgentCanvasRequirementRepository
from app.persistence.agent_canvas_runtime_repository import AgentCanvasRuntimeRepository
from app.persistence.database import create_v2_database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasExecutionRow,
    AgentCanvasExecutionMemberRow,
    AgentCanvasWorkflowRow,
)
from app.persistence.project_repository import ProjectRepository
from app.persistence.schema import upgrade_v2_schema
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_runtime import CanvasRunRequestV2
from app.schemas.workflow_v2_projects import ProjectCreate
from app.services.agent_canvas_runtime import AgentCanvasRunService, DynamicCanvasScheduler

pytestmark = pytest.mark.integration
NOW = datetime.now(timezone.utc)
TTL = timedelta(seconds=60)


@pytest.fixture
def store(tmp_path):
    (tmp_path / "v2").mkdir()
    database = create_v2_database(tmp_path)
    upgrade_v2_schema(database)
    events = EventRepository(database)
    projects = ProjectRepository(database)
    workflows = AgentCanvasWorkflowRepository(database, projects, events)
    with database.engine.begin() as connection:
        projects.insert_in_transaction(
            connection,
            ProjectCreate(
                project_id="project",
                name="Fence test",
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            ),
        )
        connection.execute(
            insert(AgentCanvasWorkflowRow).values(
                workflow_id="workflow",
                project_id="project",
                workflow_schema_version=2,
                canvas_model="agent_canvas_v1",
                revision=1,
                layout_revision=1,
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            )
        )
        AgentCanvasRequirementRepository(database).initialize_in_transaction(
            connection,
            workflow_id="workflow",
            created_at=NOW.isoformat(),
        )
    node = CanvasNodeV2(
        node_id="node",
        workflow_id="workflow",
        node_type="image",
        creative_role="scene",
        title="Fence test",
        generation_prompt="An empty stage",
        status="draft",
        position={"x": 0, "y": 0},
        revision=1,
        created_at=NOW,
        updated_at=NOW,
    )
    workflows.add_node(node, expected_revision=1)
    runtime = AgentCanvasRuntimeRepository(database, events)
    yield database, workflows, runtime, events
    database.dispose()


def execution(store):
    return store[2].create_execution(
        workflow_id="workflow",
        scope="selected_nodes",
        node_ids=("node",),
        idempotency_key="legacy",
        request_fingerprint="a" * 64,
        now=NOW,
    )


def claim(runtime, execution_id):
    lease = runtime.claim_lease(
        execution_id,
        "node",
        owner_id="worker",
        now=NOW,
        ttl=TTL,
    )
    assert lease is not None
    return lease


def test_request_cancel_immediately_fences_claim_update_renew_assert_and_dispatch(store):
    _, workflows, runtime, _ = store
    run = execution(store)
    lease = claim(runtime, run.execution_id)
    runtime.request_cancel(run.execution_id, now=NOW)
    assert (
        runtime.claim_lease(
            run.execution_id,
            "node",
            owner_id="other",
            now=NOW + TTL,
            ttl=TTL,
        )
        is None
    )
    assert not runtime.update_member(
        run.execution_id,
        "node",
        state="running",
        phase="running",
        now=NOW,
    )
    assert not runtime.admit_dispatch(lease, now=NOW)
    for operation in (
        lambda: runtime.renew_lease(lease, now=NOW, ttl=TTL),
        lambda: runtime.assert_current_lease(lease, now=NOW),
    ):
        with pytest.raises(V2PersistenceError, match="ownership was lost"):
            operation()
    assert workflows.get_node("workflow", "node").status == "draft"


def test_uncancelled_dispatch_renews_and_asserts_current_lease(store):
    _, workflows, runtime, _ = store
    run = execution(store)
    lease = claim(runtime, run.execution_id)
    renewed = runtime.renew_lease(lease, now=NOW, ttl=TTL)
    runtime.assert_current_lease(renewed, now=NOW)
    assert runtime.admit_dispatch(renewed, now=NOW)
    assert runtime.list_members(run.execution_id)[0].state == "running"
    assert workflows.get_node("workflow", "node").status == "working"


def test_update_waiting_on_cancel_transaction_cannot_overwrite_cancelled_member(store):
    database, _, runtime, _ = store
    run = execution(store)
    started = Event()

    def update_member():
        started.set()
        return runtime.update_member(
            run.execution_id, "node", state="running", phase="running", now=NOW
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with database.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            connection.execute(
                update(AgentCanvasWorkflowRow)
                .where(
                    AgentCanvasWorkflowRow.workflow_id == "workflow",
                )
                .values(updated_at=NOW.isoformat())
            )
            pending = pool.submit(update_member)
            assert started.wait(timeout=5)
            # Commit cancel on the lock-holding connection. The update cannot
            # pass a stale read/check while another writer owns cancellation.
            connection.execute(
                update(AgentCanvasExecutionRow)
                .where(
                    AgentCanvasExecutionRow.execution_id == run.execution_id,
                )
                .values(cancel_requested=True)
            )
            connection.execute(
                update(AgentCanvasExecutionMemberRow)
                .where(
                    AgentCanvasExecutionMemberRow.execution_id == run.execution_id,
                )
                .values(state="cancelled", phase=None)
            )
            connection.commit()
        assert pending.result(timeout=10) is False
    assert runtime.list_members(run.execution_id)[0].state == "cancelled"


def test_concurrent_cancel_and_dispatch_have_one_atomic_order(store):
    _, workflows, runtime, events = store
    run = execution(store)
    lease = claim(runtime, run.execution_id)
    barrier = Barrier(2)

    def cancel():
        barrier.wait(timeout=5)
        runtime.request_cancel(run.execution_id, now=NOW)
        return events.max_seq("workflow")

    def admit():
        barrier.wait(timeout=5)
        return runtime.admit_dispatch(lease, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancelled = pool.submit(cancel)
        admitted = pool.submit(admit)
        cancelled.result(timeout=10)
        won = admitted.result(timeout=10)
    assert runtime.get_execution(run.execution_id).cancel_requested
    assert runtime.list_members(run.execution_id)[0].state == ("running" if won else "queued")
    assert workflows.get_node("workflow", "node").status == ("working" if won else "draft")
    assert not runtime.admit_dispatch(lease, now=NOW)
    with pytest.raises(V2PersistenceError):
        runtime.assert_current_lease(lease, now=NOW)


def test_cancel_during_prepare_never_reanimates_member_node_or_dispatches(store):
    _, workflows, runtime, _ = store
    run = execution(store)
    preparing, release = Event(), Event()
    dispatched = Mock()
    scheduler = DynamicCanvasScheduler(
        workflows,
        runtime,
        Mock(),
        Mock(),
        Mock(),
        media_publisher=Mock(),
        clock=lambda: NOW,
    )
    scheduler.compute_ready_wave = lambda _: ("node",)

    def prepare(*_):
        preparing.set()
        assert release.wait(timeout=5)
        return SimpleNamespace(
            seedance_input_audit=None,
            optional_input_omissions=(),
            model_resolution=None,
            compiled_prompt=None,
        )

    scheduler._prepare_member = prepare
    scheduler._assert_current_dependency_fence = lambda *_: None
    scheduler._execute_member_guarded = dispatched
    with ThreadPoolExecutor(max_workers=1) as pool:
        resumed = pool.submit(scheduler.resume, run.execution_id)
        assert preparing.wait(timeout=5)
        runtime.request_cancel(run.execution_id, now=NOW)
        scheduler._cancel_members("workflow", run.execution_id)
        release.set()
        resumed.result(timeout=10)
    assert runtime.get_execution(run.execution_id).status == "cancelled"
    assert runtime.list_members(run.execution_id)[0].state == "cancelled"
    assert workflows.get_node("workflow", "node").status == "draft"
    dispatched.assert_not_called()


def test_service_replays_before_revision_eligibility_and_snapshot_mutable_checks(store):
    database, workflows, runtime, events = store
    validator = Mock()
    service = AgentCanvasRunService(workflows, runtime, events, eligibility_validator=validator)
    request = CanvasRunRequestV2(scope="selected_nodes", node_ids=("node",), source_action="run")
    revision = workflows.get_workflow("workflow").revision
    first = service.start_or_extend(
        "workflow", request, idempotency_key="key", expected_revision=revision
    )
    runtime.set_execution_status(
        first.execution_id, "completed", now=NOW, event_type="execution_completed"
    )
    with database.engine.begin() as connection:
        connection.execute(
            update(AgentCanvasWorkflowRow)
            .where(
                AgentCanvasWorkflowRow.workflow_id == "workflow",
            )
            .values(revision=revision + 1)
        )
    validator.side_effect = AssertionError("Replay must not validate mutable eligibility")
    service._run_snapshots = Mock()
    service._run_snapshots.prepare_member_intents.side_effect = AssertionError(
        "Do not freeze again"
    )
    replay = service.start_or_extend(
        "workflow", request, idempotency_key="key", expected_revision=revision
    )
    assert replay.execution_id == first.execution_id
    assert replay.accepted_node_ids == first.accepted_node_ids
    assert replay.run_intent_snapshot_ids == first.run_intent_snapshot_ids
    assert len(runtime.list_executions()) == 1
    with pytest.raises(V2PersistenceError) as mismatch:
        service.start_or_extend(
            "workflow",
            CanvasRunRequestV2(scope="all_drafts", source_action="run"),
            idempotency_key="key",
            expected_revision=revision,
        )
    assert mismatch.value.code == "idempotency_conflict"
    with pytest.raises(V2PersistenceError) as owner:
        service.start_or_extend("another-workflow", request, idempotency_key="key")
    assert owner.value.code == "idempotency_conflict"


def test_concurrent_same_key_service_admission_creates_only_one_execution(store):
    _, workflows, runtime, events = store
    barrier = Barrier(2)

    def eligible(_):
        barrier.wait(timeout=5)

    service = AgentCanvasRunService(workflows, runtime, events, eligibility_validator=eligible)
    request = CanvasRunRequestV2(scope="selected_nodes", node_ids=("node",), source_action="run")
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = [
            pool.submit(service.start_or_extend, "workflow", request, idempotency_key="same-key")
            for _ in range(2)
        ]
        results = [run.result(timeout=10) for run in runs]
    assert results[0].execution_id == results[1].execution_id
    assert len(runtime.list_executions()) == 1
    assert len(runtime.list_members(results[0].execution_id)) == 1
