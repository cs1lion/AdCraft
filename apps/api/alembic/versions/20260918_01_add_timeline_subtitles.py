"""Add subtitle authoring columns and burn-in flag (ADR 0007 Phase 3.3).

Adds:
- timelines.subtitle_burn_in (user export toggle; default on)
- timeline_clips.subtitle_text (cue text for subtitle-track clips)
- timeline_clips.subtitle_style_json (per-cue font/size/colour/position)

Also widens the transition CHECK constraints to include 'slide', which the
3.2 transition editor accepts but the original constraints omitted.

Every change is guarded so development databases that received any of it
ad-hoc upgrade cleanly.

Revision ID: 20260918_01
Revises: 20260917_02
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260918_01"
down_revision = "20260917_02"
branch_labels = None
depends_on = None


_TRANSITION_TYPES = "('fade','dissolve','wipe','slide')"


def _has_column(bind, table: str, column: str) -> bool:
    columns = {item["name"] for item in sa.inspect(bind).get_columns(table)}
    return column in columns


def _constraint_text(bind, table: str, name: str) -> str | None:
    for constraint in sa.inspect(bind).get_check_constraints(table):
        if constraint.get("name") == name:
            return constraint.get("sql_text")
    return None


def _add_timeline_burn_in() -> None:
    bind = op.get_bind()
    if _has_column(bind, "timelines", "subtitle_burn_in"):
        return
    with op.batch_alter_table("timelines") as batch:
        batch.add_column(
            sa.Column(
                "subtitle_burn_in",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def _add_clip_subtitle_columns() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("timeline_clips") as batch:
        if not _has_column(bind, "timeline_clips", "subtitle_text"):
            batch.add_column(sa.Column("subtitle_text", sa.Text(), nullable=True))
        if not _has_column(bind, "timeline_clips", "subtitle_style_json"):
            batch.add_column(
                sa.Column("subtitle_style_json", sa.Text(), nullable=True)
            )


def _widen_transition_constraints() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("timeline_clips") as batch:
        for edge in ("in", "out"):
            name = f"ck_timeline_clips_transition_{edge}_type"
            text = _constraint_text(bind, "timeline_clips", name)
            if text is not None and "slide" not in text:
                batch.drop_constraint(name, type_="check")
                batch.create_check_constraint(
                    name,
                    f"transition_{edge}_type IS NULL OR transition_{edge}_type IN "
                    f"{_TRANSITION_TYPES}",
                )


def upgrade() -> None:
    _add_timeline_burn_in()
    _add_clip_subtitle_columns()
    _widen_transition_constraints()


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("timeline_clips") as batch:
        for edge in ("in", "out"):
            name = f"ck_timeline_clips_transition_{edge}_type"
            text = _constraint_text(bind, "timeline_clips", name)
            if text is not None and "slide" in text:
                batch.drop_constraint(name, type_="check")
                batch.create_check_constraint(
                    name,
                    f"transition_{edge}_type IS NULL OR transition_{edge}_type IN "
                    "('fade','dissolve','wipe')",
                )
        if _has_column(bind, "timeline_clips", "subtitle_style_json"):
            batch.drop_column("subtitle_style_json")
        if _has_column(bind, "timeline_clips", "subtitle_text"):
            batch.drop_column("subtitle_text")
    if _has_column(bind, "timelines", "subtitle_burn_in"):
        with op.batch_alter_table("timelines") as batch:
            batch.drop_column("subtitle_burn_in")
