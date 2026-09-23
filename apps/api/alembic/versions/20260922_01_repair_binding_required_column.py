"""Drop the retired Binding requiredness column wherever it survived.

Revision ``20260903_05`` drops ``agent_canvas_bindings.required``, and the
model has had no such column since.  At least one database nevertheless still
carries it as ``BOOLEAN NOT NULL`` with no default while its ``alembic_version``
is stamped past ``20260903_05`` -- the revision was recorded as applied without
the DROP COLUMN ever reaching the file.  Every
``POST /api/v2/workflows/{id}/bindings`` then fails with
``NOT NULL constraint failed: agent_canvas_bindings.required``, because the
model's INSERT names all thirteen current columns and omits that one.

The repair is written idempotently so it is safe on a database that is already
correct: it inspects the live table and only drops the column if it is there.
``batch_alter_table`` recreates the table under SQLite, which is also how the
CHECK constraints and the ``source_asset_version_id`` column survive.

Revision ID: 20260922_01
Revises: 20260919_01
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_01"
down_revision = "20260919_01"
branch_labels = None
depends_on = None

_TABLE = "agent_canvas_bindings"
_COLUMN = "required"


def _columns() -> set[str]:
    bind = op.get_bind()
    rows = bind.exec_driver_sql(f"PRAGMA table_info({_TABLE})").fetchall()
    return {row[1] for row in rows}


def upgrade() -> None:
    if _COLUMN not in _columns():
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)


def downgrade() -> None:
    if _COLUMN in _columns():
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(
            sa.Column(
                _COLUMN,
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
