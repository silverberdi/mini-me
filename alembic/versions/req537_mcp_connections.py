"""Project-scoped MCP connections and observed capabilities.

Revision ID: req537_mcp_connections
Revises: req466_project_test_database_profile
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "req537_mcp_connections"
down_revision: Union[str, None] = "watchdog_518_component"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mcp_connections",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("endpoint", sa.String(1024), nullable=False),
        sa.Column("transport", sa.String(16), nullable=False),
        sa.Column("auth_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=True),
        sa.Column("diagnostic_code", sa.String(64), nullable=True),
        sa.Column("diagnostic_summary", sa.Text(), nullable=True),
        sa.Column("oauth_state_hash", sa.String(128), nullable=True),
        sa.Column("oauth_state_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("project_id", "endpoint", name="uq_mcp_connection_project_endpoint"),
        sa.CheckConstraint("transport IN ('http', 'sse', 'stdio')", name="ck_mcp_connection_transport"),
        sa.CheckConstraint("auth_type IN ('oauth2', 'api_key', 'bearer')", name="ck_mcp_connection_auth_type"),
        sa.CheckConstraint("status IN ('PENDING', 'ACTIVE', 'ERROR', 'DISCONNECTED', 'REVOKED')", name="ck_mcp_connection_status"),
    )
    op.create_index("ix_mcp_connections_project_status", "mcp_connections", ["project_id", "status"])
    op.create_table(
        "mcp_capabilities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("connection_id", sa.String(64), sa.ForeignKey("mcp_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("connection_id", "kind", "name", name="uq_mcp_capability_identity"),
        sa.CheckConstraint("kind IN ('tool', 'resource')", name="ck_mcp_capability_kind"),
    )
    op.create_index("ix_mcp_capabilities_connection_id", "mcp_capabilities", ["connection_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_capabilities_connection_id", table_name="mcp_capabilities")
    op.drop_table("mcp_capabilities")
    op.drop_index("ix_mcp_connections_project_status", table_name="mcp_connections")
    op.drop_table("mcp_connections")
