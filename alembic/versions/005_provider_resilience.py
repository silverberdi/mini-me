"""005 provider resilience and capacity tables

Revision ID: 005_provider_resilience
Revises: 004_deepseek_audit
Create Date: 2026-08-20 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_provider_resilience"
down_revision: Union[str, None] = "004_deepseek_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add capacity and recovery columns to jobs
    op.add_column("jobs", sa.Column("waiting_provider", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("capacity_block_reason", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("recovery_blocked_reason", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("expected_reset_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_jobs_waiting_provider", "jobs", ["waiting_provider"])
    op.create_index("ix_jobs_expected_reset_at", "jobs", ["expected_reset_at"])

    # 2. Create provider_health table
    op.create_table(
        "provider_health",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, unique=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_result_class", sa.String(length=32), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_health_provider", "provider_health", ["provider"])
    op.create_index("ix_provider_health_status", "provider_health", ["status"])
    op.create_index("ix_provider_health_updated_at", "provider_health", ["updated_at"])

    # 3. Create capacity_windows table
    op.create_table(
        "capacity_windows",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("quota_exhausted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
        sa.Column("source_signal", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_capacity_windows_provider", "capacity_windows", ["provider"])
    op.create_index(
        "ix_capacity_windows_quota_exhausted_at", "capacity_windows", ["quota_exhausted_at"]
    )
    op.create_index(
        "ix_capacity_windows_capacity_reset_at", "capacity_windows", ["capacity_reset_at"]
    )
    op.create_index("ix_capacity_windows_created_at", "capacity_windows", ["created_at"])

    # 4. Create git_operations table for mini me Git operation ownership tracking
    op.create_table(
        "git_operations",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("worktree_path", sa.String(length=512), nullable=False),
        sa.Column("operation_type", sa.String(length=64), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_git_operations_job_id", "git_operations", ["job_id"])
    op.create_index("ix_git_operations_project_id", "git_operations", ["project_id"])
    op.create_index("ix_git_operations_worktree_path", "git_operations", ["worktree_path"])
    op.create_index("ix_git_operations_status", "git_operations", ["status"])


def downgrade() -> None:
    op.drop_table("git_operations")
    op.drop_table("capacity_windows")
    op.drop_table("provider_health")
    op.drop_index("ix_jobs_expected_reset_at", table_name="jobs")
    op.drop_index("ix_jobs_waiting_provider", table_name="jobs")
    op.drop_column("jobs", "expected_reset_at")
    op.drop_column("jobs", "recovery_blocked_reason")
    op.drop_column("jobs", "capacity_block_reason")
    op.drop_column("jobs", "waiting_provider")
