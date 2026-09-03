"""016 provider efficiency telemetry.

Revision ID: 016_provider_efficiency_telemetry
Revises: 015_widen_transition_key
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016_provider_efficiency_telemetry"
down_revision: Union[str, None] = "015_widen_transition_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add efficiency columns to job_attempts
    op.add_column("job_attempts", sa.Column("task_class", sa.String(length=64), nullable=True))
    op.add_column(
        "job_attempts", sa.Column("productivity_class", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "job_attempts", sa.Column("premium_reason_code", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "job_attempts",
        sa.Column(
            "is_same_sha_duplicate",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index("ix_job_attempts_task_class", "job_attempts", ["task_class"])
    op.create_index("ix_job_attempts_productivity_class", "job_attempts", ["productivity_class"])
    op.create_index("ix_job_attempts_premium_reason_code", "job_attempts", ["premium_reason_code"])

    # 2. Create provider_efficiency_metrics table
    op.create_table(
        "provider_efficiency_metrics",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("change_name", sa.String(length=128), nullable=False),
        sa.Column("attempts_by_provider", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("duration_by_provider_ms", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("productive_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("no_progress_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("same_sha_retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "same_sha_retry_suppressed_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("corrective_retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reassignments_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reassignment_reason_codes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("provider_exhaustion_events", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("drain_transitions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("premium_provider_assignments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("premium_provider_reason_codes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("candidate_generations_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("time_to_candidate_ms", sa.Integer(), nullable=True),
        sa.Column("time_to_checks_ms", sa.Integer(), nullable=True),
        sa.Column("time_to_review_ms", sa.Integer(), nullable=True),
        sa.Column("time_to_pr_ms", sa.Integer(), nullable=True),
        sa.Column("total_cycle_time_ms", sa.Integer(), nullable=True),
        sa.Column("human_gates_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("operator_actions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("self_hosting_native_phases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("self_hosting_total_phases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("self_hosting_percentage", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_provider_efficiency_metrics_run_id", "provider_efficiency_metrics", ["run_id"]
    )
    op.create_index(
        "ix_provider_efficiency_metrics_project_id", "provider_efficiency_metrics", ["project_id"]
    )
    op.create_index(
        "ix_provider_efficiency_metrics_change_name", "provider_efficiency_metrics", ["change_name"]
    )
    op.create_index(
        "ix_provider_efficiency_metrics_created_at", "provider_efficiency_metrics", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("provider_efficiency_metrics")
    op.drop_index("ix_job_attempts_premium_reason_code", table_name="job_attempts")
    op.drop_index("ix_job_attempts_productivity_class", table_name="job_attempts")
    op.drop_index("ix_job_attempts_task_class", table_name="job_attempts")
    op.drop_column("job_attempts", "is_same_sha_duplicate")
    op.drop_column("job_attempts", "premium_reason_code")
    op.drop_column("job_attempts", "productivity_class")
    op.drop_column("job_attempts", "task_class")
