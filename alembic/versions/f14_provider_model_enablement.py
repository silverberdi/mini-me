"""Add independent operator enablement to provider model entries."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f14_provider_model_enablement"
down_revision: Union[str, None] = "f13_provider_model_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "provider_model_registry",
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("provider_model_registry", "is_enabled")
