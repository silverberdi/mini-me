"""Add project lifecycle-gate policy fields.

Revision ID: 022_strict_openspec_lifecycle_governance
Revises: 021_provider_probe_cooldown_state
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022_strict_openspec_lifecycle_governance"
down_revision: Union[str, None] = "021_provider_probe_cooldown_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name in ("strict_validation_required", "verify_gate_required", "sync_gate_required", "archive_gate_required"):
        op.add_column("projects", sa.Column(name, sa.Boolean(), server_default=sa.text("true"), nullable=False))


def downgrade() -> None:
    for name in ("archive_gate_required", "sync_gate_required", "verify_gate_required", "strict_validation_required"):
        op.drop_column("projects", name)
