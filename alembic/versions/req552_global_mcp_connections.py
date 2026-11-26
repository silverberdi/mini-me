"""Allow organization-wide MCP connections.

Revision ID: req552_global_mcp_connections
Revises: req537_mcp_connections
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "req552_global_mcp_connections"
down_revision: Union[str, None] = "req537_mcp_connections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("mcp_connections", "project_id", existing_type=sa.String(length=64), nullable=True)
    op.create_index(
        "uq_mcp_connection_global_endpoint",
        "mcp_connections",
        ["endpoint"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
        sqlite_where=sa.text("project_id IS NULL"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_global_rows = connection.execute(
        sa.text("SELECT 1 FROM mcp_connections WHERE project_id IS NULL LIMIT 1")
    ).first()
    if has_global_rows:
        raise RuntimeError(
            "Cannot downgrade global MCP connections while global rows exist; remove them first."
        )
    op.drop_index("uq_mcp_connection_global_endpoint", table_name="mcp_connections")
    op.alter_column("mcp_connections", "project_id", existing_type=sa.String(length=64), nullable=False)
