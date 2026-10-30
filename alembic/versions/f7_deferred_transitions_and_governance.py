"""Durable F7 deferred transitions and executor governance.

Revision ID: f7_deferred_transitions_and_governance
Revises: f2_retire_project_legacy_context
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7_deferred_transitions_and_governance"
down_revision: Union[str, None] = "f2_retire_project_legacy_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deferred_transitions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("transition_type", sa.String(64), nullable=False),
        sa.Column("target_project_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("deferred_transitions")
