"""Deduplicate changes and enforce project/name logical identity.

The upgrade keeps the earliest physical row in each duplicate group, copies the
most authoritative mutable state to it, and removes redundant rows.  Downgrade
is schema-only: deleted duplicate rows are intentionally not recreated.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "008b_change_identity"
down_revision: Union[str, None] = "008_autonomous_orchestration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_REQUIRED_FIELDS = (
    "id",
    "project_id",
    "name",
    "status",
    "schema_name",
    "specs_paths",
    "last_readiness_status",
    "last_readiness_reasons",
    "discovered_at",
    "updated_at",
)


_VALID_READINESS_BY_STATUS = {
    "DISCOVERED": {"NOT_READY"},
    "READY": {"READY"},
    # These lifecycle states represent work that passed readiness; BLOCKED has
    # its own explicit readiness state in the domain model.
    "IN_PROGRESS": {"READY"},
    "DONE": {"READY"},
    "CANCELLED": {"READY"},
    "BLOCKED": {"BLOCKED"},
}


def _validate_consistency(row: sa.RowMapping) -> None:
    status = row["status"]
    readiness = row["last_readiness_status"]
    if readiness not in _VALID_READINESS_BY_STATUS.get(status, set()):
        raise RuntimeError(
            "Cannot reconcile contradictory Change state: "
            f"project_id={row['project_id']!r}, name={row['name']!r}, id={row['id']!r}, "
            f"status={status!r}, readiness={readiness!r}"
        )


def _quality(row: sa.RowMapping) -> int:
    return int(row["status"] == "READY" and row["last_readiness_status"] == "READY")


def upgrade() -> None:
    if context.is_offline_mode():
        op.create_unique_constraint("uq_changes_project_name", "changes", ["project_id", "name"])
        return
    connection = op.get_bind()
    rows = (
        connection.execute(
            sa.text(
                "SELECT id, project_id, name, status, stage, schema_name, proposal_path, "
                "tasks_path, design_path, specs_paths, last_readiness_status, "
                "last_readiness_reasons, discovered_at, updated_at "
                "FROM changes ORDER BY project_id, name, discovered_at, id"
            )
        )
        .mappings()
        .all()
    )

    groups: dict[tuple[str, str], list[sa.RowMapping]] = {}
    for row in rows:
        if any(row[field] is None for field in _REQUIRED_FIELDS):
            raise RuntimeError(
                f"Cannot reconcile changes row {row.get('id')!r}: required data is NULL"
            )
        _validate_consistency(row)
        groups.setdefault((row["project_id"], row["name"]), []).append(row)

    update_sql = sa.text(
        "UPDATE changes SET status = :status, stage = :stage, schema_name = :schema_name, "
        "proposal_path = :proposal_path, tasks_path = :tasks_path, design_path = :design_path, "
        "specs_paths = :specs_paths, last_readiness_status = :last_readiness_status, "
        "last_readiness_reasons = :last_readiness_reasons, discovered_at = :discovered_at, "
        "updated_at = :updated_at WHERE id = :survivor_id"
    ).bindparams(
        sa.bindparam("specs_paths", type_=sa.JSON),
        sa.bindparam("last_readiness_reasons", type_=sa.JSON),
    )
    delete_sql = sa.text("DELETE FROM changes WHERE id = :id")

    for (project_id, name), group in groups.items():
        if len(group) < 2:
            continue
        survivor = min(group, key=lambda row: (row["discovered_at"], row["id"]))
        authoritative = max(
            group,
            key=lambda row: (
                _quality(row),
                row["updated_at"],
            ),
        )
        tied = [
            row
            for row in group
            if (
                _quality(row) == _quality(authoritative)
                and row["updated_at"] == authoritative["updated_at"]
            )
        ]
        authoritative = min(tied, key=lambda row: row["id"])
        connection.execute(
            update_sql,
            {
                "survivor_id": survivor["id"],
                "status": authoritative["status"],
                "stage": authoritative["stage"],
                "schema_name": authoritative["schema_name"],
                "proposal_path": authoritative["proposal_path"],
                "tasks_path": authoritative["tasks_path"],
                "design_path": authoritative["design_path"],
                "specs_paths": authoritative["specs_paths"],
                "last_readiness_status": authoritative["last_readiness_status"],
                "last_readiness_reasons": authoritative["last_readiness_reasons"],
                "discovered_at": survivor["discovered_at"],
                "updated_at": authoritative["updated_at"],
            },
        )
        for row in group:
            if row["id"] != survivor["id"]:
                connection.execute(delete_sql, {"id": row["id"]})

    op.create_unique_constraint("uq_changes_project_name", "changes", ["project_id", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_changes_project_name", "changes", type_="unique")
