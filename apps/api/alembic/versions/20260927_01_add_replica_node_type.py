"""Widen the Agent Canvas node type constraint to include replica.

The node type is already accepted by ``CanvasNodeTypeV2`` (the replica
blueprint node shipped 2026-09-27), but this migration was missed — creating
a replica node on any database carried by the old CHECK fails with
``ck_agent_canvas_nodes_type``. Follows the 20260919_01 (voice-cast) pattern.

Revision ID: 20260927_01
Revises: 20260922_01
Create Date: 2026-09-27
"""

from alembic import op


revision = "20260927_01"
down_revision = "20260922_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_constraint("ck_agent_canvas_nodes_type", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_nodes_type",
            "node_type IN ('text', 'script', 'image', 'video', 'audio', 'editing', "
            "'scene-3d', 'voice-cast', 'replica')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_constraint("ck_agent_canvas_nodes_type", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_nodes_type",
            "node_type IN ('text', 'script', 'image', 'video', 'audio', 'editing', "
            "'scene-3d', 'voice-cast')",
        )
