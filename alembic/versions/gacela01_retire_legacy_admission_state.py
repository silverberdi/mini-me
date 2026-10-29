"""Retire F1 local backlog, queue and scheduler-decision state.

Revision ID: gacela01_retire_legacy_admission_state
Revises: r02_contract_review_budget_identity
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "gacela01_retire_legacy_admission_state"
down_revision: Union[str, None] = "r02_contract_review_budget_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The F1 runbook requires a verified protected backup before this destructive
    # operation. These tables have no retained F1 consumer.
    op.drop_table("scheduler_decision_records")
    op.drop_table("work_queue_snapshots")
    op.drop_table("backlog_items")


def downgrade() -> None:
    # Schema rollback intentionally restores shape, not deleted records. Restore
    # representative/production data from the protected pre-upgrade backup.
    op.create_table(
        "backlog_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("item_key", sa.String(128), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.String(32), nullable=False, server_default="NORMAL"),
        sa.Column("status", sa.String(32), nullable=False, server_default="BACKLOG"),
        sa.Column("source", sa.String(32), nullable=False, server_default="LOCAL_BACKLOG"),
        sa.Column("source_location", sa.String(255)),
        sa.Column("dependencies", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("readiness_state", sa.String(32), nullable=False, server_default="NOT_READY"),
        sa.Column("unmet_readiness_reasons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("human_questions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("human_answers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("github_issue_number", sa.Integer()),
        sa.Column("github_issue_url", sa.String(512)),
        sa.Column("github_project_item_id", sa.String(128)),
        sa.Column("openspec_change_name", sa.String(128)),
        sa.Column("run_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "item_key", name="uq_backlog_items_project_key"),
    )
    op.create_table(
        "work_queue_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("change_name", sa.String(128), nullable=False, index=True),
        sa.Column("github_issue_number", sa.Integer()),
        sa.Column("github_issue_title", sa.String(512)),
        sa.Column("github_project_item_id", sa.String(128)),
        sa.Column("priority", sa.String(32), nullable=False, server_default="NORMAL"),
        sa.Column("roadmap_stage", sa.Integer()),
        sa.Column("dependencies", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("readiness_state", sa.String(32), nullable=False, server_default="NOT_READY"),
        sa.Column("unmet_readiness_reasons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("blocked_reason", sa.Text()),
        sa.Column("admission_eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "change_name", name="uq_work_queue_snapshots_project_change"),
    )
    op.create_table(
        "scheduler_decision_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("change_name", sa.String(128), nullable=False, index=True),
        sa.Column("github_issue_number", sa.Integer()),
        sa.Column("decision", sa.String(32), nullable=False, index=True),
        sa.Column("reason_code", sa.String(64), index=True),
        sa.Column("reason_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("selected_implementer", sa.String(64)),
        sa.Column("concurrency_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("capacity_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("orchestration_runs.id", ondelete="SET NULL"), index=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
