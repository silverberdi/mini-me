"""008 autonomous change orchestration tables

Revision ID: 008_autonomous_orchestration
Revises: 007_continuation_governance
Create Date: 2026-08-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_autonomous_orchestration"
down_revision: Union[str, None] = "007_continuation_governance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create orchestration_runs table
    op.create_table(
        "orchestration_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("change_name", sa.String(length=128), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=False),
        sa.Column("current_stage", sa.String(length=32), nullable=False, server_default="ADMITTED"),
        sa.Column(
            "resumable_stage", sa.String(length=32), nullable=False, server_default="ADMITTED"
        ),
        sa.Column("stop_outcome", sa.String(length=32), nullable=True),
        sa.Column("human_gate", sa.String(length=32), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("stop_details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "active_job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("current_generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_candidate_sha", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_orchestration_runs_project_id", "orchestration_runs", ["project_id"])
    op.create_index("ix_orchestration_runs_change_name", "orchestration_runs", ["change_name"])
    op.create_index("ix_orchestration_runs_current_stage", "orchestration_runs", ["current_stage"])
    op.create_index("ix_orchestration_runs_stop_outcome", "orchestration_runs", ["stop_outcome"])
    op.create_index("ix_orchestration_runs_human_gate", "orchestration_runs", ["human_gate"])
    op.create_index("ix_orchestration_runs_active_job_id", "orchestration_runs", ["active_job_id"])
    op.create_index("ix_orchestration_runs_is_active", "orchestration_runs", ["is_active"])
    op.create_index("ix_orchestration_runs_created_at", "orchestration_runs", ["created_at"])
    op.create_index(
        "uq_active_orchestration_run",
        "orchestration_runs",
        ["project_id", "change_name"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
        sqlite_where=sa.text("is_active = 1"),
    )

    # 2. Create orchestration_stage_events table
    op.create_table(
        "orchestration_stage_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_stage", sa.String(length=32), nullable=True),
        sa.Column("to_stage", sa.String(length=32), nullable=False),
        sa.Column(
            "event_type",
            sa.String(length=64),
            nullable=False,
            server_default="STAGE_TRANSITION",
        ),
        sa.Column("transition_key", sa.String(length=128), nullable=True),
        sa.Column("evidence_references", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("actor", sa.String(length=64), nullable=False, server_default="system"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_orchestration_stage_events_run_id", "orchestration_stage_events", ["run_id"]
    )
    op.create_index(
        "ix_orchestration_stage_events_transition_key",
        "orchestration_stage_events",
        ["transition_key"],
        unique=True,
    )
    op.create_index(
        "ix_orchestration_stage_events_created_at",
        "orchestration_stage_events",
        ["created_at"],
    )

    # 3. Create orchestration_candidates table
    op.create_table(
        "orchestration_candidates",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=False),
        sa.Column("candidate_sha", sa.String(length=64), nullable=False),
        sa.Column(
            "manifest_id",
            sa.String(length=64),
            sa.ForeignKey("candidate_manifests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("authorship_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_frozen", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("superseded_by_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("run_id", "generation", name="uq_orchestration_candidate_generation"),
    )
    op.create_index("ix_orchestration_candidates_run_id", "orchestration_candidates", ["run_id"])
    op.create_index(
        "ix_orchestration_candidates_created_at",
        "orchestration_candidates",
        ["created_at"],
    )

    # 4. Create orchestration_external_actions table
    op.create_table(
        "orchestration_external_actions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_key", sa.String(length=128), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("target_identity", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("candidate_sha", sa.String(length=64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="RESERVED"),
        sa.Column("remote_identifier", sa.String(length=255), nullable=True),
        sa.Column("result_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "reserved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_orchestration_external_actions_run_id",
        "orchestration_external_actions",
        ["run_id"],
    )
    op.create_index(
        "ix_orchestration_external_actions_action_key",
        "orchestration_external_actions",
        ["action_key"],
        unique=True,
    )
    op.create_index(
        "ix_orchestration_external_actions_status",
        "orchestration_external_actions",
        ["status"],
    )
    op.create_index(
        "ix_orchestration_external_actions_created_at",
        "orchestration_external_actions",
        ["created_at"],
    )

    # Historical review/audit records remain readable, but the coordinator
    # rejects any record missing these explicit authority bindings.
    op.add_column("project_bindings", sa.Column("github_pr_number", sa.Integer(), nullable=True))
    op.add_column(
        "project_bindings", sa.Column("github_pr_url", sa.String(length=512), nullable=True)
    )
    op.add_column("reviews", sa.Column("reviewer_model", sa.String(length=128), nullable=True))
    op.add_column("reviews", sa.Column("orchestration_run_id", sa.String(length=64), nullable=True))
    op.add_column("reviews", sa.Column("candidate_generation", sa.Integer(), nullable=True))
    op.add_column("reviews", sa.Column("manifest_id", sa.String(length=64), nullable=True))
    op.add_column("reviews", sa.Column("manifest_hash", sa.String(length=64), nullable=True))
    op.add_column("audits", sa.Column("orchestration_run_id", sa.String(length=64), nullable=True))
    op.add_column("audits", sa.Column("candidate_generation", sa.Integer(), nullable=True))
    op.add_column("audits", sa.Column("manifest_id", sa.String(length=64), nullable=True))
    op.add_column("audits", sa.Column("manifest_hash", sa.String(length=64), nullable=True))
    op.add_column("audits", sa.Column("is_full_candidate", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("audits", "is_full_candidate")
    op.drop_column("audits", "manifest_hash")
    op.drop_column("audits", "manifest_id")
    op.drop_column("audits", "candidate_generation")
    op.drop_column("audits", "orchestration_run_id")
    op.drop_column("reviews", "manifest_hash")
    op.drop_column("reviews", "manifest_id")
    op.drop_column("reviews", "candidate_generation")
    op.drop_column("reviews", "orchestration_run_id")
    op.drop_column("reviews", "reviewer_model")
    op.drop_column("project_bindings", "github_pr_url")
    op.drop_column("project_bindings", "github_pr_number")

    op.drop_index(
        "ix_orchestration_external_actions_created_at",
        table_name="orchestration_external_actions",
    )
    op.drop_index(
        "ix_orchestration_external_actions_status",
        table_name="orchestration_external_actions",
    )
    op.drop_index(
        "ix_orchestration_external_actions_action_key",
        table_name="orchestration_external_actions",
    )
    op.drop_index(
        "ix_orchestration_external_actions_run_id",
        table_name="orchestration_external_actions",
    )
    op.drop_table("orchestration_external_actions")

    op.drop_index(
        "ix_orchestration_candidates_created_at",
        table_name="orchestration_candidates",
    )
    op.drop_index("ix_orchestration_candidates_run_id", table_name="orchestration_candidates")
    op.drop_table("orchestration_candidates")

    op.drop_index(
        "ix_orchestration_stage_events_created_at",
        table_name="orchestration_stage_events",
    )
    op.drop_index(
        "ix_orchestration_stage_events_transition_key",
        table_name="orchestration_stage_events",
    )
    op.drop_index(
        "ix_orchestration_stage_events_run_id",
        table_name="orchestration_stage_events",
    )
    op.drop_table("orchestration_stage_events")

    op.drop_index("uq_active_orchestration_run", table_name="orchestration_runs")
    op.drop_index("ix_orchestration_runs_created_at", table_name="orchestration_runs")
    op.drop_index("ix_orchestration_runs_is_active", table_name="orchestration_runs")
    op.drop_index("ix_orchestration_runs_active_job_id", table_name="orchestration_runs")
    op.drop_index("ix_orchestration_runs_human_gate", table_name="orchestration_runs")
    op.drop_index("ix_orchestration_runs_stop_outcome", table_name="orchestration_runs")
    op.drop_index("ix_orchestration_runs_current_stage", table_name="orchestration_runs")
    op.drop_index("ix_orchestration_runs_change_name", table_name="orchestration_runs")
    op.drop_index("ix_orchestration_runs_project_id", table_name="orchestration_runs")
    op.drop_table("orchestration_runs")
