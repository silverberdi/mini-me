"""020 autonomous intake admission policy.

Revision ID: 020_autonomous_intake_admission_policy
Revises: 019_work_intake_and_backlog_items
Create Date: 2026-09-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_autonomous_intake_admission_policy"
down_revision: Union[str, None] = "019_work_intake_and_backlog_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add auto_prepare, auto_admit, and max_concurrent_jobs columns to projects table
    op.add_column(
        "projects",
        sa.Column("auto_prepare", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "projects",
        sa.Column("auto_admit", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "projects",
        sa.Column("max_concurrent_jobs", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("projects", "max_concurrent_jobs")
    op.drop_column("projects", "auto_admit")
    op.drop_column("projects", "auto_prepare")
