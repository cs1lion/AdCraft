"""Widen the Agent Canvas node type constraint to include voice-cast.

The node type is already accepted by ``CanvasNodeTypeV2``; without this
migration creating a voice-cast node fails the database CHECK constraint.

Revision ID: 20260919_01
Revises: 20260918_02
Create Date: 2026-09-19
"""

from alembic import op


revision = "20260919_01"
down_revision = "20260918_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_constraint("ck_agent_canvas_nodes_type", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_nodes_type",
            "node_type IN ('text', 'script', 'image', 'video', 'audio', 'editing', 'scene-3d', 'voice-cast')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_constraint("ck_agent_canvas_nodes_type", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_nodes_type",
            "node_type IN ('text', 'script', 'image', 'video', 'audio', 'editing', 'scene-3d')",
        )
