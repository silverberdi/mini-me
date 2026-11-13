"""Usage APIs expose observed provider facts without internal cap state."""
from decimal import Decimal

from fastapi.testclient import TestClient

from minime.api.app import app, get_uow
from minime.domain.models import BudgetLedgerEntry, Project


def _project(uow, project_id: str = "mini-me") -> None:
    uow.projects.save(
        Project(project_id=project_id, display_name=project_id, repository="owner/repo")
    )


def test_usage_api_returns_observed_spend_without_policy_or_headroom(in_memory_uow):
    _project(in_memory_uow)
    in_memory_uow.budget_ledger.save(
        BudgetLedgerEntry(
            project_id="mini-me",
            job_id="job-1",
            change_id="change-1",
            provider="openrouter",
            billing_origin="openrouter",
            role="implementer",
            canonical_model_identity="deepseek/deepseek-chat",
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
            amount_usd=Decimal("0.05"),
            entry_type="USAGE",
        )
    )
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    try:
        response = TestClient(app).get("/budget/usage?project_id=mini-me")
    finally:
        app.dependency_overrides.pop(get_uow, None)
    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == "mini-me"
    assert data["ledger"][0]["amount_usd"] == "0.05"
    assert data["token_usage_by_model"]["deepseek/deepseek-chat"]["total_tokens"] == 30
    assert "policy" not in data
    assert "headroom" not in data


def test_project_usage_alias_returns_empty_observed_data_without_policy(in_memory_uow):
    _project(in_memory_uow, "custom-proj")
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    try:
        response = TestClient(app).get("/projects/custom-proj/budget")
    finally:
        app.dependency_overrides.pop(get_uow, None)
    assert response.status_code == 200
    assert response.json()["ledger"] == []
    assert "headroom" not in response.json()


def test_openrouter_status_has_no_artificial_caps(in_memory_uow):
    _project(in_memory_uow)
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    try:
        response = TestClient(app).get("/providers/openrouter/status?project_id=mini-me")
    finally:
        app.dependency_overrides.pop(get_uow, None)
    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == "mini-me"
    assert data["provider"] == "openrouter"
    assert "daily_cap_usd" not in data
    assert "monthly_cap_usd" not in data
    assert "headroom" not in data
