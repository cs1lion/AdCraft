"""Self-healing recovery for snapshot-less prompt-preparation dispatches.

A direct or legacy Node writer can enqueue a prompt-preparation dispatch
without a frozen ``StageAuthoringContextV1`` snapshot, and reconcile
successors created from a snapshot-less row inherit the gap.  Instead of
letting the bounded worker fail closed on the very first attempt, the
production worker rebuilds the context from current workflow state and
persists it exactly once.  These tests lock that loop: repair, prepare,
and evidence rebuild.  A real workflow without a guidance session
(free-authoring canvas) is synthesized from the node and its requirement
ledger; unknown workflows and ledgeless workflow shells stay fail-closed.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import insert, update

from app.persistence.agent_canvas_conversation_repository import (
    AgentCanvasConversationRepository,
)
from app.persistence.agent_canvas_prompt_preparation_dispatch_repository import (
    AgentCanvasPromptPreparationDispatchRepository,
    normalize_queued_node,
)
from app.persistence.agent_canvas_requirement_repository import AgentCanvasRequirementRepository
from app.persistence.agent_canvas_repository import AgentCanvasWorkflowRepository
from app.persistence.database import create_v2_database
from app.persistence.errors import V2PersistenceError
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasConversationRow,
    AgentCanvasCreativeMemoryRow,
    AgentCanvasNodeRow,
    AgentCanvasWorkflowRow,
)
from app.persistence.project_repository import ProjectRepository
from app.persistence.schema import upgrade_v2_schema
from app.schemas.agent_canvas import CanvasNodeV2
from app.schemas.agent_canvas_creative_session import (
    CreativeElementDecisionV2,
    CreativeGoalV2,
)
from app.schemas.agent_canvas_progressive_authoring import StageAuthoringContextV1
from app.schemas.agent_canvas_prompt_preparation import NodePromptPreparationV1
from app.schemas.workflow_v2_projects import ProjectCreate
from app.services.agent_canvas_prompt_context_rebuilder import PromptContextRebuilder
from app.services.agent_canvas_prompt_preparation import NodePromptPreparationService
from app.services.agent_canvas_prompt_preparation_worker import (
    AgentCanvasPromptPreparationWorker,
)

pytestmark = [pytest.mark.integration]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _queued_script_node(
    workflow_id: str,
    *,
    recipe_id: str | None = None,
    now: datetime | None = None,
) -> CanvasNodeV2:
    timestamp = now or _now()
    preparation = NodePromptPreparationV1(
        status="queued",
        operation_id=None,
        attempt_no=0,
        context_snapshot_id=None,
        prompt_digest=None,
        error=None,
        updated_at=timestamp,
    )
    metadata: dict[str, Any] = {}
    if recipe_id is not None:
        metadata["prompt_recipe_id"] = recipe_id
    return CanvasNodeV2(
        node_id=f"node_{uuid4().hex[:24]}",
        workflow_id=workflow_id,
        node_type="script",
        creative_role="script",
        title="Self-heal script node",
        status="draft",
        execution_mode="generative",
        structured_content={"content": "One shot: a product in motion."},
        metadata=metadata,
        position={"x": 0, "y": 0},
        revision=1,
        prompt_preparation=preparation,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _node_values(node: CanvasNodeV2) -> dict[str, Any]:
    """Mirror ``_node_values`` in the workflow repository for one Node row."""

    return {
        "node_id": node.node_id,
        "workflow_id": node.workflow_id,
        "node_type": node.node_type,
        "creative_role": node.creative_role,
        "role_contract_version": node.role_contract_version,
        "title": node.title,
        "status": node.status,
        "execution_mode": node.execution_mode,
        "summary_prompt": node.summary_prompt,
        "generation_prompt": node.generation_prompt,
        "structured_content_json": json.dumps(node.structured_content, ensure_ascii=True),
        "model_selection_mode": node.model_selection_mode,
        "model_ref": node.model_ref,
        "parameters_json": json.dumps(node.parameters, ensure_ascii=True),
        "metadata_json": json.dumps(node.metadata, ensure_ascii=True),
        "parameter_provenance_json": json.dumps(
            {
                field: provenance.model_dump(mode="json")
                for field, provenance in node.parameter_provenance.items()
            },
            ensure_ascii=True,
        ),
        "prompt_context_snapshot_id": node.prompt_context_snapshot_id,
        "output_asset_id": node.output_asset_id,
        "position_x": node.position.x,
        "position_y": node.position.y,
        "revision": node.revision,
        "error_json": node.error.model_dump_json() if node.error is not None else None,
        "prompt_preparation_json": node.prompt_preparation.model_dump_json(),
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
    }


def _seed_workflow(
    database: Any,
    *,
    workflow_id: str,
    project_id: str,
    node: CanvasNodeV2,
    now: datetime,
) -> None:
    """Register one project, workflow shell, and node without outbox rows.

    Mirrors ``create_empty`` minus the idempotency/replay plumbing, and
    leaves preparation identity creation to the dispatch repository.
    """

    iso = now.isoformat()
    project = ProjectCreate(
        project_id=project_id,
        name="Self-heal project",
        created_at=iso,
        updated_at=iso,
    )
    projects = ProjectRepository(database)
    requirements = AgentCanvasRequirementRepository(database)
    with database.engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            projects.insert_in_transaction(connection, project)
            connection.execute(
                insert(AgentCanvasWorkflowRow).values(
                    workflow_id=workflow_id,
                    project_id=project_id,
                    workflow_schema_version=2,
                    canvas_model="agent_canvas_v1",
                    revision=1,
                    layout_revision=1,
                    created_at=iso,
                    updated_at=iso,
                )
            )
            initialized = requirements.initialize_in_transaction(
                connection,
                workflow_id=workflow_id,
                created_at=iso,
            )
            # The canonical production duration is a mandatory Script
            # parameter; a bare ledger leaves the compiler unable to name a
            # prompt, so pin one for the self-heal node to proceed.
            _append_duration_control_in_transaction(
                connection,
                requirements,
                workflow_id,
                initialized.revision_no,
                iso,
            )
            connection.execute(
                insert(AgentCanvasConversationRow).values(
                    conversation_id=f"conversation_{workflow_id}",
                    workflow_id=workflow_id,
                    created_at=iso,
                    updated_at=iso,
                )
            )
            connection.execute(
                insert(AgentCanvasCreativeMemoryRow).values(
                    workflow_id=workflow_id,
                    creative_goal="",
                    target_audience="",
                    duration_format="",
                    approved_style_summary="",
                    approved_node_ids_json="{}",
                    open_questions_json="[]",
                    deferred_topics_json="[]",
                    rejection_notes_json="[]",
                    conversation_summary="",
                    summary_through_sequence_no=0,
                    memory_revision=0,
                    created_at=iso,
                    updated_at=iso,
                )
            )
            connection.execute(insert(AgentCanvasNodeRow).values(_node_values(node)))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def _append_duration_control_in_transaction(
    connection: Any,
    requirements: Any,
    workflow_id: str,
    expected_revision_no: int,
    created_at: str,
) -> None:
    """Append one canonical production duration inside the caller's transaction."""

    from app.schemas.agent_canvas_requirements import (
        DurationSecondsControlV1,
        RequirementLedgerV1,
    )

    current = requirements.get_current_in_transaction(connection, workflow_id)
    ledger = current.ledger
    updated = RequirementLedgerV1(
        schema_version=ledger.schema_version,
        hard_controls=(
            *ledger.hard_controls,
            DurationSecondsControlV1(
                source_kind="manual_edit",
                source_text="Self-heal fixture duration",
                created_revision_no=expected_revision_no + 1,
                control="duration_seconds",
                value=30.0,
            ),
        ),
        active_directives=ledger.active_directives,
        element_presence=ledger.element_presence,
        character_occurrences=ledger.character_occurrences,
        unresolved_conflicts=ledger.unresolved_conflicts,
    )
    requirements.append_in_transaction(
        connection,
        workflow_id=workflow_id,
        expected_revision_no=expected_revision_no,
        next_ledger=updated,
        source_kind="manual_edit",
        created_at=created_at,
    )


