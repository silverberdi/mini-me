"""Ledger-backed Dashboard cost projection contract tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from minime.api.app import app, get_current_operator, get_uow
from minime.domain.enums import WorktreeCreationState
from minime.domain.models import (
    AuthorizedOperator,
    BudgetLedgerEntry,
    OrchestrationWorktreeOwnership,
    Project,
)
from minime.services.dashboard_service import OperationsDashboardService
from tests.conftest import InMemoryPersistenceUnitOfWork


def _entry(
    *,
    provider: str,
    model: str,
    amount: str,
    entry_type: str = "SETTLEMENT",
    reservation_id: str | None = "reservation-1",
    origin: str | None = None,
    created_at: datetime = datetime(2026, 11, 5, 14, 30, tzinfo=UTC),
) -> BudgetLedgerEntry:
    return BudgetLedgerEntry(
        entry_id=f"entry-{provider}-{model}-{amount}-{entry_type}",
        reservation_id=reservation_id,
        project_id="project-1",
        job_id="job-1",
        change_id="change-1",
        provider=provider,
        billing_origin=origin or provider,
        role="execution",
        canonical_model_identity=model,
        amount_usd=Decimal(amount),
        entry_type=entry_type,
        created_at=created_at,
        total_tokens=999999,
    )


@pytest.fixture
def cost_uow() -> InMemoryPersistenceUnitOfWork:
    uow = InMemoryPersistenceUnitOfWork()
    uow.projects.save(
        Project(
            project_id="project-1",
            display_name="Cost project",
            repository="owner/cost-project",
        )
    )
    return uow


def test_cost_projection_uses_only_liquidated_verified_ledger_rows(cost_uow) -> None:
    cost_uow.budget_ledger.save(
        _entry(provider="deepseek", model="deepseek/deepseek-flash", amount="0.123456", origin="deepseek_direct")
    )
    cost_uow.budget_ledger.save(
        _entry(provider="openrouter", model="openrouter/deepseek/deepseek-r1-0528", amount="1.20")
    )
    cost_uow.budget_ledger.save(
        _entry(provider="openrouter", model="openrouter/unknown", amount="9.99", entry_type="RESERVATION")
    )
    cost_uow.budget_ledger.save(
        _entry(provider="deepseek", model="deepseek/deepseek-flash", amount="8.88", entry_type="USAGE", reservation_id=None, origin="deepseek_direct")
    )
    cost_uow.budget_ledger.save(
        _entry(provider="mystery", model="deepseek/deepseek-flash", amount="7.77")
    )

    payload = OperationsDashboardService(cost_uow).get_cost_projection("project-1").model_dump()

    assert payload["status"] == "available"
    assert {provider["provider"] for provider in payload["providers"]} == {"deepseek_direct", "openrouter"}
    assert payload["providers"][0]["amount_usd"] == "0.123456"
    assert payload["series"][0]["source_timestamps"] == ["2026-11-05T14:30:00+00:00"]
    assert all(point["amount_usd"] != "8.88" for point in payload["series"])


def test_verified_provider_with_unknown_model_stays_in_provider_total(cost_uow) -> None:
    cost_uow.budget_ledger.save(
        _entry(provider="openrouter", model="", amount="0.000001")
    )
    payload = OperationsDashboardService(cost_uow).get_cost_projection("project-1").model_dump()
    provider = payload["providers"][0]

    assert provider["amount_usd"] == "0.000001"
    assert provider["models"] == [{"model": "Modelo no identificado", "amount_usd": "0.000001"}]


def test_no_data_is_explicit_and_run_tokens_are_ignored(cost_uow) -> None:
    payload = OperationsDashboardService(cost_uow).get_cost_projection("project-1").model_dump()
    assert payload == {"status": "no_data", "providers": [], "series": []}


def test_dashboard_cost_api_preserves_auth_boundary_and_existing_shape(cost_uow) -> None:
    ownership = OrchestrationWorktreeOwnership(
        worktree_id="worktree-1",
        project_id="project-1",
        job_id="job-1",
        run_id="run-1",
        change_name="cost-change",
        canonical_worktree_path="/tmp/cost-worktree",
        source_repository_identity="owner/cost-project",
        source_base_sha="a" * 40,
        branch="cost-test",
        creation_state=WorktreeCreationState.CREATED,
    )
    cost_uow.orchestration_worktree_ownerships = SimpleNamespace(
        list_active=lambda: [ownership]
    )
    app.dependency_overrides[get_uow] = lambda: cost_uow
    app.dependency_overrides[get_current_operator] = lambda: AuthorizedOperator(email="operator@example.com")
    cost_uow.budget_ledger.save(
        _entry(provider="deepseek", model="deepseek/deepseek-flash", amount="0.100000", origin="deepseek_direct")
    )
    try:
        response = TestClient(app).get("/api/v1/dashboard/overview?project_id=project-1")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["cost"]["providers"][0]["label"] == "DeepSeek Direct"
    assert body["cost"]["providers"][0]["amount_usd"] == "0.100000"
    assert "system_status" in body
    assert body["system_status"]["active_worktrees_list"][0]["state"] == "CREATED"
