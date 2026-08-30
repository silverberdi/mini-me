"""Add immutable candidate refs and generation-bound check evidence."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_human_resolution"
down_revision: Union[str, None] = "008b_change_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orchestration_candidates",
        sa.Column("candidate_ref", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "check_results",
        sa.Column("candidate_sha", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "check_results",
        sa.Column("candidate_generation", sa.Integer(), nullable=True),
    )
    op.create_index("ix_check_results_candidate_sha", "check_results", ["candidate_sha"])
    op.create_index(
        "ix_check_results_candidate_generation",
        "check_results",
        ["candidate_generation"],
    )


def downgrade() -> None:
    op.drop_index("ix_check_results_candidate_generation", table_name="check_results")
    op.drop_index("ix_check_results_candidate_sha", table_name="check_results")
    op.drop_column("check_results", "candidate_generation")
    op.drop_column("check_results", "candidate_sha")
    op.drop_column("orchestration_candidates", "candidate_ref")
