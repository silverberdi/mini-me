"""add recovery claims, recovery decisions, and external action attempts

Revision ID: g01_recovery_convergence
Revises: d04_durable_sagas
Create Date: 2026-10-01 22:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'g01_recovery_convergence'
down_revision: Union[str, None] = 'd04_durable_sagas'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. create recovery_claims table
    op.create_table(
        'recovery_claims',
        sa.Column('claim_key', sa.String(length=255), nullable=False),
        sa.Column('fence_token', sa.BigInteger(), server_default='1', nullable=False),
        sa.Column('owner_instance_id', sa.String(length=128), nullable=False),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_decision_id', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('claim_key'),
    )
    op.create_index('ix_recovery_claims_lease_expires_at', 'recovery_claims', ['lease_expires_at'], unique=False)
    op.create_index('ix_recovery_claims_owner_instance_id', 'recovery_claims', ['owner_instance_id'], unique=False)

    # 2. create recovery_decisions table
    op.create_table(
        'recovery_decisions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('cycle_id', sa.String(length=64), nullable=False),
        sa.Column('claim_key', sa.String(length=255), nullable=False),
        sa.Column('identity_type', sa.String(length=64), nullable=False),
        sa.Column('identity_id', sa.String(length=255), nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=True),
        sa.Column('change_name', sa.String(length=128), nullable=True),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('prior_checkpoint', sa.JSON(), nullable=False),
        sa.Column('observation_refs', sa.JSON(), nullable=False),
        sa.Column('classification', sa.String(length=64), nullable=False),
        sa.Column('planned_action', sa.String(length=64), nullable=False),
        sa.Column('fence_token', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.String(length=64), server_default='PLANNED', nullable=False),
        sa.Column('result_payload', sa.JSON(), nullable=False),
        sa.Column('reason_code', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cycle_id', 'claim_key', name='uq_recovery_decisions_cycle_claim'),
    )
    op.create_index('ix_recovery_decisions_cycle_id', 'recovery_decisions', ['cycle_id'], unique=False)
    op.create_index('ix_recovery_decisions_claim_key', 'recovery_decisions', ['claim_key'], unique=False)

    # 3. create external_action_attempts table
    op.create_table(
        'external_action_attempts',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('action_key', sa.String(length=128), nullable=False),
        sa.Column('claim_key', sa.String(length=255), nullable=False),
        sa.Column('fence_token', sa.BigInteger(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), server_default='1', nullable=False),
        sa.Column('dispatch_intent_key', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='EXECUTING', nullable=False),
        sa.Column('result_payload', sa.JSON(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['action_key'], ['orchestration_external_actions.action_key'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dispatch_intent_key', name='uq_external_action_dispatch_intent'),
    )
    op.create_index('ix_external_action_attempts_action_key', 'external_action_attempts', ['action_key'], unique=False)

    # 4. update orchestration_external_actions table
    op.add_column('orchestration_external_actions', sa.Column('last_claim_key', sa.String(length=255), nullable=True))
    op.add_column('orchestration_external_actions', sa.Column('last_fence_token', sa.BigInteger(), nullable=True))
    op.add_column('orchestration_external_actions', sa.Column('last_dispatch_intent_id', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('orchestration_external_actions', 'last_dispatch_intent_id')
    op.drop_column('orchestration_external_actions', 'last_fence_token')
    op.drop_column('orchestration_external_actions', 'last_claim_key')

    op.drop_index('ix_external_action_attempts_action_key', table_name='external_action_attempts')
    op.drop_table('external_action_attempts')

    op.drop_index('ix_recovery_decisions_claim_key', table_name='recovery_decisions')
    op.drop_index('ix_recovery_decisions_cycle_id', table_name='recovery_decisions')
    op.drop_table('recovery_decisions')

    op.drop_index('ix_recovery_claims_owner_instance_id', table_name='recovery_claims')
    op.drop_index('ix_recovery_claims_lease_expires_at', table_name='recovery_claims')
    op.drop_table('recovery_claims')
