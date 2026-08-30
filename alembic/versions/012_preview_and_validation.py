"""012 container preview and guided validation persistence."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_preview_and_validation"
down_revision: Union[str, None] = "011_governance_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table("validation_runs")
    op.drop_table("preview_sessions")
