"""Add push_subscriptions table for F11 Web Push.

Revision ID: f11_push_subscriptions
Revises: f7_deferred_transitions_and_governance
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f11_push_subscriptions"
down_revision: Union[str, None] = "f7_deferred_transitions_and_governance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("operator_id", sa.String(128), nullable=False, index=True),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("device_label", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("category_stage_transitions", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("category_human_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("category_terminal_outcomes", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("push_subscriptions")
