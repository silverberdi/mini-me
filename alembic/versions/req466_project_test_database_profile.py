"""Add non-secret per-project PostgreSQL test database identity.

Revision ID: req466_project_test_database_profile
Revises: req374_remove_artificial_budget_caps
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "req466_project_test_database_profile"
down_revision: Union[str, None] = "req374_remove_artificial_budget_caps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("test_database", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "test_database")
