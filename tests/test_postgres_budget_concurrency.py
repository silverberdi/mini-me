"""Regression checks that Mini Me no longer persists artificial provider caps."""

from minime.db.models import Base


def test_openrouter_project_budget_policy_is_not_in_postgres_metadata():
    assert "openrouter_budget_policies" not in Base.metadata.tables
    assert "openrouter_drain_allowed" not in Base.metadata.tables["projects"].columns
    assert "openrouter_pricing_snapshots" in Base.metadata.tables
    assert "budget_ledger" in Base.metadata.tables
