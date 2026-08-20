"""001 initial foundation tables

Revision ID: 001_initial_foundation
Revises:
Create Date: 2026-08-19 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial_foundation"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # projects
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("base_branch", sa.String(length=128), server_default="main", nullable=False),
        sa.Column(
            "openspec_path", sa.String(length=255), server_default="openspec", nullable=False
        ),
        sa.Column("implementer", sa.String(length=64), server_default="codex", nullable=False),
        sa.Column("reviewer", sa.String(length=64), server_default="antigravity", nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("external_providers_allowed", sa.JSON(), nullable=False),
        sa.Column(
            "openrouter_drain_allowed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("deployment_preview", sa.JSON(), nullable=False),
        sa.Column("deployment_production", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="ACTIVE", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # project_bindings
    op.create_table(
        "project_bindings",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("github_issue_number", sa.Integer(), nullable=True),
        sa.Column("github_project_item_id", sa.String(length=128), nullable=True),
        sa.Column("openspec_change_name", sa.String(length=128), nullable=False),
        sa.Column("is_valid", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("mismatch_reasons", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "openspec_change_name", name="uq_project_bindings_project_change"
        ),
    )
    op.create_index("ix_project_bindings_project_id", "project_bindings", ["project_id"])

    # changes
    op.create_table(
        "changes",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="DISCOVERED", nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column(
            "schema_name", sa.String(length=64), server_default="spec-driven", nullable=False
        ),
        sa.Column("proposal_path", sa.Text(), nullable=True),
        sa.Column("tasks_path", sa.Text(), nullable=True),
        sa.Column("design_path", sa.Text(), nullable=True),
        sa.Column("specs_paths", sa.JSON(), nullable=False),
        sa.Column(
            "last_readiness_status",
            sa.String(length=32),
            server_default="NOT_READY",
            nullable=False,
        ),
        sa.Column("last_readiness_reasons", sa.JSON(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_changes_project_id", "changes", ["project_id"])
    op.create_index("ix_changes_name", "changes", ["name"])

    # events
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("change_id", sa.String(length=64), nullable=True),
        sa.Column("operation_id", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_project_id", "events", ["project_id"])
    op.create_index("ix_events_change_id", "events", ["change_id"])
    op.create_index("ix_events_timestamp", "events", ["timestamp"])

    # metric_facts
    op.create_table(
        "metric_facts",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("metric_name", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("change_id", sa.String(length=64), nullable=True),
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


def downgrade() -> None:
    op.drop_table("metric_facts")
    op.drop_table("events")
    op.drop_table("changes")
    op.drop_table("project_bindings")
    op.drop_table("projects")
