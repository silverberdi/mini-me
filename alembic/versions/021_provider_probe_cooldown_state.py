"""021 provider probe cooldown state.

Revision ID: 021_provider_probe_cooldown_state
Revises: 020_autonomous_intake_admission_policy
Create Date: 2026-09-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021_provider_probe_cooldown_state"
down_revision: Union[str, None] = "020_autonomous_intake_admission_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "provider_health",
        sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "provider_health",
        sa.Column(
            "consecutive_probe_failures",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "provider_health",
        sa.Column("probe_window_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "provider_health",
        sa.Column(
            "probe_count_in_window",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("provider_health", "probe_count_in_window")
    op.drop_column("provider_health", "probe_window_started_at")
    op.drop_column("provider_health", "consecutive_probe_failures")
    op.drop_column("provider_health", "last_probe_at")
