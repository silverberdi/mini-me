"""011 governance hardening review authorship evidence."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_governance_hardening"
down_revision: Union[str, None] = "010_candidate_remediation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("is_mixed_authorship", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "reviews",
        sa.Column("authorship_evidence", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("reviews", "authorship_evidence")
    op.drop_column("reviews", "is_mixed_authorship")
