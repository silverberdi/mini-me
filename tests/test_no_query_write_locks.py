"""Test suite verifying zero FOR UPDATE write locks on GET query routes with real instrumentation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from minime.api.app import app, get_uow
from minime.domain.enums import ProjectStatus, ProviderHealthStatus
from minime.domain.models import Project, ProviderHealth, utc_now


@pytest.fixture
def lock_monitoring_client(in_memory_uow, tmp_path):
    uow = in_memory_uow
    for_update_queries: list[str] = []

    proj = Project(
        project_id="p-lock-test",
        display_name="Lock Test Project",
        repository="owner/repo",
        base_branch="main",
        status=ProjectStatus.ACTIVE,
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(proj)

    for prov in ["codex", "antigravity"]:
        uow.provider_health.save(
            ProviderHealth(
                health_id=f"ph-{prov}",
                provider=prov,
                status=ProviderHealthStatus.AVAILABLE,
                updated_at=utc_now(),
            )
        )
    uow.commit()

    # Wrap repository methods with real instrumentation spy
    orig_ph_for_update = uow.provider_health.get_by_provider_for_update

    def spy_ph_for_update(provider: str):
        for_update_queries.append(f"provider_health.get_by_provider_for_update({provider})")
        return orig_ph_for_update(provider)

    uow.provider_health.get_by_provider_for_update = spy_ph_for_update

    orig_budget_for_update = uow.budget_policies.get_for_update

    def spy_budget_for_update(project_id: str):
        for_update_queries.append(f"budget_policies.get_for_update({project_id})")
        return orig_budget_for_update(project_id)

    uow.budget_policies.get_for_update = spy_budget_for_update

    orig_saga_for_update = uow.durable_sagas.get_for_update

    def spy_saga_for_update(saga_id: str):
        for_update_queries.append(f"durable_sagas.get_for_update({saga_id})")
        return orig_saga_for_update(saga_id)

    uow.durable_sagas.get_for_update = spy_saga_for_update

    # Attach SQLAlchemy listener if bound
    session = getattr(uow, "session", None)
    if session is not None and hasattr(session, "bind") and session.bind is not None:
        from sqlalchemy import event

        def sqla_listener(conn, cursor, statement, parameters, context, executemany):
            if "FOR UPDATE" in statement.upper():
                for_update_queries.append(f"SQL: {statement}")

        event.listen(session.bind, "before_cursor_execute", sqla_listener)

    def _get_uow_override():
        return uow

    app.dependency_overrides[get_uow] = _get_uow_override
    client = TestClient(app)
    yield client, uow, for_update_queries, str(tmp_path)
    app.dependency_overrides.clear()


def test_budget_usage_get_uses_no_write_locks(lock_monitoring_client):
    client, _, lock_queries, _ = lock_monitoring_client
    lock_queries.clear()

    response = client.get("/budget/usage")
    assert response.status_code == 200
    assert len(lock_queries) == 0, f"FOR UPDATE queries executed: {lock_queries}"


def test_project_budget_get_uses_no_write_locks(lock_monitoring_client):
    client, _, lock_queries, _ = lock_monitoring_client
    lock_queries.clear()

    response = client.get("/projects/p-lock-test/budget")
    assert response.status_code == 200
    assert len(lock_queries) == 0, f"FOR UPDATE queries executed: {lock_queries}"


def test_openrouter_status_get_uses_no_write_locks(lock_monitoring_client):
    client, _, lock_queries, _ = lock_monitoring_client
    lock_queries.clear()

    response = client.get("/providers/openrouter/status")
    assert response.status_code == 200
    assert len(lock_queries) == 0, f"FOR UPDATE queries executed: {lock_queries}"


def test_scheduler_status_get_uses_no_write_locks(lock_monitoring_client):
    client, _, lock_queries, _ = lock_monitoring_client
    lock_queries.clear()

    response = client.get("/scheduler/status")
    assert response.status_code == 200
    assert len(lock_queries) == 0, f"FOR UPDATE queries executed: {lock_queries}"


def test_providers_health_get_uses_no_write_locks(lock_monitoring_client):
    client, _, lock_queries, _ = lock_monitoring_client
    lock_queries.clear()

    response = client.get("/providers/health")
    assert response.status_code == 200
    assert len(lock_queries) == 0, f"FOR UPDATE queries executed: {lock_queries}"


def test_dashboard_queries_get_uses_no_write_locks(lock_monitoring_client):
    client, _, lock_queries, _ = lock_monitoring_client
    lock_queries.clear()

    r1 = client.get("/dashboard")
    assert r1.status_code == 200
    assert len(lock_queries) == 0, f"FOR UPDATE queries executed: {lock_queries}"

    r2 = client.get("/api/v1/dashboard/overview")
    assert r2.status_code == 200
    assert len(lock_queries) == 0, f"FOR UPDATE queries executed: {lock_queries}"


def test_readiness_get_uses_no_write_locks(lock_monitoring_client):
    client, _, lock_queries, tmp_root = lock_monitoring_client
    lock_queries.clear()

    response = client.get(
        f"/projects/p-lock-test/changes/sample-change/readiness?project_root={tmp_root}"
    )
    assert response.status_code == 200
    assert len(lock_queries) == 0, f"FOR UPDATE queries executed: {lock_queries}"


def test_write_lock_instrumentation_spy_detects_command_locking(lock_monitoring_client):
    client, uow, lock_queries, _ = lock_monitoring_client
    lock_queries.clear()

    # Direct invocation of for_update repository method (used by command sagas/probes)
    uow.provider_health.get_by_provider_for_update("codex")
    assert len(lock_queries) == 1
    assert "provider_health.get_by_provider_for_update(codex)" in lock_queries[0]
