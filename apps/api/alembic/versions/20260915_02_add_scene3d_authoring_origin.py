"""Add authoring origin fields to Agent Canvas nodes.

Revision ID: 20260915_02
Revises: 20260915_01
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260915_02"
down_revision = "20260915_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.add_column(
            sa.Column(
                "authoring_origin",
                sa.Text(),
                nullable=False,
                server_default="user_free",
            )
        )
        batch.add_column(sa.Column("intent_hint", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_agent_canvas_nodes_authoring_origin",
            "authoring_origin IN ('user_free', 'agent_guided', 'template')",
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_canvas_nodes") as batch:
        batch.drop_constraint("ck_agent_canvas_nodes_authoring_origin", type_="check")
        batch.drop_column("intent_hint")
        batch.drop_column("authoring_origin")
