"""006 openrouter budget tables

Revision ID: 006_openrouter_budget
Revises: 005_provider_resilience
Create Date: 2026-08-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_openrouter_budget"
down_revision: Union[str, None] = "005_provider_resilience"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
    op.create_table(
        "openrouter_pricing_snapshots",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("canonical_model_identity", sa.String(length=128), nullable=False),
        sa.Column("routed_model_identity", sa.String(length=128), nullable=False),
        sa.Column("prompt_price_per_token", sa.Numeric(14, 10), nullable=False),
        sa.Column("output_price_per_token", sa.Numeric(14, 10), nullable=False),
        sa.Column(
            "additional_cost_per_request", sa.Numeric(10, 6), nullable=False, server_default="0"
        ),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("change_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("canonical_model_identity", sa.String(length=128), nullable=False),
        sa.Column("reserved_amount_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "pricing_snapshot_id",
            sa.String(length=128),
            sa.ForeignKey("openrouter_pricing_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_table(
        "budget_ledger",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "reservation_id",
            sa.String(length=36),
            sa.ForeignKey("budget_reservations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("change_id", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="openrouter"),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("canonical_model_identity", sa.String(length=128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("amount_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column("entry_type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_budget_reservations_project_status", "budget_reservations", ["project_id", "status"]
    )
    op.create_index("ix_budget_reservations_created_at", "budget_reservations", ["created_at"])
    op.create_index(
        "ix_budget_ledger_project_created", "budget_ledger", ["project_id", "created_at"]
    )
    op.create_index("ix_budget_ledger_created", "budget_ledger", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_budget_ledger_created", table_name="budget_ledger")
    op.drop_index("ix_budget_ledger_project_created", table_name="budget_ledger")
    op.drop_index("ix_budget_reservations_created_at", table_name="budget_reservations")
    op.drop_index("ix_budget_reservations_project_status", table_name="budget_reservations")
    op.drop_table("budget_ledger")
    op.drop_table("budget_reservations")
    op.drop_table("openrouter_pricing_snapshots")
    op.drop_table("openrouter_budget_policies")
