"""add durable sagas and generalize external actions

Revision ID: d04_durable_sagas
Revises: c03_managed_repo_isolation
Create Date: 2026-09-28 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd04_durable_sagas'
down_revision: Union[str, None] = 'c03_managed_repo_isolation'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create durable_sagas table
    op.create_table(
        'durable_sagas',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('saga_type', sa.String(length=32), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('work_item_key', sa.String(length=255), nullable=False),
        sa.Column('change_name', sa.String(length=128), nullable=True),
        sa.Column('run_id', sa.String(length=64), nullable=True),
        sa.Column('job_id', sa.String(length=64), nullable=True),
        sa.Column('generation', sa.Integer(), server_default='1', nullable=False),
        sa.Column('current_phase', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='IN_PROGRESS', nullable=False),
        sa.Column('last_observed_outcome', sa.String(length=32), nullable=True),
        sa.Column('blocking_reason', sa.Text(), nullable=True),
        sa.Column('evidence_references', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['orchestration_runs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_durable_sagas_change_name', 'durable_sagas', ['change_name'], unique=False)
    op.create_index('ix_durable_sagas_created_at', 'durable_sagas', ['created_at'], unique=False)
    op.create_index('ix_durable_sagas_job_id', 'durable_sagas', ['job_id'], unique=False)
    op.create_index('ix_durable_sagas_project_id', 'durable_sagas', ['project_id'], unique=False)
    op.create_index('ix_durable_sagas_run_id', 'durable_sagas', ['run_id'], unique=False)
    op.create_index('ix_durable_sagas_saga_type', 'durable_sagas', ['saga_type'], unique=False)
    op.create_index('ix_durable_sagas_status', 'durable_sagas', ['status'], unique=False)
    op.create_index('ix_durable_sagas_work_item_key', 'durable_sagas', ['work_item_key'], unique=False)

    op.create_index(
        'uq_active_intake_saga',
        'durable_sagas',
        ['project_id', 'work_item_key'],
        unique=True,
        postgresql_where=sa.text("saga_type = 'INTAKE' AND status IN ('IN_PROGRESS', 'BLOCKED')"),
        sqlite_where=sa.text("saga_type = 'INTAKE' AND status IN ('IN_PROGRESS', 'BLOCKED')"),
    )
    op.create_index(
        'uq_active_closure_saga',
        'durable_sagas',
        ['project_id', 'work_item_key'],
        unique=True,
        postgresql_where=sa.text("saga_type = 'CLOSURE' AND status IN ('IN_PROGRESS', 'BLOCKED')"),
        sqlite_where=sa.text("saga_type = 'CLOSURE' AND status IN ('IN_PROGRESS', 'BLOCKED')"),
    )

    # 2. update orchestration_external_actions table
    op.add_column('orchestration_external_actions', sa.Column('saga_id', sa.String(length=64), nullable=True))
    op.create_foreign_key(
        'fk_orchestration_external_actions_saga_id',
        'orchestration_external_actions',
        'durable_sagas',
        ['saga_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_index('ix_orchestration_external_actions_saga_id', 'orchestration_external_actions', ['saga_id'], unique=False)
    op.alter_column('orchestration_external_actions', 'run_id', existing_type=sa.String(length=64), nullable=True)
    op.alter_column('orchestration_external_actions', 'candidate_sha', existing_type=sa.String(length=64), nullable=True)


def downgrade() -> None:
    op.alter_column('orchestration_external_actions', 'candidate_sha', existing_type=sa.String(length=64), nullable=False)
    op.alter_column('orchestration_external_actions', 'run_id', existing_type=sa.String(length=64), nullable=False)
    op.drop_index('ix_orchestration_external_actions_saga_id', table_name='orchestration_external_actions')
    op.drop_constraint('fk_orchestration_external_actions_saga_id', 'orchestration_external_actions', type_='foreignkey')
    op.drop_column('orchestration_external_actions', 'saga_id')

    op.drop_index('uq_active_closure_saga', table_name='durable_sagas')
    op.drop_index('uq_active_intake_saga', table_name='durable_sagas')
    op.drop_index('ix_durable_sagas_work_item_key', table_name='durable_sagas')
    op.drop_index('ix_durable_sagas_status', table_name='durable_sagas')
    op.drop_index('ix_durable_sagas_saga_type', table_name='durable_sagas')
    op.drop_index('ix_durable_sagas_run_id', table_name='durable_sagas')
    op.drop_index('ix_durable_sagas_project_id', table_name='durable_sagas')
    op.drop_index('ix_durable_sagas_job_id', table_name='durable_sagas')
    op.drop_index('ix_durable_sagas_created_at', table_name='durable_sagas')
    op.drop_index('ix_durable_sagas_change_name', table_name='durable_sagas')
    op.drop_table('durable_sagas')
