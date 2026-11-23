"""Add observed cost identity and provenance to the durable ledger."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "req461_durable_cost_settlement"
down_revision: Union[str, None] = "req466_project_test_database_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("budget_ledger", sa.Column("usage_identity", sa.String(256), nullable=True))
    op.add_column("budget_ledger", sa.Column("source", sa.String(128), nullable=True))
    op.add_column(
        "budget_ledger",
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_budget_ledger_usage_identity", "budget_ledger", ["usage_identity"])


def downgrade() -> None:
    op.drop_constraint("uq_budget_ledger_usage_identity", "budget_ledger", type_="unique")
    op.drop_column("budget_ledger", "observed_at")
    op.drop_column("budget_ledger", "source")
    op.drop_column("budget_ledger", "usage_identity")
