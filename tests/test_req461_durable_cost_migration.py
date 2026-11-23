"""Regression tests for retry-safe req-461 schema changes."""

import importlib.util
from pathlib import Path


_PATH = Path(__file__).parents[1] / "alembic/versions/req461_durable_cost_settlement.py"
_SPEC = importlib.util.spec_from_file_location("req461_durable_cost_settlement", _PATH)
migration = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(migration)


class _Inspector:
    def __init__(self, columns, constraints):
        self.columns = columns
        self.constraints = constraints

    def get_columns(self, _table):
        return [{"name": name} for name in self.columns]

    def get_unique_constraints(self, _table):
        return [{"name": name} for name in self.constraints]


class _Op:
    def __init__(self):
        self.calls = []

    def get_bind(self):
        return object()

    def add_column(self, *args):
        self.calls.append(("add_column", args))

    def create_unique_constraint(self, *args):
        self.calls.append(("create_unique_constraint", args))


def test_migration_helpers_detect_existing_columns_and_constraint(monkeypatch):
    inspector = _Inspector(
        {"usage_identity", "source", "observed_at"},
        {"uq_budget_ledger_usage_identity"},
    )
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)

    assert migration._column_names(object()) == {"usage_identity", "source", "observed_at"}
    assert migration._unique_constraint_names(object()) == {"uq_budget_ledger_usage_identity"}


def test_upgrade_skips_all_ddl_when_req461_schema_is_already_present(monkeypatch):
    inspector = _Inspector(
        {"usage_identity", "source", "observed_at"},
        {"uq_budget_ledger_usage_identity"},
    )
    operations = _Op()
    monkeypatch.setattr(migration.op, "get_bind", operations.get_bind)
    monkeypatch.setattr(migration.op, "add_column", operations.add_column)
    monkeypatch.setattr(migration.op, "create_unique_constraint", operations.create_unique_constraint)
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)

    migration.upgrade()

    assert operations.calls == []
