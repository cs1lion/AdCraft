"""Add ducking_json to timelines (ADR 0007 Phase 2).

Persists the user-tuned TimelineDuckingConfigV1 (sidechain auto-ducking
parameters). NULL means the export adapter applies renderer defaults
automatically whenever both voice and BGM clips are present.

The add is guarded with a column-existence check so development databases
that already received the column upgrade cleanly.

Revision ID: 20260917_02
Revises: 20260917_01
Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260917_02"
down_revision = "20260917_01"
branch_labels = None
depends_on = None


def _has_ducking_column(bind) -> bool:
    columns = {column["name"] for column in sa.inspect(bind).get_columns("timelines")}
    return "ducking_json" in columns


def upgrade() -> None:
    bind = op.get_bind()
    if _has_ducking_column(bind):
        return
    with op.batch_alter_table("timelines") as batch:
        batch.add_column(sa.Column("ducking_json", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_ducking_column(bind):
        return
    with op.batch_alter_table("timelines") as batch:
        batch.drop_column("ducking_json")
