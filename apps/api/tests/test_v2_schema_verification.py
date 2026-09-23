"""Startup schema-verification guard.

The alembic revision marker alone cannot detect a database whose tables,
columns, or FK targets drifted from the SQLAlchemy models (partial restores,
out-of-band edits).  ``verify_v2_schema`` must fail fast with a structured
drift report instead of letting the scheduler and result-commit paths crash on
missing tables at runtime (2026-09-19 E2E failure mode).
"""

from pathlib import Path
from typing import Any

import pytest

from app.persistence.database import create_v2_database
from app.persistence.errors import V2PersistenceError
from app.persistence.schema import upgrade_v2_schema, verify_v2_schema

pytestmark = [pytest.mark.integration]


@pytest.fixture
def database(tmp_path: Path) -> Any:
    data_dir = tmp_path / "data"
    (data_dir / "v2").mkdir(parents=True)
    database = create_v2_database(data_dir)
    upgrade_v2_schema(database)
    yield database
    database.dispose()


def test_verify_accepts_fresh_upgraded_database(database: Any) -> None:
    verify_v2_schema(database)


def test_verify_detects_missing_column(database: Any) -> None:
    with database.engine.begin() as connection:
        # A column-add migration that was never applied to this database.
        connection.exec_driver_sql(
            "CREATE TABLE provider_submission_intents_probe AS SELECT 1 WHERE 0"
        )
        connection.exec_driver_sql(
            "DROP TABLE provider_submission_intents_probe"
        )
        connection.exec_driver_sql(
            "ALTER TABLE agent_canvas_provider_submission_intents "
            "DROP COLUMN frozen_model_resolution_json"
        )

    with pytest.raises(V2PersistenceError) as exc_info:
        verify_v2_schema(database)

    assert exc_info.value.code == "v2_persistence_schema_drift"
    drift = (exc_info.value.details or {}).get("schema_drift", {})
    assert any(
        entry.startswith("agent_canvas_provider_submission_intents.frozen_model_resolution_json")
        for entry in drift.get("missing_columns", [])
    )


def test_verify_detects_dangling_foreign_key_target(database: Any) -> None:
    with database.engine.begin() as connection:
        # The corruption shape found in the dev database: FK targets pointing
        # at a renamed _temp table that no longer exists.
        connection.exec_driver_sql(
            "CREATE TABLE agent_canvas_post_ready_effects_probe ("
            "effect_id TEXT PRIMARY KEY, "
            "source_commit_id TEXT NOT NULL, "
            "FOREIGN KEY(source_commit_id) REFERENCES "
            "agent_canvas_execution_result_commits_temp (commit_id))"
        )

    try:
        with pytest.raises(V2PersistenceError) as exc_info:
            verify_v2_schema(database)
        assert exc_info.value.code == "v2_persistence_schema_drift"
        drift = (exc_info.value.details or {}).get("schema_drift", {})
        assert drift.get("dangling_foreign_keys")
    finally:
        with database.engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP TABLE agent_canvas_post_ready_effects_probe"
            )
        # After removing the probe the remaining schema is consistent again.
        verify_v2_schema(database)


def test_verify_detects_missing_table(database: Any) -> None:
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE agent_canvas_result_publication_intents")

    with pytest.raises(V2PersistenceError) as exc_info:
        verify_v2_schema(database)

    assert exc_info.value.code == "v2_persistence_schema_drift"
    drift = (exc_info.value.details or {}).get("schema_drift", {})
    assert "agent_canvas_result_publication_intents" in drift.get("missing_tables", [])
