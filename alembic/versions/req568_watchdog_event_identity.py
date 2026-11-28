"""Key Watchdog diagnoses by event identity within a candidate transition."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "req568_watchdog_event_identity"
down_revision: Union[str, None] = "req552_global_mcp_connections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("watchdog_diagnoses")}
    if "event_identity" not in columns:
        op.add_column("watchdog_diagnoses", sa.Column("event_identity", sa.String(128), nullable=True))
    if "transition_key" not in columns:
        op.add_column("watchdog_diagnoses", sa.Column("transition_key", sa.String(255), nullable=True))

    op.execute(
        sa.text(
            "UPDATE watchdog_diagnoses "
            "SET event_identity = COALESCE(evidence ->> 'event_identity', id), "
            "transition_key = evidence ->> 'sre_intervention_transition_key' "
            "WHERE event_identity IS NULL"
        )
    )
    constraints = {
        item["name"] for item in inspector.get_unique_constraints("watchdog_diagnoses") if item.get("name")
    }
    if "uq_watchdog_run_stage_generation" in constraints:
        op.drop_constraint("uq_watchdog_run_stage_generation", "watchdog_diagnoses", type_="unique")
    if "uq_watchdog_run_stage_generation_event" not in constraints:
        op.create_unique_constraint(
            "uq_watchdog_run_stage_generation_event",
            "watchdog_diagnoses",
            ["run_id", "stage", "candidate_generation", "event_identity"],
        )
    op.alter_column("watchdog_diagnoses", "event_identity", nullable=False)
    op.create_index("ix_watchdog_diagnoses_event_identity", "watchdog_diagnoses", ["event_identity"], if_not_exists=True)
    op.create_index("ix_watchdog_diagnoses_transition_key", "watchdog_diagnoses", ["transition_key"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_watchdog_diagnoses_transition_key", table_name="watchdog_diagnoses", if_exists=True)
    op.drop_index("ix_watchdog_diagnoses_event_identity", table_name="watchdog_diagnoses", if_exists=True)
    op.drop_constraint("uq_watchdog_run_stage_generation_event", "watchdog_diagnoses", type_="unique")
    op.create_unique_constraint(
        "uq_watchdog_run_stage_generation", "watchdog_diagnoses", ["run_id", "stage", "candidate_generation"]
    )
    op.drop_column("watchdog_diagnoses", "transition_key")
    op.drop_column("watchdog_diagnoses", "event_identity")
