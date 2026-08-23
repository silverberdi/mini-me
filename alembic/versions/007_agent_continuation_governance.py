"""007 agent continuation and reassignment governance tables

Revision ID: 007_continuation_governance
Revises: 006_openrouter_budget
Create Date: 2026-08-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_continuation_governance"
down_revision: Union[str, None] = "006_openrouter_budget"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add columns to jobs table
    op.add_column(
        "jobs", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "jobs", sa.Column("reassignment_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("jobs", sa.Column("current_executor", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("latest_outcome", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("latest_progress", sa.String(length=64), nullable=True))
    op.add_column("jobs", sa.Column("continuation_decision", sa.String(length=64), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("is_mixed_authorship", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("jobs", sa.Column("escalation_reason", sa.Text(), nullable=True))

    # 2. Create job_attempts table
    op.create_table(
        "job_attempts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("executor_role", sa.String(length=64), nullable=False),
        sa.Column("model_identity", sa.String(length=128), nullable=False),
        sa.Column("start_sha", sa.String(length=64), nullable=True),
        sa.Column("end_sha", sa.String(length=64), nullable=True),
        sa.Column("normalized_outcome", sa.String(length=64), nullable=False),
        sa.Column("progress_classification", sa.String(length=64), nullable=True),
        sa.Column("continuation_decision", sa.String(length=64), nullable=True),
        sa.Column("corrective_retries_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("same_outcome_streak", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "same_blocker_fingerprint_streak", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("corrective_prompt", sa.Text(), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_job_attempts_job_id", "job_attempts", ["job_id"])
    op.create_index("ix_job_attempts_normalized_outcome", "job_attempts", ["normalized_outcome"])
    op.create_index("ix_job_attempts_started_at", "job_attempts", ["started_at"])
    op.create_index("ix_job_attempts_created_at", "job_attempts", ["created_at"])

    # 3. Create blocker_claims table
    op.create_table(
        "blocker_claims",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id",
            sa.String(length=64),
            sa.ForeignKey("job_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("blocker_type", sa.String(length=64), nullable=False),
        sa.Column("blocker_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("affected_requirement", sa.String(length=255), nullable=True),
        sa.Column("failing_invariant", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("attempted_remediation", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("is_agent_solvable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("validation_verdict", sa.String(length=32), nullable=False),
        sa.Column("validation_rationale", sa.Text(), nullable=True),
        sa.Column(
            "available_integration_points",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_blocker_claims_job_id", "blocker_claims", ["job_id"])
    op.create_index("ix_blocker_claims_attempt_id", "blocker_claims", ["attempt_id"])
    op.create_index("ix_blocker_claims_fingerprint", "blocker_claims", ["blocker_fingerprint"])
    op.create_index(
        "ix_blocker_claims_validation_verdict", "blocker_claims", ["validation_verdict"]
    )
    op.create_index("ix_blocker_claims_created_at", "blocker_claims", ["created_at"])

    # 4. Create job_handoffs table
    op.create_table(
        "job_handoffs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_attempt_id",
            sa.String(length=64),
            sa.ForeignKey("job_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_attempt_id",
            sa.String(length=64),
            sa.ForeignKey("job_attempts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_executor", sa.String(length=64), nullable=False),
        sa.Column("to_executor", sa.String(length=64), nullable=False),
        sa.Column("worktree_path", sa.String(length=512), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=False),
        sa.Column("candidate_sha", sa.String(length=64), nullable=False),
        sa.Column("completed_tasks", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("remaining_tasks", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("manifest_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("checks_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("blockers_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("architectural_notes", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "do_not_redo_guidance", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("authorship_history", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("is_consumed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_job_handoffs_job_id", "job_handoffs", ["job_id"])
    op.create_index("ix_job_handoffs_created_at", "job_handoffs", ["created_at"])

    # 5. Create candidate_manifests table
    op.create_table(
        "candidate_manifests",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id",
            sa.String(length=64),
            sa.ForeignKey("job_attempts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("candidate_sha", sa.String(length=64), nullable=False),
        sa.Column("tracked_files", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("staged_files", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("untracked_files", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("deleted_files", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("total_files_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_candidate_manifests_job_id", "candidate_manifests", ["job_id"])
    op.create_index("ix_candidate_manifests_created_at", "candidate_manifests", ["created_at"])

    # 6. Create candidate_authorships table
    op.create_table(
        "candidate_authorships",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_role", sa.String(length=64), nullable=False),
        sa.Column("model_identity", sa.String(length=128), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("files_touched", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("is_primary_author", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_candidate_authorships_job_id", "candidate_authorships", ["job_id"])
    op.create_index("ix_candidate_authorships_created_at", "candidate_authorships", ["created_at"])

    # 7. Create evidence_diagnostics table
    op.create_table(
        "evidence_diagnostics",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id",
            sa.String(length=64),
            sa.ForeignKey("job_attempts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stage_type", sa.String(length=64), nullable=False),
        sa.Column("check_name", sa.String(length=128), nullable=True),
        sa.Column("diagnostic_status", sa.String(length=32), nullable=False),
        sa.Column("environment_identity", sa.String(length=128), nullable=False),
        sa.Column("candidate_sha", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence_reference", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_evidence_diagnostics_job_id", "evidence_diagnostics", ["job_id"])
    op.create_index("ix_evidence_diagnostics_status", "evidence_diagnostics", ["diagnostic_status"])
    op.create_index("ix_evidence_diagnostics_created_at", "evidence_diagnostics", ["created_at"])


def downgrade() -> None:
    op.drop_table("evidence_diagnostics")
    op.drop_table("candidate_authorships")
    op.drop_table("candidate_manifests")
    op.drop_table("job_handoffs")
    op.drop_table("blocker_claims")
    op.drop_table("job_attempts")

    op.drop_column("jobs", "escalation_reason")
    op.drop_column("jobs", "is_mixed_authorship")
    op.drop_column("jobs", "continuation_decision")
    op.drop_column("jobs", "latest_progress")
    op.drop_column("jobs", "latest_outcome")
    op.drop_column("jobs", "current_executor")
    op.drop_column("jobs", "reassignment_count")
    op.drop_column("jobs", "attempt_count")