@pytest.fixture
def canvas_db(tmp_path: Path) -> Any:
    data_dir = tmp_path / "data"
    (data_dir / "v2").mkdir(parents=True)
    database = create_v2_database(data_dir)
    upgrade_v2_schema(database)
    yield database
    database.dispose()


def _repositories(canvas_db: Any) -> dict[str, Any]:
    database = canvas_db
    events = EventRepository(database)
    return {
        "workflows": AgentCanvasWorkflowRepository(database, ProjectRepository(database), events),
        "conversations": AgentCanvasConversationRepository(database, events),
        "requirements": AgentCanvasRequirementRepository(database),
        "dispatches": AgentCanvasPromptPreparationDispatchRepository(database, events),
    }


def _seed_guidance_session(repos: dict[str, Any], workflow_id: str) -> None:
    element_decision = CreativeElementDecisionV2(
        element_kind="product",
        presence="include",
        authority="agent",
        source="delegated_to_agent",
    )
    repos["conversations"].create_guidance_session(
        workflow_id,
        goal=CreativeGoalV2(
            requested_output="script", delivery_scope="draft", summary="Self-heal goal"
        ),
        element_decisions=(element_decision,),
        active_style_skill_run_id=None,
    )


def _enqueue_snapshotless(repos: dict[str, Any], node: CanvasNodeV2, *, now: datetime) -> None:
    """Register one queued dispatch through the repository, without context.

    Mirrors the direct-node writer path: the persisted Node row and its
    derived operation identity must stay in lock-step with the outbox row,
    so the operation id is computed once and written to both.
    """

    dispatches = repos["dispatches"]
    normalized = normalize_queued_node(node, bindings=(), context_digest=None)
    operation_id = normalized.prompt_preparation.operation_id
    assert operation_id
    persisted_preparation = normalized.prompt_preparation.model_copy(
        update={
            "operation_id": operation_id,
            "context_snapshot_id": None,
        }
    )
    persisted_node = normalized.model_copy(update={"prompt_preparation": persisted_preparation})
    with dispatches.database.engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            connection.execute(
                update(AgentCanvasNodeRow)
                .where(
                    AgentCanvasNodeRow.node_id == node.node_id,
                    AgentCanvasNodeRow.workflow_id == node.workflow_id,
                )
                .values(
                    prompt_preparation_json=persisted_preparation.model_dump_json(),
                    metadata_json=json.dumps(node.metadata, ensure_ascii=True),
                )
            )
            dispatches.ensure_for_node_in_transaction(
                connection,
                persisted_node,
                now=now,
            )
            _advance_workflow_revision(connection, node.workflow_id, now=now)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def _advance_workflow_revision(connection: Any, workflow_id: str, *, now: datetime) -> None:
    result = connection.execute(
        update(AgentCanvasWorkflowRow)
        .where(AgentCanvasWorkflowRow.workflow_id == workflow_id)
        .values(revision=AgentCanvasWorkflowRow.revision + 1, updated_at=now.isoformat())
    )
    assert result.rowcount == 1


