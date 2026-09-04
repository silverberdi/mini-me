"""019 work intake and backlog items.

Revision ID: 019_work_intake_and_backlog_items
Revises: 018_widen_change_id_on_events
Create Date: 2026-09-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019_work_intake_and_backlog_items"
down_revision: Union[str, None] = "018_widen_change_id_on_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add onboarding and context columns to projects
    op.add_column(
        "projects",
        sa.Column(
            "context_sources",
            sa.JSON(),
            server_default='["README.md", "docs/", "ROADMAP.md"]',
            nullable=False,
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "roadmap_path", sa.String(length=255), server_default="docs/ROADMAP.md", nullable=False
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "backlog_path", sa.String(length=255), server_default="docs/ROADMAP.md", nullable=False
        ),
    )
    op.add_column(
        "projects",
        sa.Column("github_project_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("github_project_owner", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column(
            "onboarding_status",
            sa.String(length=32),
            server_default="READY_FOR_WORK",
            nullable=False,
        ),
    )
    op.add_column(
        "projects",
        sa.Column("onboarding_reasons", sa.JSON(), server_default="[]", nullable=False),
    )

    # 2. Create backlog_items table
    op.create_table(
        "backlog_items",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("item_key", sa.String(length=128), nullable=False, index=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("priority", sa.String(length=32), server_default="NORMAL", nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="BACKLOG", nullable=False, index=True
        ),
        sa.Column("source", sa.String(length=32), server_default="LOCAL_BACKLOG", nullable=False),
        sa.Column("source_location", sa.String(length=255), nullable=True),
        sa.Column("dependencies", sa.JSON(), server_default="[]", nullable=False),
        sa.Column(
            "readiness_state", sa.String(length=32), server_default="NOT_READY", nullable=False
        ),
        sa.Column("unmet_readiness_reasons", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("human_questions", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("human_answers", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("github_issue_number", sa.Integer(), nullable=True),
        sa.Column("github_issue_url", sa.String(length=512), nullable=True),
        sa.Column("github_project_item_id", sa.String(length=128), nullable=True),
        sa.Column("openspec_change_name", sa.String(length=128), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "item_key", name="uq_backlog_items_project_key"),
    )


def downgrade() -> None:
    op.drop_table("backlog_items")
    op.drop_column("projects", "onboarding_reasons")
    op.drop_column("projects", "onboarding_status")
    op.drop_column("projects", "github_project_owner")
    op.drop_column("projects", "github_project_number")
    op.drop_column("projects", "backlog_path")
    op.drop_column("projects", "roadmap_path")
    op.drop_column("projects", "context_sources")
