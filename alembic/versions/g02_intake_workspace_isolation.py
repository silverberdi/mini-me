"""add intake workspace ownership table and partial active indexes

Revision ID: g02_intake_workspace_isolation
Revises: g01_recovery_convergence
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'g02_intake_workspace_isolation'
down_revision: Union[str, None] = 'g01_recovery_convergence'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'intake_workspace_ownerships',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('item_key', sa.String(length=128), nullable=False),
        sa.Column('saga_id', sa.String(length=64), nullable=False),
        sa.Column('change_name', sa.String(length=128), nullable=False),
        sa.Column('canonical_workspace_path', sa.String(length=512), nullable=False),
        sa.Column('canonical_repository_identity', sa.String(length=255), nullable=False),
        sa.Column('base_sha', sa.String(length=64), nullable=False),
        sa.Column('head_sha', sa.String(length=64), nullable=True),
        sa.Column('creation_state', sa.String(length=32), server_default='RESERVED', nullable=False),
        sa.Column('publication_state', sa.String(length=32), server_default='UNPUBLISHED', nullable=False),
        sa.Column('published_ref', sa.String(length=255), nullable=True),
        sa.Column('published_sha', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_intake_workspace_ownerships_project_id', 'intake_workspace_ownerships', ['project_id'], unique=False)
    op.create_index('ix_intake_workspace_ownerships_item_key', 'intake_workspace_ownerships', ['item_key'], unique=False)
    op.create_index('ix_intake_workspace_ownerships_saga_id', 'intake_workspace_ownerships', ['saga_id'], unique=False)
    op.create_index('ix_intake_workspace_ownerships_canonical_workspace_path', 'intake_workspace_ownerships', ['canonical_workspace_path'], unique=False)
    op.create_index('ix_intake_workspace_ownerships_creation_state', 'intake_workspace_ownerships', ['creation_state'], unique=False)
    op.create_index('ix_intake_workspace_ownerships_publication_state', 'intake_workspace_ownerships', ['publication_state'], unique=False)

    op.create_index(
        'uq_intake_workspace_active_item',
        'intake_workspace_ownerships',
        ['project_id', 'item_key'],
        unique=True,
        postgresql_where=sa.text("creation_state IN ('RESERVED', 'CREATING', 'ACTIVE')"),
        sqlite_where=sa.text("creation_state IN ('RESERVED', 'CREATING', 'ACTIVE')"),
    )
    op.create_index(
        'uq_intake_workspace_active_path',
        'intake_workspace_ownerships',
        ['canonical_workspace_path'],
        unique=True,
        postgresql_where=sa.text("creation_state IN ('RESERVED', 'CREATING', 'ACTIVE')"),
        sqlite_where=sa.text("creation_state IN ('RESERVED', 'CREATING', 'ACTIVE')"),
    )
    op.create_index(
        'uq_intake_workspace_active_saga',
        'intake_workspace_ownerships',
        ['saga_id'],
        unique=True,
        postgresql_where=sa.text("creation_state IN ('RESERVED', 'CREATING', 'ACTIVE')"),
        sqlite_where=sa.text("creation_state IN ('RESERVED', 'CREATING', 'ACTIVE')"),
    )


def downgrade() -> None:
    op.drop_index('uq_intake_workspace_active_saga', table_name='intake_workspace_ownerships')
    op.drop_index('uq_intake_workspace_active_path', table_name='intake_workspace_ownerships')
    op.drop_index('uq_intake_workspace_active_item', table_name='intake_workspace_ownerships')
    op.drop_index('ix_intake_workspace_ownerships_publication_state', table_name='intake_workspace_ownerships')
    op.drop_index('ix_intake_workspace_ownerships_creation_state', table_name='intake_workspace_ownerships')
    op.drop_index('ix_intake_workspace_ownerships_canonical_workspace_path', table_name='intake_workspace_ownerships')
    op.drop_index('ix_intake_workspace_ownerships_saga_id', table_name='intake_workspace_ownerships')
    op.drop_index('ix_intake_workspace_ownerships_item_key', table_name='intake_workspace_ownerships')
    op.drop_index('ix_intake_workspace_ownerships_project_id', table_name='intake_workspace_ownerships')
    op.drop_table('intake_workspace_ownerships')
