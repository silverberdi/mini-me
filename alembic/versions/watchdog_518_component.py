"""Record the affected component for Watchdog recurrence summaries."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "watchdog_518_component"
down_revision: Union[str, None] = "watchdog_518_sre"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "watchdog_diagnoses",
        sa.Column(
            "affected_component",
            sa.String(128),
            nullable=False,
            server_default="orchestration",
        ),
    )
    op.create_index(
        "ix_watchdog_diagnoses_affected_component",
        "watchdog_diagnoses",
        ["affected_component"],
    )


def downgrade() -> None:
    op.drop_index("ix_watchdog_diagnoses_affected_component", table_name="watchdog_diagnoses")
    op.drop_column("watchdog_diagnoses", "affected_component")
