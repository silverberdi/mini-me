"""Unit tests for Budget and OpenRouter observability API endpoints."""

from decimal import Decimal

from fastapi.testclient import TestClient

from minime.api.app import app, get_uow
from minime.domain.models import OpenRouterBudgetPolicy, Project
from minime.services.budget_service import BudgetService


def test_budget_usage_api_endpoint(in_memory_uow):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
    )
    in_memory_uow.projects.save(project)
    service = BudgetService(in_memory_uow)
    service.sync_policy_from_config(
        project_id="mini-me",
        enabled=True,
        daily_cap_usd=Decimal("15.00"),
        monthly_cap_usd=Decimal("40.00"),
    )

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    res = client.get("/budget/usage?project_id=mini-me")
    assert res.status_code == 200
    data = res.json()
    assert data["project_id"] == "mini-me"
    assert data["policy"]["enabled"] is True
    assert float(data["policy"]["daily_cap_usd"]) == 15.0
    assert float(data["policy"]["monthly_cap_usd"]) == 40.0
    assert float(data["headroom"]["daily_headroom_usd"]) == 15.0
    assert float(data["headroom"]["monthly_headroom_usd"]) == 40.0


def test_project_budget_path_endpoint(in_memory_uow):
    project = Project(
        project_id="custom-proj",
        display_name="Custom Project",
        repository="owner/custom-proj",
    )
    in_memory_uow.projects.save(project)
    service = BudgetService(in_memory_uow)
    service.sync_policy_from_config(
        project_id="custom-proj",
        enabled=True,
        daily_cap_usd=Decimal("25.00"),
        monthly_cap_usd=Decimal("100.00"),
    )

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    res = client.get("/projects/custom-proj/budget")
    assert res.status_code == 200
    data = res.json()
    assert data["project_id"] == "custom-proj"
    assert float(data["policy"]["daily_cap_usd"]) == 25.0


def test_openrouter_status_api_endpoint(in_memory_uow):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="owner/mini-me",
    )
    in_memory_uow.projects.save(project)
    service = BudgetService(in_memory_uow)
    service.sync_policy_from_config(
        project_id="mini-me",
        enabled=True,
        daily_cap_usd=Decimal("10.00"),
        monthly_cap_usd=Decimal("30.00"),
    )

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    res = client.get("/providers/openrouter/status?project_id=mini-me")
    assert res.status_code == 200
    data = res.json()
    assert data["project_id"] == "mini-me"
    assert data["enabled"] is True
    assert data["is_breached"] is False
    assert "allowed_models" in data
    assert "implementer" in data["allowed_models"]
    assert "reviewer" in data["allowed_models"]


def test_budget_api_breach_indicator(in_memory_uow):
    project = Project(
        project_id="breached-proj",
        display_name="Breached",
        repository="owner/breached",
    )
    in_memory_uow.projects.save(project)
    policy = OpenRouterBudgetPolicy(
        project_id="breached-proj",
        enabled=True,
        daily_cap_usd=Decimal("10.00"),
        monthly_cap_usd=Decimal("30.00"),
        is_breached=True,
    )
    in_memory_uow.budget_policies.save(policy)

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    res = client.get("/providers/openrouter/status?project_id=breached-proj")
    assert res.status_code == 200
    data = res.json()
    assert data["is_breached"] is True

