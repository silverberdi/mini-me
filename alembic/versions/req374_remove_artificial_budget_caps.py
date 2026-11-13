"""Remove artificial OpenRouter project spend caps.

Revision ID: req374_remove_artificial_budget_caps
Revises: poda01_retire_orphaned_persistence
Create Date: 2026-11-12
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "req374_remove_artificial_budget_caps"
down_revision: Union[str, None] = "poda01_retire_orphaned_persistence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "UPDATE projects SET execution_policy = "
                "CAST(CAST(execution_policy AS jsonb) - "
                "ARRAY['fallback_authorized','fallback_daily_cap_usd','fallback_monthly_cap_usd'] "
                "AS json)"
            )
        )
    op.drop_table("openrouter_budget_policies")
    op.drop_column("projects", "openrouter_drain_allowed")


def downgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "openrouter_drain_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "openrouter_budget_policies",
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("daily_cap_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("monthly_cap_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_breached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
