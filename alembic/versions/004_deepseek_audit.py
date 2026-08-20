"""004 deepseek audit tables

Revision ID: 004_deepseek_audit
Revises: 003_review_pipeline
Create Date: 2026-08-20 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_deepseek_audit"
down_revision: Union[str, None] = "003_review_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audits",
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
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("candidate_sha", sa.String(length=64), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=False),
        sa.Column(
            "review_id",
            sa.String(length=64),
            sa.ForeignKey("reviews.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("review_verdict", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("risk", sa.String(length=16), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audits_job_id", "audits", ["job_id"])
    op.create_index("ix_audits_project_id", "audits", ["project_id"])
    op.create_index("ix_audits_change_name", "audits", ["change_name"])
    op.create_index("ix_audits_review_id", "audits", ["review_id"])
    op.create_index("ix_audits_status", "audits", ["status"])
    op.create_index("ix_audits_risk", "audits", ["risk"])
    op.create_index("ix_audits_created_at", "audits", ["created_at"])

    op.create_table(
        "audit_findings",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "audit_id",
            sa.String(length=64),
            sa.ForeignKey("audits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("file", sa.String(length=255), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_findings_audit_id", "audit_findings", ["audit_id"])
    op.create_index("ix_audit_findings_severity", "audit_findings", ["severity"])
    op.create_index("ix_audit_findings_category", "audit_findings", ["category"])
    op.create_index("ix_audit_findings_created_at", "audit_findings", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_findings")
    op.drop_table("audits")
