"""managed repository runtime isolation tables

Revision ID: c03_managed_repo_isolation
Revises: b02_fail_closed_external_evidence
Create Date: 2026-09-21 22:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c03_managed_repo_isolation'
down_revision: Union[str, None] = '024_task_classification_snapshots'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. project_managed_repository_bindings
    op.create_table(
        'project_managed_repository_bindings',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('canonical_repository_identity', sa.String(length=255), nullable=False),
        sa.Column('remote_name', sa.String(length=64), server_default='origin', nullable=False),
        sa.Column('managed_repository_root', sa.String(length=512), nullable=False),
        sa.Column('worktree_parent_dir', sa.String(length=512), nullable=False),
        sa.Column('default_base_branch', sa.String(length=128), server_default='main', nullable=False),
        sa.Column('ownership_marker_filename', sa.String(length=128), server_default='.minime-managed-project.json', nullable=False),
        sa.Column('is_valid', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('mismatch_reasons', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', name='uq_project_managed_repository_binding_project_id')
    )
    op.create_index('ix_project_managed_repository_bindings_project_id', 'project_managed_repository_bindings', ['project_id'], unique=True)
    op.create_index('ix_pmrb_canonical_repo_id', 'project_managed_repository_bindings', ['canonical_repository_identity'], unique=False)

    # 2. orchestration_worktree_ownerships
    op.create_table(
        'orchestration_worktree_ownerships',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('job_id', sa.String(length=64), nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('change_name', sa.String(length=128), nullable=False),
        sa.Column('canonical_worktree_path', sa.String(length=512), nullable=False),
        sa.Column('source_repository_identity', sa.String(length=255), nullable=False),
        sa.Column('source_base_sha', sa.String(length=64), nullable=False),
        sa.Column('branch', sa.String(length=128), nullable=False),
        sa.Column('creation_state', sa.String(length=32), server_default='PENDING', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('canonical_worktree_path', name='uq_orchestration_worktree_ownership_path')
    )
    op.create_index('ix_orchestration_worktree_ownerships_project_id', 'orchestration_worktree_ownerships', ['project_id'], unique=False)
    op.create_index('ix_orchestration_worktree_ownerships_job_id', 'orchestration_worktree_ownerships', ['job_id'], unique=False)
    op.create_index('ix_orchestration_worktree_ownerships_run_id', 'orchestration_worktree_ownerships', ['run_id'], unique=False)
    op.create_index('ix_owo_canonical_worktree_path', 'orchestration_worktree_ownerships', ['canonical_worktree_path'], unique=True)
    op.create_index('ix_orchestration_worktree_ownerships_creation_state', 'orchestration_worktree_ownerships', ['creation_state'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_orchestration_worktree_ownerships_creation_state', table_name='orchestration_worktree_ownerships')
    op.drop_index('ix_owo_canonical_worktree_path', table_name='orchestration_worktree_ownerships')
    op.drop_index('ix_orchestration_worktree_ownerships_run_id', table_name='orchestration_worktree_ownerships')
    op.drop_index('ix_orchestration_worktree_ownerships_job_id', table_name='orchestration_worktree_ownerships')
    op.drop_index('ix_orchestration_worktree_ownerships_project_id', table_name='orchestration_worktree_ownerships')
    op.drop_table('orchestration_worktree_ownerships')
    op.drop_index('ix_pmrb_canonical_repo_id', table_name='project_managed_repository_bindings')
    op.drop_index('ix_project_managed_repository_bindings_project_id', table_name='project_managed_repository_bindings')
    op.drop_table('project_managed_repository_bindings')
