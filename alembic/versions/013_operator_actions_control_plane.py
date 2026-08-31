"""013 operator actions control plane persistence."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_operator_control_plane"
down_revision: Union[str, None] = "012_preview_and_validation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operator_action_records",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "action_request_id", sa.String(length=64), unique=True, nullable=False, index=True
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
        sa.Column(
            "job_id",
            sa.String(length=64),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("action_type", sa.String(length=64), nullable=False, index=True),
        sa.Column(
            "actor_identity", sa.String(length=128), nullable=False, server_default="operator"
        ),
        sa.Column("source_interface", sa.String(length=64), nullable=False, server_default="tui"),
        sa.Column("precondition_stage", sa.String(length=64), nullable=True),
        sa.Column("precondition_gate", sa.String(length=64), nullable=True),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="ACCEPTED", index=True
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("resulting_stage", sa.String(length=64), nullable=True),
        sa.Column("resulting_outcome", sa.String(length=64), nullable=True),
        sa.Column("resulting_gate", sa.String(length=64), nullable=True),
        sa.Column("evidence_reference", sa.String(length=255), nullable=True),
        sa.Column("parameters_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result_payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("operator_action_records")
