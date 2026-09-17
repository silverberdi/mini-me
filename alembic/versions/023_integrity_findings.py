"""Add integrity_findings table for OpenSpec integrity audits.

Revision ID: 023_integrity_findings
Revises: 022_strict_openspec_lifecycle_governance
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "023_integrity_findings"
down_revision: Union[str, None] = "022_strict_openspec_lifecycle_governance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integrity_findings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("overall_status", sa.String(length=16), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("evidence_gaps", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("integrity_findings")
