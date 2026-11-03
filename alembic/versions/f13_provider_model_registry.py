"""Create the canonical provider/model registry without touching legacy tables."""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f13_provider_model_registry"
down_revision: Union[str, None] = "f11_push_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_model_registry",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("harness_id", sa.String(128), nullable=False),
        sa.Column("canonical_model_id", sa.String(255), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("max_context_tokens", sa.Integer(), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("discovery_status", sa.String(16), nullable=False),
        sa.Column("diagnostic_code", sa.String(64), nullable=True),
        sa.Column("diagnostic_summary", sa.Text(), nullable=True),
        sa.Column("observed_cli_version", sa.String(128), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_id", "harness_id", "canonical_model_id", name="uq_provider_model_registry_identity"),
        sa.CheckConstraint("origin IN ('static', 'discovered', 'custom')", name="ck_provider_model_registry_origin"),
        sa.CheckConstraint("discovery_status IN ('available', 'unavailable', 'blocked')", name="ck_provider_model_registry_status"),
        sa.CheckConstraint("max_context_tokens IS NULL OR max_context_tokens >= 0", name="ck_provider_model_registry_context_nonnegative"),
        sa.CheckConstraint("version > 0", name="ck_provider_model_registry_version_positive"),
        sa.CheckConstraint("length(trim(canonical_model_id)) > 0", name="ck_provider_model_registry_model_nonempty"),
    )
    op.create_index("ix_provider_model_registry_status_updated", "provider_model_registry", ["discovery_status", "updated_at"])
    op.create_index("ix_provider_model_registry_origin_provider_harness", "provider_model_registry", ["origin", "provider_id", "harness_id"])
    # Idempotent metadata-only backfill. It never reads or writes project connections.
    op.execute(sa.text("""
        INSERT INTO provider_model_registry
          (id, provider_id, harness_id, canonical_model_id, origin, capabilities,
           discovery_status, diagnostic_code, diagnostic_summary, version, created_at, updated_at)
        VALUES
          ('static-deepseek-chat', 'deepseek', 'direct', 'deepseek-chat', 'static', '{"model_route":"direct"}'::jsonb,
           'unavailable', 'not_observed', 'Static compatibility metadata; refresh required', 1, now(), now()),
          ('static-deepseek-reasoner', 'deepseek', 'direct', 'deepseek-reasoner', 'static', '{"model_route":"direct"}'::jsonb,
           'unavailable', 'not_observed', 'Static compatibility metadata; refresh required', 1, now(), now()),
          ('static-opencode-deepseek-flash', 'deepseek', 'opencode', 'deepseek/deepseek-flash', 'static', '{"model_route":"deepseek_direct"}'::jsonb,
           'unavailable', 'not_observed', 'Static compatibility metadata; refresh required', 1, now(), now()),
          ('static-opencode-deepseek-v4-pro', 'deepseek', 'opencode', 'deepseek/deepseek-v4-pro', 'static', '{"model_route":"deepseek_direct"}'::jsonb,
           'unavailable', 'not_observed', 'Static compatibility metadata; refresh required', 1, now(), now()),
          ('static-opencode-openrouter-deepseek-r1', 'openrouter', 'opencode', 'openrouter/deepseek/deepseek-r1-0528', 'static', '{"model_route":"openrouter"}'::jsonb,
           'unavailable', 'not_observed', 'Static compatibility metadata; refresh required', 1, now(), now())
        ON CONFLICT (provider_id, harness_id, canonical_model_id) DO NOTHING
    """))


def downgrade() -> None:
    op.drop_index("ix_provider_model_registry_origin_provider_harness", table_name="provider_model_registry")
    op.drop_index("ix_provider_model_registry_status_updated", table_name="provider_model_registry")
    op.drop_table("provider_model_registry")
