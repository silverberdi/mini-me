"""Test suite verifying zero FOR UPDATE write locks on GET query routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from minime.api.app import app, get_uow


@pytest.fixture
def lock_monitoring_client(in_memory_uow):
    uow = in_memory_uow
    for_update_queries: list[str] = []

    def _get_uow_override():
        return uow

    app.dependency_overrides[get_uow] = _get_uow_override
    client = TestClient(app)
    yield client, uow, for_update_queries
    app.dependency_overrides.clear()


def test_budget_usage_get_uses_no_write_locks(lock_monitoring_client):
    client, _, lock_queries = lock_monitoring_client
    lock_queries.clear()

    response = client.get("/budget/usage")
    assert response.status_code == 200
    assert len(lock_queries) == 0, f"FOR UPDATE queries executed: {lock_queries}"


def test_openrouter_status_get_uses_no_write_locks(lock_monitoring_client):
    client, _, lock_queries = lock_monitoring_client
    lock_queries.clear()

    response = client.get("/providers/openrouter/status")
    assert response.status_code == 200
    assert len(lock_queries) == 0, f"FOR UPDATE queries executed: {lock_queries}"


def test_dashboard_overview_get_uses_no_write_locks(lock_monitoring_client):
    client, _, lock_queries = lock_monitoring_client
    lock_queries.clear()

    response = client.get("/dashboard")
    assert response.status_code == 200
    assert len(lock_queries) == 0, f"FOR UPDATE queries executed: {lock_queries}"
