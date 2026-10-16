"""Bind review evidence and budget reservations to provider/account/stage.

Revision ID: r02_contract_review_budget_identity
Revises: 025_independent_audit_policy
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r02_contract_review_budget_identity"
down_revision: Union[str, None] = "025_independent_audit_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("review_stage", sa.String(32), server_default="CODE_REVIEW", nullable=False),
    )
    op.add_column("reviews", sa.Column("contract_hash", sa.String(64), nullable=True))
    op.add_column("reviews", sa.Column("provider", sa.String(32), nullable=True))
    op.add_column("reviews", sa.Column("account_fingerprint", sa.String(64), nullable=True))
    op.add_column("reviews", sa.Column("budget_authorization_id", sa.String(64), nullable=True))
    op.add_column("reviews", sa.Column("budget_reservation_id", sa.String(36), nullable=True))
    op.add_column("reviews", sa.Column("billing_origin", sa.String(64), nullable=True))
    op.create_index("ix_reviews_review_stage", "reviews", ["review_stage"])
    op.create_index("ix_reviews_contract_hash", "reviews", ["contract_hash"])

    op.add_column(
        "openrouter_pricing_snapshots",
        sa.Column("provider", sa.String(32), server_default="openrouter", nullable=False),
    )
    op.add_column(
        "openrouter_pricing_snapshots",
        sa.Column("account_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "openrouter_pricing_snapshots",
        sa.Column("billing_origin", sa.String(64), server_default="openrouter", nullable=False),
    )

    op.add_column("budget_reservations", sa.Column("run_id", sa.String(64), nullable=True))
    op.create_index("ix_budget_reservations_run_id", "budget_reservations", ["run_id"])
    op.add_column(
        "budget_reservations",
        sa.Column("provider", sa.String(32), server_default="openrouter", nullable=False),
    )
    op.add_column(
        "budget_reservations", sa.Column("account_fingerprint", sa.String(64), nullable=True)
    )
    op.add_column(
        "budget_reservations",
        sa.Column("stage", sa.String(32), server_default="LEGACY_OPENROUTER", nullable=False),
    )
    op.add_column(
        "budget_reservations",
        sa.Column("billing_origin", sa.String(64), server_default="openrouter", nullable=False),
    )
    op.add_column(
        "budget_reservations", sa.Column("authorization_id", sa.String(64), nullable=True)
    )
    op.create_unique_constraint(
        "uq_budget_reservations_authorization_id", "budget_reservations", ["authorization_id"]
    )
    op.add_column(
        "budget_reservations", sa.Column("idempotency_key", sa.String(128), nullable=True)
    )
    op.create_unique_constraint(
        "uq_budget_reservations_idempotency_key", "budget_reservations", ["idempotency_key"]
    )

    op.add_column("budget_ledger", sa.Column("account_fingerprint", sa.String(64), nullable=True))
    op.add_column(
        "budget_ledger",
        sa.Column("stage", sa.String(32), server_default="LEGACY_OPENROUTER", nullable=False),
    )
    op.add_column(
        "budget_ledger",
        sa.Column("billing_origin", sa.String(64), server_default="openrouter", nullable=False),
    )


def downgrade() -> None:
    for column in ("billing_origin", "stage", "account_fingerprint"):
        op.drop_column("budget_ledger", column)
    op.drop_constraint(
        "uq_budget_reservations_idempotency_key", "budget_reservations", type_="unique"
    )
    op.drop_constraint(
        "uq_budget_reservations_authorization_id", "budget_reservations", type_="unique"
    )
    for column in (
        "idempotency_key",
        "authorization_id",
        "billing_origin",
        "stage",
        "account_fingerprint",
        "provider",
    ):
        op.drop_column("budget_reservations", column)
    op.drop_index("ix_budget_reservations_run_id", table_name="budget_reservations")
    op.drop_column("budget_reservations", "run_id")
    for column in ("billing_origin", "account_fingerprint", "provider"):
        op.drop_column("openrouter_pricing_snapshots", column)
    op.drop_index("ix_reviews_contract_hash", table_name="reviews")
    op.drop_index("ix_reviews_review_stage", table_name="reviews")
    for column in (
        "billing_origin",
        "budget_reservation_id",
        "budget_authorization_id",
        "account_fingerprint",
        "provider",
        "contract_hash",
        "review_stage",
    ):
        op.drop_column("reviews", column)
