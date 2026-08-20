"""002 jobs pipeline tables

Revision ID: 002_jobs_pipeline
Revises: 001_initial_foundation
Create Date: 2026-08-20 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_jobs_pipeline"
down_revision: Union[str, None] = "001_initial_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("change_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("implementer_role", sa.String(length=64), nullable=False),
        sa.Column("candidate_sha", sa.String(length=64), nullable=True),
        sa.Column("base_sha", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])
    op.create_index("ix_jobs_change_name", "jobs", ["change_name"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])

    op.create_table(
        "job_logs",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stream", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_logs_job_id", "job_logs", ["job_id"])
    op.create_index("ix_job_logs_timestamp", "job_logs", ["timestamp"])

    op.create_table(
        "check_results",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check_name", sa.String(length=128), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("output_snippet", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_check_results_job_id", "check_results", ["job_id"])
    op.create_index("ix_check_results_created_at", "check_results", ["created_at"])


def downgrade() -> None:
    op.drop_table("check_results")
    op.drop_table("job_logs")
    op.drop_table("jobs")
