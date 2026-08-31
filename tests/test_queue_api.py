"""API tests for Queue and Scheduler endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.api.app import app, get_uow
from minime.domain.enums import (
    AdmissionDecision,
    QueuePriority,
    ReadinessState,
)
from minime.domain.models import (
    Project,
    SchedulerDecisionRecord,
    WorkQueueItem,
)


@pytest.fixture
def queue_api_client(in_memory_uow: InMemoryPersistenceUnitOfWork):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    item1 = WorkQueueItem(
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        github_issue_number=45,
        priority=QueuePriority.HIGH,
        roadmap_stage=16,
        readiness_state=ReadinessState.READY,
        admission_eligible=True,
        priority_score=5000.0,
    )
    item2 = WorkQueueItem(
        project_id="mini-me",
        change_name="017-pwa-control-center",
        github_issue_number=46,
        priority=QueuePriority.NORMAL,
        roadmap_stage=17,
        readiness_state=ReadinessState.NOT_READY,
        admission_eligible=False,
        blocked_reason="Stage 16 not complete",
        priority_score=1000.0,
    )
    in_memory_uow.work_queue.save(item1)
    in_memory_uow.work_queue.save(item2)

    decision = SchedulerDecisionRecord(
        project_id="mini-me",
        change_name="016-autonomous-queue-work-selection",
        github_issue_number=45,
        decision=AdmissionDecision.ADMITTED,
        reason_summary="READY and eligible",
        priority_score=5000.0,
        selected_implementer="codex",
    )
    in_memory_uow.scheduler_decisions.save(decision)
    in_memory_uow.commit()

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    client = TestClient(app)
    yield client, in_memory_uow
    app.dependency_overrides.clear()


def test_list_queue_api(queue_api_client):
    client, _ = queue_api_client
    response = client.get("/api/v1/queue")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["change_name"] == "016-autonomous-queue-work-selection"

    # Test ready_only filter
    response_ready = client.get("/api/v1/queue?ready_only=true")
    assert response_ready.status_code == 200
    data_ready = response_ready.json()
    assert len(data_ready) == 1
    assert data_ready[0]["change_name"] == "016-autonomous-queue-work-selection"


def test_explain_queue_api(queue_api_client):
    client, _ = queue_api_client
    response = client.get("/api/v1/queue/016-autonomous-queue-work-selection/explain")
    assert response.status_code == 200
    data = response.json()
    assert data["change_name"] == "016-autonomous-queue-work-selection"
    assert data["priority"] == "HIGH"
    assert data["queue_position"] == 1
    assert data["base_score"] == 5000.0


def test_scheduler_status_api(queue_api_client):
    client, _ = queue_api_client
    response = client.get("/api/v1/scheduler/status")
    assert response.status_code == 200
    data = response.json()
    assert data["queue_depth"] == 2
    assert data["ready_count"] == 1
    assert data["blocked_count"] == 1
    assert len(data["recent_decisions"]) == 1
