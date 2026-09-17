"""Create Timeline orchestration tables (ADR 0007) and align node type constraint.

Adds:
- timelines / timeline_tracks / timeline_clips (see app.persistence.models)
- widens ck_agent_canvas_nodes_type to include 'voice-cast', aligning the
  migration chain with the ORM model (voice-cast nodes were already produced
  by the runtime and created ad-hoc on development databases).

Creation is guarded with table-existence checks so databases that received
the tables through the one-off e2e_output/migrate_timeline_tables.py script
upgrade cleanly.

Revision ID: 20260917_01
Revises: 20260915_02
Create Date: 2026-09-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260917_01"
down_revision = "20260915_02"
branch_labels = None
depends_on = None


_NODE_TYPES_WITH_VOICE_CAST = (
    "node_type IN ('text', 'script', 'image', 'video', 'audio', "
    "'editing', 'scene-3d', 'voice-cast')"
)
_NODE_TYPES_WITHOUT_VOICE_CAST = (
    "node_type IN ('text', 'script', 'image', 'video', 'audio', "
    "'editing', 'scene-3d')"
)


def _constraint_contains_voice_cast(bind) -> bool:
    constraints = sa.inspect(bind).get_check_constraints("agent_canvas_nodes")
    return any(
        constraint.get("sql_text") and "voice-cast" in constraint["sql_text"]
        for constraint in constraints
    )


def _widen_node_type_constraint() -> None:
    bind = op.get_bind()
    if _constraint_contains_voice_cast(bind):
        return
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_constraint("ck_agent_canvas_nodes_type", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_nodes_type",
            _NODE_TYPES_WITH_VOICE_CAST,
        )


def _revert_node_type_constraint() -> None:
    bind = op.get_bind()
    if not _constraint_contains_voice_cast(bind):
        return
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_constraint("ck_agent_canvas_nodes_type", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_nodes_type",
            _NODE_TYPES_WITHOUT_VOICE_CAST,
        )


def _create_timelines() -> None:
    op.create_table(
        "timelines",
        sa.Column("timeline_id", sa.Text(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Text(),
            sa.ForeignKey("agent_canvas_workflows.workflow_id"),
            nullable=False,
        ),
        sa.Column("duration_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fps", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("fps > 0", name="ck_timelines_positive_fps"),
        sa.CheckConstraint(
            "duration_seconds >= 0", name="ck_timelines_nonnegative_duration"
        ),
        sa.UniqueConstraint("workflow_id", name="uq_timelines_workflow"),
    )


def _create_timeline_tracks() -> None:
    op.create_table(
        "timeline_tracks",
        sa.Column("track_id", sa.Text(), primary_key=True),
        sa.Column(
            "timeline_id",
            sa.Text(),
            sa.ForeignKey("timelines.timeline_id"),
            nullable=False,
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("muted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("volume", sa.Float(), nullable=False, server_default="1"),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "display_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "type IN ('video','voice','bgm','sfx','camera','subtitle')",
            name="ck_timeline_tracks_type",
        ),
        sa.CheckConstraint(
            "volume >= 0 AND volume <= 1",
            name="ck_timeline_tracks_volume_range",
        ),
        sa.CheckConstraint(
            "display_order >= 0",
            name="ck_timeline_tracks_display_order",
        ),
    )
    op.create_index(
        "ix_timeline_tracks_timeline_order",
        "timeline_tracks",
        ["timeline_id", "display_order"],
    )


def _create_timeline_clips() -> None:
    op.create_table(
        "timeline_clips",
        sa.Column("clip_id", sa.Text(), primary_key=True),
        sa.Column(
            "track_id",
            sa.Text(),
            sa.ForeignKey("timeline_tracks.track_id"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Text()),
        sa.Column("asset_version_id", sa.Text()),
        sa.Column("source_node_id", sa.Text()),
        sa.Column(
            "start_time", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "duration", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "source_start", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("source_duration", sa.Float()),
        sa.Column("fade_in", sa.Float()),
        sa.Column("fade_out", sa.Float()),
        sa.Column("transition_in_type", sa.Text()),
        sa.Column("transition_in_duration", sa.Float()),
        sa.Column("transition_out_type", sa.Text()),
        sa.Column("transition_out_duration", sa.Float()),
        sa.Column("bound_character_id", sa.Text()),
        sa.Column("label", sa.Text()),
        sa.Column("color", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "start_time >= 0", name="ck_timeline_clips_start_time"
        ),
        sa.CheckConstraint(
            "duration > 0", name="ck_timeline_clips_positive_duration"
        ),
        sa.CheckConstraint(
            "source_start >= 0", name="ck_timeline_clips_source_start"
        ),
        sa.CheckConstraint(
            "transition_in_type IS NULL OR transition_in_type IN "
            "('fade','dissolve','wipe')",
            name="ck_timeline_clips_transition_in_type",
        ),
        sa.CheckConstraint(
            "transition_out_type IS NULL OR transition_out_type IN "
            "('fade','dissolve','wipe')",
            name="ck_timeline_clips_transition_out_type",
        ),
    )
    op.create_index(
        "ix_timeline_clips_track_start",
        "timeline_clips",
        ["track_id", "start_time"],
    )
    op.create_index(
        "ix_timeline_clips_source_node",
        "timeline_clips",
        ["source_node_id"],
    )
    op.create_index(
        "ix_timeline_clips_asset",
        "timeline_clips",
        ["asset_id"],
    )


def upgrade() -> None:
    _widen_node_type_constraint()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("timelines"):
        _create_timelines()
    if not inspector.has_table("timeline_tracks"):
        _create_timeline_tracks()
    if not inspector.has_table("timeline_clips"):
        _create_timeline_clips()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("timeline_clips"):
        op.drop_index("ix_timeline_clips_asset", table_name="timeline_clips")
        op.drop_index(
            "ix_timeline_clips_source_node", table_name="timeline_clips"
        )
        op.drop_index(
            "ix_timeline_clips_track_start", table_name="timeline_clips"
        )
        op.drop_table("timeline_clips")
    if inspector.has_table("timeline_tracks"):
        op.drop_index(
            "ix_timeline_tracks_timeline_order",
            table_name="timeline_tracks",
        )
        op.drop_table("timeline_tracks")
    if inspector.has_table("timelines"):
        op.drop_table("timelines")
    _revert_node_type_constraint()
