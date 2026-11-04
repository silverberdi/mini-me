from __future__ import annotations

import asyncio
import importlib
import json

import pytest
from fastapi import BackgroundTasks, HTTPException
from httpx import ASGITransport, AsyncClient
from tests.conftest import setup_managed_repository_fixture

from minime.domain.enums import HumanGate, OrchestrationStage, OrchestrationStopOutcome
from minime.domain.models import AuthorizedOperator, OrchestrationRun, Project
from minime.services.event_broker import EventBroker

api_module = importlib.import_module("minime.api.app")


async def _next_sse_event(iterator):
    pending = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)
    return pending


@pytest.mark.asyncio
async def test_successful_project_and_request_mutations_reach_sse(in_memory_uow, monkeypatch):
    broker = EventBroker()
    monkeypatch.setattr(api_module, "event_broker", broker)
    in_memory_uow.projects.save(
        Project(project_id="project-a", display_name="SSE", repository="org/sse")
    )
    monkeypatch.setattr(api_module.ProjectService, "pause_project", lambda *args, **kwargs: {"paused": True})
    monkeypatch.setattr(api_module.ProjectService, "resume_project", lambda *args, **kwargs: {"paused": False})
    monkeypatch.setattr(api_module.ProjectService, "pause_global", lambda *args, **kwargs: {"paused": True})
    monkeypatch.setattr(api_module.ProjectService, "resume_global", lambda *args, **kwargs: {"paused": False})
    monkeypatch.setattr(api_module.ProjectService, "set_lifecycle", lambda self, project_id, *, active: in_memory_uow.projects.get_by_id(project_id))
    monkeypatch.setattr(api_module.ProjectService, "public_project_payload", lambda self, project: {"project_id": project.project_id})

    from minime.services.request_lifecycle_service import RequestLifecycleService

    monkeypatch.setattr(RequestLifecycleService, "create_request", lambda *args, **kwargs: {"number": 41})
    monkeypatch.setattr(RequestLifecycleService, "deactivate_request", lambda *args, **kwargs: {"disabled": True})
    monkeypatch.setattr(RequestLifecycleService, "reactivate_request", lambda *args, **kwargs: {"disabled": False})

    response = await api_module.stream_events(_operator=None)
    stream = response.body_iterator
    assert await anext(stream) == ": connected\n\n"

    events = [
        ("project.pause_changed", {"scope": "project", "project_id": "project-a"}, api_module.pause_project, ("project-a", None, in_memory_uow)),
        ("project.pause_changed", {"scope": "project", "project_id": "project-a"}, api_module.resume_project, ("project-a", None, in_memory_uow)),
        ("project.pause_changed", {"scope": "global"}, api_module.pause_system, (None, in_memory_uow)),
        ("project.pause_changed", {"scope": "global"}, api_module.resume_system, (None, in_memory_uow)),
        (
            "request.created",
            {"project_id": "project-a", "request_id": 41},
            api_module.create_project_request,
            (
                "project-a",
                api_module.CreateProjectRequestPayload(
                    title="Request", description="Description", acceptance_criteria="Criteria"
                ),
                None,
                in_memory_uow,
            ),
        ),
        ("request.deactivated", {"project_id": "project-a", "issue_number": 41}, api_module.deactivate_project_request, ("project-a", 41, None, in_memory_uow)),
        ("request.reactivated", {"project_id": "project-a", "issue_number": 41}, api_module.reactivate_project_request, ("project-a", 41, None, in_memory_uow)),
    ]

    for expected_type, expected_data, endpoint, args in events:
        pending_event = await _next_sse_event(stream)
        background_tasks = BackgroundTasks()
        if endpoint is api_module.pause_project:
            endpoint(*args, background_tasks=background_tasks)
        elif endpoint in (api_module.resume_project, api_module.pause_system, api_module.resume_system):
            endpoint(*args, background_tasks=background_tasks)
        elif endpoint is api_module.create_project_request:
            endpoint(*args, background_tasks=background_tasks)
        else:
            endpoint(*args, background_tasks=background_tasks)
        await background_tasks()
        event = await pending_event
        assert event.startswith(f"event: {expected_type}\n")
        assert "secret" not in event.lower()
        assert json.loads(event.split("data: ", 1)[1]) == expected_data

    await stream.aclose()


