"""014 autonomous queue work selection persistence.

Revision ID: 014_autonomous_queue_work_selection
Revises: 013_operator_control_plane
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_autonomous_queue_work_selection"
down_revision: Union[str, None] = "013_operator_control_plane"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")
    op.create_table(
        "work_queue_snapshots",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("change_name", sa.String(length=128), nullable=False, index=True),
        sa.Column("github_issue_number", sa.Integer(), nullable=True),
        sa.Column("github_issue_title", sa.String(length=512), nullable=True),
        sa.Column("github_project_item_id", sa.String(length=128), nullable=True),
        sa.Column("priority", sa.String(length=32), nullable=False, server_default="NORMAL"),
        sa.Column("roadmap_stage", sa.Integer(), nullable=True),
        sa.Column("dependencies", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "readiness_state", sa.String(length=32), nullable=False, server_default="NOT_READY"
        ),
        sa.Column("unmet_readiness_reasons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column(
            "admission_eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "change_name", name="uq_work_queue_snapshots_project_change"
        ),
    )

    op.create_table(
        "scheduler_decision_records",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("change_name", sa.String(length=128), nullable=False, index=True),
        sa.Column("github_issue_number", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False, index=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True, index=True),
        sa.Column("reason_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("selected_implementer", sa.String(length=64), nullable=True),
        sa.Column("concurrency_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("capacity_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("orchestration_runs.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("scheduler_decision_records")
    op.drop_table("work_queue_snapshots")
