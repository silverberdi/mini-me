"""015 widen transition key on orchestration_stage_events.

Revision ID: 015_widen_transition_key
Revises: 014_autonomous_queue_work_selection
Create Date: 2026-09-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_widen_transition_key"
down_revision: Union[str, None] = "014_autonomous_queue_work_selection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "orchestration_stage_events",
        "transition_key",
        existing_type=sa.String(length=128),
        type_=sa.String(length=512),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "orchestration_stage_events",
        "transition_key",
        existing_type=sa.String(length=512),
        type_=sa.String(length=128),
        existing_nullable=True,
    )
