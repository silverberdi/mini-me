"""017 auth sessions and operators.

Revision ID: 017_auth_sessions_and_operators
Revises: 016_provider_efficiency_telemetry
Create Date: 2026-09-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017_auth_sessions_and_operators"
down_revision: Union[str, None] = "016_provider_efficiency_telemetry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create authorized_operators table
    op.create_table(
        "authorized_operators",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("email", sa.String(length=255), unique=True, nullable=False),
        sa.Column("google_sub", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_authorized_operators_email", "authorized_operators", ["email"]
    )
    op.create_index(
        "ix_authorized_operators_google_sub", "authorized_operators", ["google_sub"]
    )

    # 2. Create auth_sessions table
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("session_token_hash", sa.String(length=128), unique=True, nullable=False),
        sa.Column("operator_email", sa.String(length=255), nullable=False),
        sa.Column("google_sub", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_auth_sessions_token_hash", "auth_sessions", ["session_token_hash"]
    )
    op.create_index(
        "ix_auth_sessions_operator_email", "auth_sessions", ["operator_email"]
    )
    op.create_index(
        "ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"]
    )

    # 3. Create auth_audit_events table
    op.create_table(
        "auth_audit_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("operator_email", sa.String(length=255), nullable=True),
        sa.Column("google_sub", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_auth_audit_events_event_type", "auth_audit_events", ["event_type"]
    )
    op.create_index(
        "ix_auth_audit_events_operator_email", "auth_audit_events", ["operator_email"]
    )
    op.create_index(
        "ix_auth_audit_events_timestamp", "auth_audit_events", ["timestamp"]
    )


def downgrade() -> None:
    op.drop_table("auth_audit_events")
    op.drop_table("auth_sessions")
    op.drop_table("authorized_operators")