def _rebuilder(repos: dict[str, Any]) -> PromptContextRebuilder:
    return PromptContextRebuilder(
        workflows=repos["workflows"],
        conversations=repos["conversations"],
        requirements=repos["requirements"],
        documents=None,
    )


def _worker(
    repos: dict[str, Any], *, worker_id: str, clock: Any
) -> AgentCanvasPromptPreparationWorker:
    dispatches = repos["dispatches"]
    preparation_service = NodePromptPreparationService(repos["workflows"])
    rebuilder = _rebuilder(repos)
    workflows = repos["workflows"]
    return AgentCanvasPromptPreparationWorker(
        dispatches,
        prepare=lambda item, context: preparation_service.prepare(
            item.workflow_id,
            item.node_id,
            operation_id=item.operation_id,
            context=context,
        ),
        context_repairer=lambda item, loaded: rebuilder.build(item.workflow_id, loaded),
        node_loader=workflows.get_node,
        worker_id=worker_id,
        stale_dispatch_reconciler=(
            lambda item, owner, generation, reason, timestamp: (
                workflows.reconcile_stale_prompt_preparation_dispatch(
                    item,
                    worker_id=owner,
                    lease_generation=generation,
                    reason=reason,
                    now=timestamp,
                )
            )
        ),
        clock=clock,
    )


