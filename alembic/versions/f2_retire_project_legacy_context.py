"""Retire project-local context and GitHub Projects metadata superseded by F2."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2_retire_project_legacy_context"
down_revision: Union[str, None] = "f2_retire_project_admission_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop columns with no live F2/F3/F5 readers or writers."""
    op.drop_column("projects", "github_project_owner")
    op.drop_column("projects", "github_project_number")
    op.drop_column("projects", "backlog_path")
    op.drop_column("projects", "roadmap_path")
    op.drop_column("projects", "context_sources")


def downgrade() -> None:
    """Restore schema shape with safe defaults; backups restore old values."""
    op.add_column(
        "projects",
        sa.Column(
            "context_sources",
            sa.JSON(),
            server_default='["README.md", "docs/", "ROADMAP.md"]',
            nullable=False,
        ),
    )
    op.add_column(
        "projects",
        sa.Column("roadmap_path", sa.String(length=255), server_default="docs/ROADMAP.md", nullable=False),
    )
    op.add_column(
        "projects",
        sa.Column("backlog_path", sa.String(length=255), server_default="docs/ROADMAP.md", nullable=False),
    )
    op.add_column("projects", sa.Column("github_project_number", sa.Integer(), nullable=True))
    op.add_column(
        "projects", sa.Column("github_project_owner", sa.String(length=128), nullable=True)
    )
