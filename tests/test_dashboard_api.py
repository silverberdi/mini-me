"""API endpoint integration tests for Operations Dashboard."""

from __future__ import annotations

from fastapi.testclient import TestClient

from minime.api.app import app, get_uow
from minime.domain.enums import (
    ChangeStatus,
    OrchestrationStage,
    ReadinessState,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    Change,
    OrchestrationRun,
    OrchestrationStageEvent,
    Project,
)


def test_api_dashboard_overview_empty(in_memory_uow: PersistenceUnitOfWork) -> None:
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    resp = client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["system_status"]["healthy"] is True
    assert data["system_status"]["active_runs_count"] == 0
    assert data["attention_items"] == []
    assert data["changes"] == []


def test_api_dashboard_overview_with_data(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="mini-me",
        name="012-execution-operations-dashboard",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    run = OrchestrationRun(
        run_id="run-012",
        project_id="mini-me",
        change_name="012-execution-operations-dashboard",
        current_stage=OrchestrationStage.IMPLEMENTING,
        is_active=True,
        current_generation=1,
        current_candidate_sha="abc1234567890",
        base_sha="base1234567890",
    )
    in_memory_uow.orchestration_runs.save(run)

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    resp = client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["system_status"]["active_runs_count"] == 1
    assert len(data["active_executions"]) == 1
    assert data["active_executions"][0]["change_name"] == "012-execution-operations-dashboard"
    assert len(data["changes"]) == 1
    assert data["changes"][0]["status"] == "RUNNING"


def test_api_dashboard_change_detail(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="mini-me",
        name="012-execution-operations-dashboard",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    run = OrchestrationRun(
        run_id="run-012",
        project_id="mini-me",
        change_name="012-execution-operations-dashboard",
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        is_active=True,
        current_generation=1,
        current_candidate_sha="abc1234567890",
        base_sha="base1234567890",
    )
    in_memory_uow.orchestration_runs.save(run)

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    resp = client.get("/api/v1/dashboard/changes/mini-me/012-execution-operations-dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == "mini-me"
    assert data["change_name"] == "012-execution-operations-dashboard"
    assert data["status"] == "RUNNING"
    assert len(data["pipeline"]) == 6
    assert data["candidate_authority"]["candidate_sha"] == "abc1234567890"


def test_api_dashboard_run_detail(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="mini-me",
        name="012-execution-operations-dashboard",
    )
    in_memory_uow.changes.save(change)

    run = OrchestrationRun(
        run_id="run-exact-99",
        project_id="mini-me",
        change_name="012-execution-operations-dashboard",
        current_stage=OrchestrationStage.INDEPENDENT_AUDIT,
        is_active=True,
        current_generation=1,
        base_sha="base9999",
    )
    in_memory_uow.orchestration_runs.save(run)

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    resp = client.get("/api/v1/dashboard/runs/run-exact-99")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run-exact-99"
    assert data["current_stage"] == "INDEPENDENT_AUDIT"

    # Non-existent run
    resp_404 = client.get("/api/v1/dashboard/runs/non-existent-run")
    assert resp_404.status_code == 404


def test_api_dashboard_events(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    se = OrchestrationStageEvent(
        run_id="run-ev-1",
        from_stage=OrchestrationStage.ADMITTED,
        to_stage=OrchestrationStage.PREPARING_EXECUTION,
        evidence_references={"reason": "Admitted change into execution"},
    )
    in_memory_uow.orchestration_stage_events.save(se)

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    resp = client.get("/api/v1/dashboard/events?run_id=run-ev-1")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["from_stage"] == "ADMITTED"
    assert events[0]["to_stage"] == "PREPARING_EXECUTION"


def test_api_dashboard_static_and_html(in_memory_uow: PersistenceUnitOfWork) -> None:
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)

    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert "mini me" in resp_root.text

    resp_dashboard = client.get("/dashboard")
    assert resp_dashboard.status_code == 200
    assert "Operations Dashboard" in resp_dashboard.text

    resp_css = client.get("/static/css/dashboard.css")
    assert resp_css.status_code == 200
    assert "--bg-app" in resp_css.text

    resp_js = client.get("/static/js/dashboard.js")
    assert resp_js.status_code == 200
    assert "fetchOverview" in resp_js.text
