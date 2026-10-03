"""Durable result commit preserves authoring content and lands run outputs.

Locks the ADR 0017-era fix to the terminal result authority: a media run's
executor structured content (scene-3d's generated SceneScript, previs
trajectory, consistency reports, …) must reach the node through
``AgentCanvasResultCommitRepository.commit`` — merged with what the author
already had on the node (drafts, dialogue lines, director takes, published
previs clips), never replacing it. Mutation check: reverting the merge to a
wholesale column replace makes the authoring-preserved assertion below red;
dropping the pass-through in ``agent_canvas_output_preparation`` makes the
scene-script-landed assertion red.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert

from app.persistence.asset_library_repository import V2AssetLibraryRepository
from app.persistence.agent_canvas_result_commit_repository import (
    AgentCanvasResultCommitRepository,
)
from app.persistence.database import create_v2_database
from app.persistence.event_repository import EventRepository
from app.persistence.models import (
    AgentCanvasExecutionMemberRow,
    AgentCanvasExecutionRow,
    AgentCanvasNodeLeaseRow,
    AgentCanvasNodeRow,
    AgentCanvasWorkflowRow,
)
from app.persistence.project_repository import ProjectRepository
from app.persistence.schema import upgrade_v2_schema
from app.schemas.agent_canvas_runtime_authority import (
    CanvasExecutionResultCommitCommandV2,
    PreparedContentObjectV2,
    PreparedNodeResultV2,
)
from app.schemas.workflow_v2_projects import ProjectCreate

pytestmark = pytest.mark.integration

NOW = datetime.now(timezone.utc)

#: Authoring fields an author (or the ADR 0017 publish endpoint) put on the
#: scene-3d node BEFORE the run — the commit must not destroy these.
AUTHORING_CONTENT = {
    "white_model": False,
    "dialogue_lines": [{"character_id": "hanxiao", "text": "守住气闸！"}],
    "published_previs_clips": [{"node_id": "node_clip", "shot_id": "shot_1"}],
}

#: Outputs the scene-3d executor publishes with its media bytes.
RUN_OUTPUTS = {
    "scene_script": {"scene": {"name": "静海攻防", "duration": 24.0}},
    "previs_trajectory": {"frames": [0, 120, 240]},
}


@pytest.fixture
def db(tmp_path):
    (tmp_path / "v2").mkdir()
    database = create_v2_database(tmp_path)
    upgrade_v2_schema(database)
    return database


@pytest.fixture
def repository(db):
    events = EventRepository(db)
    projects = ProjectRepository(db)
    with db.engine.begin() as connection:
        projects.insert_in_transaction(
            connection,
            ProjectCreate(
                project_id="project",
                name="Previs commit test",
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
        connection.execute(
            insert(AgentCanvasNodeRow).values(
                node_id="node_scene3d",
                workflow_id="workflow",
                node_type="scene-3d",
                creative_role="scene_3d_previs",
                role_contract_version="ad-media-role-v2",
                title="月面基地",
                status="working",
                execution_mode="generative",
                authoring_origin="user_free",
                structured_content_json=json.dumps(AUTHORING_CONTENT, ensure_ascii=False),
                parameters_json="{}",
                metadata_json="{}",
                parameter_provenance_json="{}",
                revision=1,
                position_x=100.0,
                position_y=100.0,
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            )
        )
        connection.execute(
            insert(AgentCanvasExecutionRow).values(
                execution_id="exec_1",
                workflow_id="workflow",
                scope="selected_nodes",
                status="running",
                cancel_requested=False,
                idempotency_key="idem-1",
                request_fingerprint="fp-1",
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            )
        )
        connection.execute(
            insert(AgentCanvasExecutionMemberRow).values(
                member_id="member_1",
                execution_id="exec_1",
                workflow_id="workflow",
                node_id="node_scene3d",
                member_order=0,
                state="running",
                attempt_no=0,
                updated_at=NOW.isoformat(),
            )
        )
        connection.execute(
            insert(AgentCanvasNodeLeaseRow).values(
                lease_id="lease_1",
                workflow_id="workflow",
                execution_id="exec_1",
                node_id="node_scene3d",
                owner_id="owner_1",
                generation=1,
                state="claimed",
                heartbeat_at=NOW.isoformat(),
                expires_at=(NOW + timedelta(seconds=60)).isoformat(),
            )
        )
    assets = V2AssetLibraryRepository(db)
    return AgentCanvasResultCommitRepository(db, assets, events)


def _command(*, structured_content: dict | None) -> CanvasExecutionResultCommitCommandV2:
    content = b"previs-bytes"
    digest = hashlib.sha256(json.dumps(structured_content or {}, sort_keys=True).encode()).hexdigest()
    return CanvasExecutionResultCommitCommandV2(
        workflow_id="workflow",
        execution_id="exec_1",
        member_id="member_1",
        node_id="node_scene3d",
        lease_owner_id="owner_1",
        lease_generation=1,
        logical_result_key="result-key-1",
        payload_digest=digest,
        outcome="succeeded",
        prepared_result=PreparedNodeResultV2(
            logical_result_key="result-key-1",
            payload_digest=digest,
            structured_content=structured_content,
            prepared_object=PreparedContentObjectV2(
                storage_key="v2/assets/previs.mp4",
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                media_type="video",
                mime_type="video/mp4",
                filename="previs.mp4",
                media_facts={"width": 960, "height": 540},
            ),
            asset_id="asset_previs_out",
            version_id="version_asset_previs_out",
            asset_display_name="previs",
        ),
        committed_at=NOW,
    )


def test_commit_merges_run_outputs_and_preserves_authoring(repository, db) -> None:
    receipt = repository.commit(_command(structured_content=RUN_OUTPUTS))
    assert receipt.asset_id == "asset_previs_out"

    with db.engine.connect() as connection:
        row = connection.execute(
            AgentCanvasNodeRow.__table__.select().where(
                AgentCanvasNodeRow.node_id == "node_scene3d"
            )
        ).mappings().one()
    stored = json.loads(row["structured_content_json"])
    # Run outputs landed on the node (the fix: the durable commit path used to
    # drop them entirely, leaving a scene-3d node without its SceneScript).
    assert stored["scene_script"] == RUN_OUTPUTS["scene_script"]
    assert stored["previs_trajectory"] == RUN_OUTPUTS["previs_trajectory"]
    # Authoring fields survived the merge (mutation check: replace → red).
    assert stored["white_model"] is False
    assert stored["dialogue_lines"] == AUTHORING_CONTENT["dialogue_lines"]
    assert stored["published_previs_clips"] == AUTHORING_CONTENT["published_previs_clips"]


def test_commit_without_structured_content_leaves_node_content_untouched(repository, db) -> None:
    """Asset-only commit (no executor structured content) must not blank the node."""

    receipt = repository.commit(_command(structured_content=None))
    assert receipt.asset_id is not None

    with db.engine.connect() as connection:
        row = connection.execute(
            AgentCanvasNodeRow.__table__.select().where(
                AgentCanvasNodeRow.node_id == "node_scene3d"
            )
        ).mappings().one()
    stored = json.loads(row["structured_content_json"])
    assert stored == AUTHORING_CONTENT
