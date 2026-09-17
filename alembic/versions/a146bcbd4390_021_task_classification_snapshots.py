"""021 task classification snapshots.

Provisional migration. The authored proposal expected revision 022
after provider-execution-safety-stabilization (021). This is 021
against the current base. Before merge, this must be reconciled
after stabilization lands.

Revision ID: 021_task_classification_snapshots
Revises: 020_autonomous_intake_admission_policy
Create Date: 2026-09-08
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021_task_classification_snapshots"
down_revision: Union[str, None] = "020_autonomous_intake_admission_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_classification_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "change_id",
            sa.String(64),
            sa.ForeignKey("changes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "job_id",
            sa.String(64),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("classifier_version", sa.String(16), nullable=False),
        sa.Column("complexity", sa.String(16), nullable=False),
        sa.Column(
            "risk_profile",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("surface_kind", sa.String(32), nullable=False),
        sa.Column(
            "surface_details",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "signals",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "rule_identifiers",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("evidence_source", sa.String(32), nullable=False),
        sa.Column("classification_completeness", sa.String(16), nullable=False),
        sa.Column(
            "missing_signals",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "pre_execution_snapshot_id",
            sa.String(64),
            sa.ForeignKey("task_classification_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "composite_surface",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "breadth_mismatch_detected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_legacy",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_index(
        "ix_task_classification_snapshots_change_id",
        "task_classification_snapshots",
        ["change_id"],
    )
    op.create_index(
        "ix_task_classification_snapshots_job_id",
        "task_classification_snapshots",
        ["job_id"],
    )
    op.create_index(
        "ix_task_classification_snapshots_pre_execution_snapshot_id",
        "task_classification_snapshots",
        ["pre_execution_snapshot_id"],
    )
    op.create_index(
        "ix_task_classification_snapshots_created_at",
        "task_classification_snapshots",
        ["created_at"],
    )

    op.add_column(
        "changes",
        sa.Column(
            "latest_classification_snapshot_id",
            sa.String(64),
            sa.ForeignKey("task_classification_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.add_column(
        "jobs",
        sa.Column(
            "classification_snapshot_id",
            sa.String(64),
            sa.ForeignKey("task_classification_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "classification_snapshot_id")
    op.drop_column("changes", "latest_classification_snapshot_id")
    op.drop_index(
        "ix_task_classification_snapshots_created_at",
        table_name="task_classification_snapshots",
    )
    op.drop_index(
        "ix_task_classification_snapshots_pre_execution_snapshot_id",
        table_name="task_classification_snapshots",
    )
    op.drop_index(
        "ix_task_classification_snapshots_job_id",
        table_name="task_classification_snapshots",
    )
    op.drop_index(
        "ix_task_classification_snapshots_change_id",
        table_name="task_classification_snapshots",
    )
    op.drop_table("task_classification_snapshots")