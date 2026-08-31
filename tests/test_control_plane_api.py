"""API tests for Operator Control Plane endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from minime.api.app import app, get_uow
from minime.domain.enums import (
    ChangeStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
)
from minime.domain.models import Change, OrchestrationRun, Project


@pytest.fixture
def setup_data(in_memory_uow):
    project = Project(
        project_id="p-1",
        display_name="P1",
        repository="test/p1",
        external_providers_allowed=["codex", "antigravity"],
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="p-1",
        name="015-api-test",
        status=ChangeStatus.READY,
    )
    in_memory_uow.changes.save(change)

    run = OrchestrationRun(
        run_id="run-api-1",
        project_id="p-1",
        change_name="015-api-test",
        base_sha="base12345678",
        current_stage=OrchestrationStage.IMPLEMENTING,
        resumable_stage=OrchestrationStage.IMPLEMENTING,
        is_active=False,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
    )
    in_memory_uow.orchestration_runs.save(run)
    in_memory_uow.commit()

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)
    yield client, project, change, run
    app.dependency_overrides.clear()


def test_discover_actions_api(setup_data):
    client, project, change, run = setup_data
    response = client.get(f"/api/v1/runs/{run.run_id}/actions")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 7

    actions = {item["action"]: item for item in data}
    assert "CONTINUE" in actions
    assert "CANCEL" in actions
    assert actions["CONTINUE"]["enabled"] is True


def test_execute_action_api(setup_data):
    client, project, change, run = setup_data
    payload = {
        "project_id": "p-1",
        "change_name": "015-api-test",
        "run_id": "run-api-1",
        "action_type": "CONTINUE",
        "actor_identity": "api_user",
        "source_interface": "rest_api",
        "parameters": {},
    }
    response = client.post(f"/api/v1/runs/{run.run_id}/actions/CONTINUE", json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "COMPLETED"
    assert result["action_type"] == "CONTINUE"


def test_action_history_api(setup_data):
    client, project, change, run = setup_data
    # Execute an action first
    payload = {
        "project_id": "p-1",
        "change_name": "015-api-test",
        "run_id": "run-api-1",
        "action_type": "CONTINUE",
        "actor_identity": "api_user",
        "source_interface": "rest_api",
        "parameters": {},
    }
    client.post(f"/api/v1/runs/{run.run_id}/actions/CONTINUE", json=payload)

    # Fetch history
    history_res = client.get(f"/api/v1/runs/{run.run_id}/actions/history")
    assert history_res.status_code == 200
    history = history_res.json()
    assert len(history) == 1
    assert history[0]["action_type"] == "CONTINUE"
    assert history[0]["actor_identity"] == "api_user"
