"""Add the minimal project-scoped F2 configuration document.

Revision ID: f2_project_configuration
Revises: gacela01_retire_legacy_admission_state
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2_project_configuration"
down_revision: Union[str, None] = "gacela01_retire_legacy_admission_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "projects",
        "onboarding_status",
        existing_type=sa.String(32),
        server_default="CONFIGURED",
    )
    op.add_column(
        "projects",
        sa.Column("project_type", sa.String(16), nullable=False, server_default="BROWNFIELD"),
    )
    op.add_column(
        "projects",
        sa.Column("provider_connections", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "projects",
        sa.Column("agent_profiles", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "projects",
        sa.Column("execution_policy", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "projects",
        sa.Column("onboarding_checkpoint", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.execute(
        """
        UPDATE projects
        SET onboarding_checkpoint = json_build_object(
                'f2_previous_onboarding_status', onboarding_status,
                'f2_previous_onboarding_reasons', onboarding_reasons
            ),
            onboarding_status = CASE
                WHEN onboarding_status = 'READY_FOR_WORK' THEN 'CONFIGURED'
                ELSE onboarding_status
            END,
            onboarding_reasons = CASE
                WHEN onboarding_status = 'READY_FOR_WORK' THEN
                    (COALESCE(onboarding_reasons::jsonb, '[]'::jsonb)
                     || '["Legacy readiness requires F2 identity and capability evidence"]'::jsonb)::json
                ELSE onboarding_reasons
            END
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE projects
        SET onboarding_status = COALESCE(
                onboarding_checkpoint->>'f2_previous_onboarding_status', onboarding_status
            ),
            onboarding_reasons = COALESCE(
                (onboarding_checkpoint->'f2_previous_onboarding_reasons')::json,
                onboarding_reasons
            )
        """
    )
    op.drop_column("projects", "onboarding_checkpoint")
    op.drop_column("projects", "execution_policy")
    op.drop_column("projects", "agent_profiles")
    op.drop_column("projects", "provider_connections")
    op.drop_column("projects", "project_type")
    op.alter_column(
        "projects",
        "onboarding_status",
        existing_type=sa.String(32),
        server_default="READY_FOR_WORK",
    )
