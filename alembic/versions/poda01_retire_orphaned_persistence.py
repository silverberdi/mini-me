"""Retire orphaned persistence tables (PODA 1: Issue #316).

Drops preview_sessions, validation_runs, integrity_findings, and metric_facts tables
which have 0 consumers in the active UI and runtime orchestration.
Includes symmetric downgrade() for reversible migrations.

Revision ID: poda01_retire_orphaned_persistence
Revises: f14_provider_model_enablement
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "poda01_retire_orphaned_persistence"
down_revision: Union[str, None] = "f14_provider_model_enablement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop in foreign key dependency order: validation_runs references preview_sessions
    op.drop_table("validation_runs")
    op.drop_table("preview_sessions")
    op.drop_table("integrity_findings")
    op.drop_table("metric_facts")


def downgrade() -> None:
    # Recreate metric_facts
    op.create_table(
        "metric_facts",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("metric_name", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("change_id", sa.String(length=128), nullable=True),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("fact_value", sa.Float(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_metric_facts_metric_name", "metric_facts", ["metric_name"])
    op.create_index("ix_metric_facts_project_id", "metric_facts", ["project_id"])
    op.create_index("ix_metric_facts_change_id", "metric_facts", ["change_id"])
    op.create_index("ix_metric_facts_recorded_at", "metric_facts", ["recorded_at"])

    # Recreate integrity_findings
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

    # Recreate preview_sessions
    op.create_table(
        "preview_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("change_name", sa.String(length=128), nullable=False, index=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("orchestration_runs.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("candidate_generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("head_sha", sa.String(length=64), nullable=False, index=True),
        sa.Column("base_sha", sa.String(length=64), nullable=False),
        sa.Column(
            "image_digest", sa.String(length=128), nullable=False, server_default="", index=True
        ),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="REQUESTED", index=True
        ),
        sa.Column("container_id", sa.String(length=128), nullable=True),
        sa.Column("container_name", sa.String(length=128), nullable=True),
        sa.Column("allocated_port", sa.Integer(), nullable=True),
        sa.Column("preview_url", sa.String(length=255), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Recreate validation_runs
    op.create_table(
        "validation_runs",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "preview_id",
            sa.String(length=64),
            sa.ForeignKey("preview_sessions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("change_name", sa.String(length=128), nullable=False, index=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("orchestration_runs.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("candidate_generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("head_sha", sa.String(length=64), nullable=False, index=True),
        sa.Column("base_sha", sa.String(length=64), nullable=False),
        sa.Column("image_digest", sa.String(length=128), nullable=False, index=True),
        sa.Column(
            "verdict", sa.String(length=32), nullable=False, server_default="PASS", index=True
        ),
        sa.Column("scenario_results", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("operator", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
