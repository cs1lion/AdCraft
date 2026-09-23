"""Programmatic Alembic schema bootstrap for V2 persistence."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.persistence.database import V2Database
from app.persistence.errors import V2PersistenceError

_schema_logger = logging.getLogger(__name__)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI_PATH = _REPOSITORY_ROOT / "alembic.ini"
_ALEMBIC_SCRIPT_LOCATION = _REPOSITORY_ROOT / "alembic"


def _alembic_config(database: V2Database) -> Config:
    config = Config(str(_ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(_ALEMBIC_SCRIPT_LOCATION))
    config.set_main_option(
        "sqlalchemy.url",
        database.engine.url.render_as_string(hide_password=False),
    )
    return config


def _schema_error() -> V2PersistenceError:
    return V2PersistenceError(
        "v2_persistence_schema_failed",
        "V2 persistence schema bootstrap failed.",
        stage="schema",
    )


def upgrade_v2_schema(database: V2Database) -> str:
    """Upgrade an explicit V2 database to the Alembic head revision."""

    try:
        command.upgrade(_alembic_config(database), "head")
        revision = current_v2_schema_revision(database)
    except V2PersistenceError:
        raise
    except Exception as error:
        raise _schema_error() from error

    if revision is None:
        raise _schema_error()
    return revision


def current_v2_schema_revision(database: V2Database) -> str | None:
    """Return the current Alembic revision for an explicit V2 database."""

    try:
        with database.engine.connect() as connection:
            if not inspect(connection).has_table("alembic_version"):
                return None
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    except Exception as error:
        raise _schema_error() from error


_MAX_REPORTED_DRIFT_ITEMS = 20


def verify_v2_schema(database: V2Database) -> None:
    """Fail fast when the on-disk schema drifts from the SQLAlchemy models.

    The alembic revision marker alone is not sufficient: partial restores and
    out-of-band edits can leave the database stamped at head while tables,
    columns, or FK targets disagree with the models.  That drift otherwise
    surfaces only as opaque runtime failures in the scheduler and result-commit
    paths (missing tables/columns, FK targets pointing at renamed temp tables),
    and -- for a NOT NULL column the models no longer declare -- as a rejected
    INSERT on every write to that table.
    """

    from app.persistence.models import Base

    try:
        with database.engine.connect() as connection:
            inspector = inspect(connection)
            actual_tables = set(inspector.get_table_names())
            missing_tables: list[str] = []
            missing_columns: list[str] = []
            # A column the models do not declare is drift too, but only the
            # NOT NULL ones without a default can actually break a write: the
            # repository INSERTs name every model column explicitly, so SQLite
            # rejects the statement with a NOT NULL violation naming a column
            # nothing in the code knows about.  That is exactly how
            # ``agent_canvas_bindings.required`` survived its own retirement
            # migration (20260903_05) and turned every binding create into a
            # 503, so report it instead of letting it resurface as an opaque
            # per-request failure.  Nullable extras are left alone: they are
            # harmless and an out-of-band annotation is not ours to delete.
            unexpected_not_null_columns: list[str] = []
            for table in Base.metadata.sorted_tables:
                if table.name not in actual_tables:
                    missing_tables.append(table.name)
                    continue
                actual_columns = {
                    column["name"]: column
                    for column in inspector.get_columns(table.name)
                }
                model_columns = {column.name for column in table.columns}
                missing_columns.extend(
                    f"{table.name}.{column.name}"
                    for column in table.columns
                    if column.name not in actual_columns
                )
                unexpected_not_null_columns.extend(
                    f"{table.name}.{name}"
                    for name, column in sorted(actual_columns.items())
                    if name not in model_columns
                    and not column["nullable"]
                    and column["default"] is None
                )
            dangling_foreign_keys = []
            row_level_violations = []
            for table_name in sorted(actual_tables):
                if table_name.startswith("sqlite_"):
                    continue
                for fk in connection.exec_driver_sql(
                    f"PRAGMA foreign_key_list({table_name})"
                ):
                    if fk[2] not in actual_tables:
                        dangling_foreign_keys.append(
                            f"{table_name}.{fk[1]} -> {fk[2]}"
                        )
                # Row-level orphans (e.g. rows left by cancelled executions) are
                # data hygiene, not schema drift: the runtime does not enforce
                # FKs, so report them without blocking startup.
                row_level_violations.extend(
                    f"{table_name} rowid={row[1]} -> {row[2]}"
                    for row in connection.exec_driver_sql(
                        f"PRAGMA foreign_key_check({table_name})"
                    )
                )
    except V2PersistenceError:
        raise
    except Exception as error:
        raise _schema_error() from error

    problems: dict[str, list[str]] = {}
    if missing_tables:
        problems["missing_tables"] = missing_tables
    if missing_columns:
        problems["missing_columns"] = missing_columns
    if unexpected_not_null_columns:
        problems["unexpected_not_null_columns"] = unexpected_not_null_columns
    if dangling_foreign_keys:
        problems["dangling_foreign_keys"] = dangling_foreign_keys
    if row_level_violations:
        _schema_logger.warning(
            "V2 database has %d orphan row reference(s) (data hygiene, not "
            "blocking): %s",
            len(row_level_violations),
            "; ".join(row_level_violations[:_MAX_REPORTED_DRIFT_ITEMS]),
        )
    if not problems:
        return

    bounded = {
        kind: entries[:_MAX_REPORTED_DRIFT_ITEMS] for kind, entries in problems.items()
    }
    raise V2PersistenceError(
        "v2_persistence_schema_drift",
        "V2 database schema drifted from the code models.",
        stage="schema",
        details={"schema_drift": bounded},
    )
