from fastapi.testclient import TestClient

from minime.api.app import app, get_current_operator, get_uow
from minime.domain.enums import HumanGate, OrchestrationStage, OrchestrationStopOutcome
from minime.domain.models import AuthorizedOperator, OrchestrationRun


def _add_run(uow, *, active_job_id=None):
    run = OrchestrationRun(
        run_id="cancel-api-run",
        project_id="cancel-api-project",
        change_name="issue-298-cancel-run",
        base_sha="base-sha",
        current_stage=OrchestrationStage.IMPLEMENTING,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_details={"issue_number": 298, "evidence": "keep"},
        active_job_id=active_job_id,
        is_active=True,
    )
    uow.orchestration_runs.save(run)
    return run


def test_cancel_run_api_returns_durable_terminal_result(in_memory_uow, monkeypatch):
    _add_run(in_memory_uow)
    monkeypatch.setitem(app.dependency_overrides, get_uow, lambda: in_memory_uow)
    monkeypatch.setitem(
        app.dependency_overrides,
        get_current_operator,
        lambda: AuthorizedOperator(email="operator@example.test"),
    )

    response = TestClient(app).post(
        "/api/v1/projects/cancel-api-project/runs/cancel-api-run/cancel",
        json={"reason": "Close the stuck Run", "idempotency_key": "cancel-api-1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    stored = in_memory_uow.orchestration_runs.get_by_id("cancel-api-run")
    assert not stored.is_active
    assert stored.stop_details["issue_number"] == 298
    assert stored.stop_details["cancellation"]["actor"] == "operator@example.test"


def test_cancel_run_api_rejects_active_job_without_mutation(in_memory_uow, monkeypatch):
    _add_run(in_memory_uow, active_job_id="job-active")
    monkeypatch.setitem(app.dependency_overrides, get_uow, lambda: in_memory_uow)
    monkeypatch.setitem(
        app.dependency_overrides,
        get_current_operator,
        lambda: AuthorizedOperator(email="operator@example.test"),
    )

    response = TestClient(app).post(
        "/api/v1/projects/cancel-api-project/runs/cancel-api-run/cancel",
        json={"reason": "Close the stuck Run", "idempotency_key": "cancel-api-2"},
    )

    assert response.status_code == 409
    stored = in_memory_uow.orchestration_runs.get_by_id("cancel-api-run")
    assert stored.is_active
    assert stored.active_job_id == "job-active"
