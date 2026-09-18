"""Add per-clip volume automation envelope (ADR 0007 Phase 3.4).

Adds timeline_clips.volume_keyframes_json, a JSON list of
``{"time_seconds": float, "value": 0..1}`` points measured from the start
of the clip. NULL or an empty list means a flat (unautomated) clip.

The change is guarded so development databases that received the column
ad-hoc upgrade cleanly.

Revision ID: 20260918_02
Revises: 20260918_01
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260918_02"
down_revision = "20260918_01"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    columns = {item["name"] for item in sa.inspect(bind).get_columns(table)}
    return column in columns


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "timeline_clips", "volume_keyframes_json"):
        return
    with op.batch_alter_table("timeline_clips") as batch:
        batch.add_column(sa.Column("volume_keyframes_json", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "timeline_clips", "volume_keyframes_json"):
        with op.batch_alter_table("timeline_clips") as batch:
            batch.drop_column("volume_keyframes_json")
