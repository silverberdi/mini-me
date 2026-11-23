"""Add observed cost identity and provenance to the durable ledger."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "req461_durable_cost_settlement"
down_revision: Union[str, None] = "req466_project_test_database_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = _column_names(bind)
    columns = {
        "usage_identity": sa.Column("usage_identity", sa.String(256), nullable=True),
        "source": sa.Column("source", sa.String(128), nullable=True),
        "observed_at": sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
    }
    for name, column in columns.items():
        if name not in existing_columns:
            op.add_column("budget_ledger", column)

    if "uq_budget_ledger_usage_identity" not in _unique_constraint_names(bind):
        op.create_unique_constraint(
            "uq_budget_ledger_usage_identity", "budget_ledger", ["usage_identity"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    constraints = _unique_constraint_names(bind)
    if not constraints or "uq_budget_ledger_usage_identity" in constraints:
        op.drop_constraint("uq_budget_ledger_usage_identity", "budget_ledger", type_="unique")
    cols = _column_names(bind)
    for name in ("observed_at", "source", "usage_identity"):
        if not cols or name in cols:
            op.drop_column("budget_ledger", name)


def _column_names(bind) -> set[str]:
    try:
        inspector = sa.inspect(bind)
        if inspector is None:
            return set()
        return {column["name"] for column in inspector.get_columns("budget_ledger")}
    except Exception:
        return set()


def _unique_constraint_names(bind) -> set[str]:
    try:
        inspector = sa.inspect(bind)
        if inspector is None:
            return set()
        return {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("budget_ledger")
            if constraint.get("name")
        }
    except Exception:
        return set()
