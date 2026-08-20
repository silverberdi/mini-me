"""003 review pipeline tables

Revision ID: 003_review_pipeline
Revises: 002_jobs_pipeline
Create Date: 2026-08-20 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_review_pipeline"
down_revision: Union[str, None] = "002_jobs_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("change_name", sa.String(length=128), nullable=False),
        sa.Column("reviewer_role", sa.String(length=64), nullable=False),
        sa.Column("candidate_sha", sa.String(length=64), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reviews_job_id", "reviews", ["job_id"])
    op.create_index("ix_reviews_project_id", "reviews", ["project_id"])
    op.create_index("ix_reviews_change_name", "reviews", ["change_name"])
    op.create_index("ix_reviews_status", "reviews", ["status"])
    op.create_index("ix_reviews_verdict", "reviews", ["verdict"])
    op.create_index("ix_reviews_created_at", "reviews", ["created_at"])

    op.create_table(
        "review_findings",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "review_id",
            sa.String(length=64),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("violated_requirement", sa.Text(), nullable=False),
        sa.Column("expected_correction", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_review_findings_review_id", "review_findings", ["review_id"])
    op.create_index("ix_review_findings_severity", "review_findings", ["severity"])
    op.create_index("ix_review_findings_created_at", "review_findings", ["created_at"])


def downgrade() -> None:
    op.drop_table("review_findings")
    op.drop_table("reviews")
