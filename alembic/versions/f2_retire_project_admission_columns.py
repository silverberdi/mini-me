"""Retire project-local admission switches removed in F1.

Revision ID: f2_retire_project_admission_columns
Revises: f2_project_configuration

The dropped values no longer control any operation. Before applying to a
database with retained project rows, operators must retain a restorable backup
under the Change's migration runbook. Downgrade restores schema shape with
legacy-safe defaults; exact pre-upgrade values come from that backup.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2_retire_project_admission_columns"
down_revision: Union[str, None] = "f2_project_configuration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("projects", "max_concurrent_jobs")
    op.drop_column("projects", "auto_admit")
    op.drop_column("projects", "auto_prepare")


def downgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("auto_prepare", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "projects",
        sa.Column("auto_admit", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "projects",
        sa.Column("max_concurrent_jobs", sa.Integer(), nullable=False, server_default="1"),
    )