@pytest.mark.asyncio
async def test_failed_project_mutation_does_not_publish_sse_event(in_memory_uow, monkeypatch):
    broker = EventBroker()
    published = []
    original_publish = broker.publish

    async def record_publish(event_type, payload):
        published.append((event_type, payload))
        await original_publish(event_type, payload)

    monkeypatch.setattr(broker, "publish", record_publish)
    monkeypatch.setattr(api_module, "event_broker", broker)

    def fail_pause(*args, **kwargs):
        raise ValueError("project missing")

    monkeypatch.setattr(api_module.ProjectService, "pause_project", fail_pause)
    with pytest.raises(HTTPException):
        api_module.pause_project(
            "missing-project", None, in_memory_uow, BackgroundTasks(), defer_if_active=True
        )

    assert published == []


@pytest.mark.asyncio
async def test_gate_acknowledgement_reaches_sse_before_coordinator_finishes(
    in_memory_uow, monkeypatch, tmp_path
):
    broker = EventBroker()
    published = []
    original_publish = broker.publish

    async def record_publish(event_type, payload):
        published.append((event_type, payload))
        await original_publish(event_type, payload)

    monkeypatch.setattr(broker, "publish", record_publish)
    monkeypatch.setattr(api_module, "event_broker", broker)
    project_id = "gate-project"
    run_id = "run-gate-287"
    in_memory_uow.projects.save(
        Project(project_id=project_id, display_name="Gate SSE", repository="org/gate-sse")
    )
    setup_managed_repository_fixture(
        in_memory_uow,
        project_id,
        tmp_path / "managed-repo",
        tmp_path / "worktrees",
    )
    run = OrchestrationRun(
        run_id=run_id,
        project_id=project_id,
        change_name="realtime-sse-state-and-human-gate-feedback",
        base_sha="base",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        resumable_stage=OrchestrationStage.PROPOSAL_REVIEW,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        is_active=True,
        stop_details={"human_payload": {"question": "Proceed?", "options": []}},
    )
    in_memory_uow.orchestration_runs.save(run)
    scheduled = []
    monkeypatch.setattr(
        api_module,
        "_schedule_request_worker",
        lambda project, body, intent: scheduled.append((project, body, intent)) or "operation-287",
    )
    api_module._accepted_operations.pop((project_id, f"{project_id}:active"), None)

    operator = AuthorizedOperator(email="operator@example.test")
    api_module.app.dependency_overrides[api_module.get_current_operator] = lambda: operator
    api_module.app.dependency_overrides[api_module.get_uow] = lambda: in_memory_uow
    api_module._accepted_operations.pop((project_id, f"{project_id}:active"), None)
    messages: asyncio.Queue[dict] = asyncio.Queue()
    disconnected = asyncio.Event()
    request_received = False

    async def receive():
        nonlocal request_received
        if not request_received:
            request_received = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        await messages.put(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/events",
        "raw_path": b"/api/v1/events",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
    }
    stream_task = asyncio.create_task(api_module.app(scope, receive, send))
    try:
        start = await asyncio.wait_for(messages.get(), timeout=2)
        initial = await asyncio.wait_for(messages.get(), timeout=2)
        assert start["type"] == "http.response.start" and start["status"] == 200
        assert initial["body"] == b": connected\n\n"
        await asyncio.sleep(0)

        async with AsyncClient(
            transport=ASGITransport(app=api_module.app), base_url="http://testserver"
        ) as client:
            accepted = await client.post(
                f"/api/v1/projects/{project_id}/requests/run",
                json={"operator_clarification": "Proceed with proposal"},
            )
            assert accepted.status_code == 202
            assert scheduled
            event_message = await asyncio.wait_for(messages.get(), timeout=2)
            event = event_message["body"].decode()
            assert event_message["type"] == "http.response.body"
            assert event == 'event: run.gate_acknowledged\ndata: {"project_id":"gate-project","run_id":"run-gate-287"}\n\n'
            assert published == [("run.gate_acknowledged", {"project_id": project_id, "run_id": run_id})]

            # Re-entry is accepted from the operation map but does not publish a duplicate acknowledgement.
            duplicate = await client.post(
                f"/api/v1/projects/{project_id}/requests/run",
                json={"operator_clarification": "Proceed with proposal"},
            )
            assert duplicate.status_code == 202
            assert len(published) == 1
    finally:
        disconnected.set()
        await asyncio.wait_for(stream_task, timeout=2)
        api_module.app.dependency_overrides.pop(api_module.get_current_operator, None)
        api_module.app.dependency_overrides.pop(api_module.get_uow, None)
        api_module._accepted_operations.pop((project_id, f"{project_id}:active"), None)
