"""add explicit project policy for independent DeepSeek audits

Revision ID: 025_independent_audit_policy
Revises: g02_intake_workspace_isolation
Create Date: 2026-10-14 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "025_independent_audit_policy"
down_revision: Union[str, None] = "g02_intake_workspace_isolation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "independent_audit_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "independent_audit_required")