def test_worker_repairs_snapshotless_dispatch_and_rebuilds_assertion_evidence(
    canvas_db: Any,
) -> None:
    """A direct-node script draft heals without any operator intervention."""

    repos = _repositories(canvas_db)
    now = _now()
    workflow_id = "adwf_v2_selfheal_main"
    node = _queued_script_node(workflow_id, recipe_id="recipe_selfheal", now=now)

    _seed_workflow(
        canvas_db,
        workflow_id=workflow_id,
        project_id="proj_selfheal_main",
        node=node,
        now=now,
    )
    _seed_guidance_session(repos, workflow_id)
    _enqueue_snapshotless(repos, node, now=now)

    dispatches = repos["dispatches"]
    dispatch = dispatches.get_current_for_node(workflow_id, node.node_id)
    assert dispatch is not None
    assert dispatch.context_json == {}
    assert dispatch.context_digest is None

    cycle = _worker(repos, worker_id="selfheal-main-worker", clock=lambda: now).run_once()

    if cycle.completed != 1:
        terminal = dispatches.get(dispatch.dispatch_id)
        healed_node = repos["workflows"].get_node(workflow_id, node.node_id)
        raise AssertionError(
            "self-heal cycle did not complete: "
            f"cycle={cycle} terminal={terminal} "
            f"node={healed_node.prompt_preparation}"
        )
    assert cycle.completed == 1
    assert cycle.failed == 0
    repaired = dispatches.get(dispatch.dispatch_id)
    assert repaired.status == "completed"
    assert repaired.context_json
    assert repaired.context_digest

    healed = repos["workflows"].get_node(workflow_id, node.node_id)
    assert healed.prompt_preparation.status in {"ready", "working"}
    assert healed.prompt_preparation.assertion_evidence is not None
    assert healed.prompt_preparation.assertion_evidence.evidence_digest


def test_worker_self_heals_snapshotless_dispatch_without_guidance_session(
    canvas_db: Any,
) -> None:
    """A real session-less workflow heals via a ledger-backed synthesized context."""

    repos = _repositories(canvas_db)
    now = _now()
    workflow_id = "adwf_v2_selfheal_no_session"
    node = _queued_script_node(workflow_id, now=now)

    _seed_workflow(
        canvas_db,
        workflow_id=workflow_id,
        project_id="proj_selfheal_no_session",
        node=node,
        now=now,
    )
    _enqueue_snapshotless(repos, node, now=now)

    dispatches = repos["dispatches"]
    dispatch = dispatches.get_current_for_node(workflow_id, node.node_id)
    assert dispatch is not None

    cycle = _worker(repos, worker_id="selfheal-no-session-worker", clock=lambda: now).run_once()

    assert cycle.completed == 1
    assert cycle.failed == 0
    repaired = dispatches.get(dispatch.dispatch_id)
    assert repaired.status == "completed"
    assert repaired.context_digest is not None
    # The frozen snapshot is a synthesized free-authoring context but it
    # must carry the authoritative ledger facts so Script compilation can
    # name the canonical production duration.
    assert repaired.context_json["session_id"] == f"free_authoring_{workflow_id}"
    assert repaired.context_json["requirement_facts"]["duration_seconds"] == pytest.approx(30.0)

    healed = repos["workflows"].get_node(workflow_id, node.node_id)
    assert healed.prompt_preparation.status in {"ready", "working"}
    assert healed.prompt_preparation.assertion_evidence is not None
    assert healed.prompt_preparation.assertion_evidence.evidence_digest


def test_rebuilder_synthesizes_free_authoring_context_from_ledger(
    canvas_db: Any,
) -> None:
    """A session-less workflow rebuilds deterministically from node and ledger."""

    repos = _repositories(canvas_db)
    now = _now()
    workflow_id = "adwf_v2_selfheal_free_authoring"
    node = _queued_script_node(workflow_id, now=now)

    _seed_workflow(
        canvas_db,
        workflow_id=workflow_id,
        project_id="proj_selfheal_free_authoring",
        node=node,
        now=now,
    )

    rebuilder = _rebuilder(repos)
    loaded = repos["workflows"].get_node(workflow_id, node.node_id)
    first = rebuilder.build(workflow_id, loaded)
    second = rebuilder.build(workflow_id, loaded)

    assert first is not None
    assert first == second
    assert first.session_id == f"free_authoring_{workflow_id}"
    assert first.session_revision == 1
    assert first.stage == "narrative_direction"
    assert first.internal_skill_ref.startswith("agent/skills/")
    assert first.requirement_facts["duration_seconds"] == pytest.approx(30.0)


