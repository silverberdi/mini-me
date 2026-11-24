"""Persist global Watchdog settings and run-bound diagnoses."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "watchdog_518_sre"
down_revision: Union[str, None] = "req461_durable_cost_settlement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchdog_settings",
        sa.Column("settings_id", sa.String(16), primary_key=True),
        sa.Column("provider_id", sa.String(128), nullable=True),
        sa.Column("harness_id", sa.String(128), nullable=True),
        sa.Column("canonical_model_id", sa.String(255), nullable=True),
        sa.Column(
            "inactivity_threshold_minutes", sa.Integer(), nullable=False, server_default="15"
        ),
        sa.Column("mode", sa.String(32), nullable=False, server_default="diagnostic_only"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("settings_id = 'global'", name="ck_watchdog_settings_singleton"),
        sa.CheckConstraint(
            "inactivity_threshold_minutes > 0", name="ck_watchdog_threshold_positive"
        ),
        sa.CheckConstraint(
            "mode IN ('diagnostic_only', 'mechanical_remediation')", name="ck_watchdog_mode"
        ),
        sa.CheckConstraint(
            "(provider_id IS NULL AND harness_id IS NULL AND canonical_model_id IS NULL) OR "
            "(provider_id IS NOT NULL AND harness_id IS NOT NULL AND canonical_model_id IS NOT NULL)",
            name="ck_watchdog_model_selection_complete",
        ),
    )
    op.execute(
        "INSERT INTO watchdog_settings "
        "(settings_id, inactivity_threshold_minutes, mode, updated_at) "
        "VALUES ('global', 15, 'diagnostic_only', CURRENT_TIMESTAMP)"
    )

    op.create_table(
        "watchdog_diagnoses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("orchestration_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("change_name", sa.String(128), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("candidate_sha", sa.String(64), nullable=True),
        sa.Column("candidate_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("root_cause", sa.String(128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("action", sa.String(128), nullable=True),
        sa.Column("action_result", sa.JSON(), nullable=False),
        sa.Column("improvement_suggestion", sa.Text(), nullable=True),
        sa.Column("suggestion_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id", "stage", "candidate_generation", name="uq_watchdog_run_stage_generation"
        ),
        sa.CheckConstraint(
            "suggestion_status IN ('pending', 'converted', 'discarded')",
            name="ck_watchdog_suggestion_status",
        ),
    )
    op.create_index(
        "ix_watchdog_diagnoses_feed",
        "watchdog_diagnoses",
        ["project_id", "suggestion_status", "created_at"],
    )
    op.create_index(
        "ix_watchdog_diagnoses_run", "watchdog_diagnoses", ["run_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_watchdog_diagnoses_run", table_name="watchdog_diagnoses")
    op.drop_index("ix_watchdog_diagnoses_feed", table_name="watchdog_diagnoses")
    op.drop_table("watchdog_diagnoses")
    op.drop_table("watchdog_settings")
