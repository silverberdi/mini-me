"""Focused unit checks for migration reconciliation guards."""

import importlib.util
from pathlib import Path

import pytest

_MIGRATION_PATH = Path(__file__).parents[1] / "alembic/versions/008b_change_identity.py"
_SPEC = importlib.util.spec_from_file_location("change_identity_migration", _MIGRATION_PATH)
migration = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(migration)


def row(**values):
    return {
        "id": "row-id",
        "project_id": "mini-me",
        "name": "synthetic",
        "status": "DISCOVERED",
        "last_readiness_status": "NOT_READY",
        **values,
    }


def test_migration_allows_nullable_stage():
    assert "stage" not in migration._REQUIRED_FIELDS
    migration._validate_consistency(row(stage=None))


def test_migration_rejects_contradictory_ready_state():
    with pytest.raises(RuntimeError, match="project_id=.*status='READY'.*readiness='NOT_READY'"):
        migration._validate_consistency(row(status="READY", last_readiness_status="NOT_READY"))