def test_rebuilder_fails_closed_for_unknown_and_ledgeless_workflows(
    canvas_db: Any,
) -> None:
    """No workflow shell or no requirement ledger means no synthesized context."""

    repos = _repositories(canvas_db)
    now = _now()

    # A fabricated workflow id with a node-shaped argument must never
    # produce a snapshot: the workflow shell is the authority gate.
    assert (
        _rebuilder(repos).build("adwf_v2_unknown", _queued_script_node("adwf_v2_unknown", now=now))
        is None
    )

    # A real workflow shell without a requirement ledger stays fail-closed
    # because no authoritative hard controls back the synthesized snapshot.
    workflow_id = "adwf_v2_selfheal_no_ledger"
    project_id = "proj_selfheal_no_ledger"
    iso = now.isoformat()
    projects = ProjectRepository(canvas_db)
    with canvas_db.engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            projects.insert_in_transaction(
                connection,
                ProjectCreate(
                    project_id=project_id,
                    name="Self-heal ledgeless project",
                    created_at=iso,
                    updated_at=iso,
                ),
            )
            connection.execute(
                insert(AgentCanvasWorkflowRow).values(
                    workflow_id=workflow_id,
                    project_id=project_id,
                    workflow_schema_version=2,
                    canvas_model="agent_canvas_v1",
                    revision=1,
                    layout_revision=1,
                    created_at=iso,
                    updated_at=iso,
                )
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    assert _rebuilder(repos).build(workflow_id, _queued_script_node(workflow_id, now=now)) is None


def test_rebuilder_is_deterministic_for_guided_session(canvas_db: Any) -> None:
    """The same guided workflow state names one stable snapshot every time."""

    repos = _repositories(canvas_db)
    now = _now()
    workflow_id = "adwf_v2_selfheal_deterministic"
    node = _queued_script_node(workflow_id, now=now)

    _seed_workflow(
        canvas_db,
        workflow_id=workflow_id,
        project_id="proj_selfheal_deterministic",
        node=node,
        now=now,
    )
    _seed_guidance_session(repos, workflow_id)

    rebuilder = _rebuilder(repos)
    first = rebuilder.build(workflow_id, repos["workflows"].get_node(workflow_id, node.node_id))
    second = rebuilder.build(workflow_id, repos["workflows"].get_node(workflow_id, node.node_id))

    assert first is not None
    assert first == second
    assert first.internal_skill_ref.startswith("agent/skills/")

    from app.schemas.agent_canvas_prompt_preparation_dispatch import (
        detached_context_payload,
    )
    from app.services.agent_canvas_prompt_preparation import context_digest

    payload_a, digest_a = detached_context_payload(first.model_dump(mode="json"))
    payload_b, digest_b = detached_context_payload(second.model_dump(mode="json"))
    assert payload_a == payload_b
    assert digest_a == digest_b
    assert digest_a == context_digest(first)


def test_repair_context_in_lease_only_touches_snapshotless_rows(canvas_db: Any) -> None:
    """A row that already owns a snapshot is never rewritten."""

    repos = _repositories(canvas_db)
    now = _now()
    workflow_id = "adwf_v2_selfheal_repair_guard"
    node = _queued_script_node(workflow_id, now=now)

    _seed_workflow(
        canvas_db,
        workflow_id=workflow_id,
        project_id="proj_selfheal_repair_guard",
        node=node,
        now=now,
    )
    _seed_guidance_session(repos, workflow_id)
    _enqueue_snapshotless(repos, node, now=now)

    dispatches = repos["dispatches"]
    dispatch = dispatches.get_current_for_node(workflow_id, node.node_id)
    assert dispatch is not None
    claimed, _terminalized = dispatches.claim_due_with_terminalized(
        worker_id="repair-guard-worker", now=now, batch_limit=1
    )
    assert len(claimed) == 1
    lease = dispatches.get(claimed[0].dispatch_id)
    assert lease.lease_owner == "repair-guard-worker"

    context = _rebuilt_context(repos, workflow_id, node)
    repaired = dispatches.repair_context_in_lease(
        dispatch.dispatch_id,
        worker_id="repair-guard-worker",
        lease_generation=lease.lease_generation,
        context=context.model_dump(mode="json"),
        now=now,
    )
    assert repaired.context_digest is not None

    idempotent = dispatches.repair_context_in_lease(
        dispatch.dispatch_id,
        worker_id="repair-guard-worker",
        lease_generation=lease.lease_generation,
        context=context.model_dump(mode="json"),
        now=now,
    )
    assert idempotent.context_digest == repaired.context_digest

    with pytest.raises(V2PersistenceError) as conflict:
        dispatches.repair_context_in_lease(
            dispatch.dispatch_id,
            worker_id="stale-worker",
            lease_generation=0,
            context=context.model_dump(mode="json"),
            now=now,
        )
    assert conflict.value.code == "prompt_preparation_dispatch_lease_stale"


def _rebuilt_context(
    repos: dict[str, Any],
    workflow_id: str,
    node: CanvasNodeV2,
) -> StageAuthoringContextV1:
    context = _rebuilder(repos).build(
        workflow_id, repos["workflows"].get_node(workflow_id, node.node_id)
    )
    assert context is not None
    return context
