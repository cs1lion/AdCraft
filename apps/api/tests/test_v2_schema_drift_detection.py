"""Schema drift must fail at bootstrap, not at the first write.

Migration 20260903_05 dropped ``agent_canvas_bindings.required`` and the model
has had no such column since.  One database still carried it as
``BOOLEAN NOT NULL`` with no default while its ``alembic_version`` was stamped
past that migration, so the DROP COLUMN never reached the file.  Every
``POST /api/v2/workflows/{id}/bindings`` then failed with
``NOT NULL constraint failed: agent_canvas_bindings.required`` -- a 503 per
request, from a cause no request could see.

``verify_v2_schema`` already checked the model -> database direction (missing
tables and columns) but not the database -> model direction, which is where
this one hid.  These tests pin both halves.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.persistence.database import create_v2_database
from app.persistence.errors import V2PersistenceError
from app.persistence.schema import upgrade_v2_schema, verify_v2_schema

TABLE = "agent_canvas_bindings"
RETIRED_COLUMN = "required"


def _database(v2_media_data_dir: Path):
    database = create_v2_database(v2_media_data_dir)
    upgrade_v2_schema(database)
    return database


def test_clean_schema_verifies(v2_media_data_dir: Path) -> None:
    database = _database(v2_media_data_dir)
    try:
        assert verify_v2_schema(database) is None
    finally:
        database.dispose()


def test_retired_not_null_column_is_reported_as_drift(v2_media_data_dir: Path) -> None:
    database = _database(v2_media_data_dir)
    try:
        with database.engine.connect() as connection:
            connection.execute(
                text(f"ALTER TABLE {TABLE} ADD COLUMN {RETIRED_COLUMN} BOOLEAN NOT NULL")
            )
            connection.commit()

        with pytest.raises(V2PersistenceError) as error:
            verify_v2_schema(database)

        assert error.value.code == "v2_persistence_schema_drift"
        drift = error.value.details["schema_drift"]
        assert "unexpected_not_null_columns" in drift
        assert any(
            entry == f"{TABLE}.{RETIRED_COLUMN}"
            for entry in drift["unexpected_not_null_columns"]
        ), drift
    finally:
        database.dispose()


def test_nullable_extra_column_is_not_drift(v2_media_data_dir: Path) -> None:
    database = _database(v2_media_data_dir)
    try:
        with database.engine.connect() as connection:
            # A nullable extra is an annotation someone else added; it cannot
            # break an INSERT that omits it, so it is not ours to reject.
            connection.execute(
                text(f"ALTER TABLE {TABLE} ADD COLUMN operator_note TEXT")
            )
            connection.commit()

        assert verify_v2_schema(database) is None
    finally:
        database.dispose()


def test_model_only_column_is_reported_as_drift(v2_media_data_dir: Path) -> None:
    database = _database(v2_media_data_dir)
    try:
        with database.engine.connect() as connection:
            connection.execute(text(f"ALTER TABLE {TABLE} DROP COLUMN enabled"))
            connection.commit()

        with pytest.raises(V2PersistenceError) as error:
            verify_v2_schema(database)

        drift = error.value.details["schema_drift"]
        assert f"{TABLE}.enabled" in drift["missing_columns"]
    finally:
        database.dispose()
