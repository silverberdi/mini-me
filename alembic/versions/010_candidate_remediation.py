"""Persist immutable preserved-candidate remediation requests."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_candidate_remediation"
down_revision: Union[str, None] = "009_human_resolution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candidate_remediations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_candidate_id", sa.String(length=64), nullable=False),
        sa.Column("source_generation", sa.Integer(), nullable=False),
        sa.Column("source_candidate_sha", sa.String(length=64), nullable=False),
        sa.Column("source_base_sha", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("contract_hash", sa.String(length=64), nullable=False),
        sa.Column("contract_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("workspace_path", sa.String(length=1024), nullable=True),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("authorized_paths", sa.JSON(), nullable=False),
        sa.Column("tree_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("result_candidate_id", sa.String(length=64), nullable=True),
        sa.Column("result_generation", sa.Integer(), nullable=True),
        sa.Column("result_candidate_sha", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "source_generation",
            "source_candidate_sha",
            "contract_hash",
            name="uq_candidate_remediation_identity",
        ),
    )
    op.create_index("ix_candidate_remediations_run_id", "candidate_remediations", ["run_id"])
    op.create_index("ix_candidate_remediations_job_id", "candidate_remediations", ["job_id"])
    op.create_index("ix_candidate_remediations_status", "candidate_remediations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_candidate_remediations_status", table_name="candidate_remediations")
    op.drop_index("ix_candidate_remediations_job_id", table_name="candidate_remediations")
    op.drop_index("ix_candidate_remediations_run_id", table_name="candidate_remediations")
    op.drop_table("candidate_remediations")
