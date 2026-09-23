"""Widen the Agent Canvas node type constraint to include scene-3d.

Revision ID: 20260915_01
Revises: 20260908_01
Create Date: 2026-09-15
"""

from alembic import op


revision = "20260915_01"
down_revision = "20260908_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_constraint("ck_agent_canvas_nodes_type", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_nodes_type",
            "node_type IN ('text', 'script', 'image', 'video', 'audio', 'editing', 'scene-3d')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_constraint("ck_agent_canvas_nodes_type", type_="check")
        batch.create_check_constraint(
            "ck_agent_canvas_nodes_type",
            "node_type IN ('text', 'script', 'image', 'video', 'audio', 'editing')",
        )
