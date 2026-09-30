"""Test suite verifying ReadinessService CQS split into pure query and persist command."""

from __future__ import annotations

import pytest

from minime.domain.enums import ProjectStatus, ReadinessState
from minime.domain.models import Project
from minime.services.readiness_service import ReadinessService


@pytest.fixture
def mock_readiness_uow(in_memory_uow):
    uow = in_memory_uow
    proj = Project(
        project_id="p-readiness-test",
        display_name="Readiness Test Project",
        repository="owner/repo",
        base_branch="main",
        status=ProjectStatus.ACTIVE,
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(proj)
    uow.commit()
    uow.committed = False
    yield uow


def test_evaluate_change_readiness_pure_executes_zero_db_commits_or_saves(
    mock_readiness_uow, tmp_path
):
    uow = mock_readiness_uow
    service = ReadinessService(uow)

    # Pure evaluation
    result = service.evaluate_change_readiness_pure(
        project_id="p-readiness-test",
        change_name="test-pure-change",
        project_root=str(tmp_path),
    )

    assert result.change_id == "test-pure-change"
    assert result.status == ReadinessState.NOT_READY

    # Assert 0 DB commits and 0 new Change records in DB
    assert uow.committed is False
    assert uow.changes.get_by_name("p-readiness-test", "test-pure-change") is None


def test_evaluate_and_persist_change_readiness_persists_records_and_commits(
    mock_readiness_uow, tmp_path
):
    uow = mock_readiness_uow
    service = ReadinessService(uow)

    # Persisting command
    result = service.evaluate_and_persist_change_readiness(
        project_id="p-readiness-test",
        change_name="test-persist-change",
        project_root=str(tmp_path),
    )

    assert result.change_id == "test-persist-change"

    # Assert Change record created and commit called
    assert uow.changes.get_by_name("p-readiness-test", "test-persist-change") is not None
    assert uow.committed is True


def test_http_get_readiness_route_purity(mock_readiness_uow, tmp_path):
    from fastapi.testclient import TestClient

    from minime.api.app import app, get_uow

    uow = mock_readiness_uow
    uow.committed = False

    def _get_uow_override():
        return uow

    app.dependency_overrides[get_uow] = _get_uow_override
    client = TestClient(app)

    events_before = len(uow.events.list_events(limit=100))
    metrics_before = len(getattr(uow.metrics, "_facts", []))

    response = client.get(
        f"/projects/p-readiness-test/changes/test-http-readiness/readiness?project_root={tmp_path}"
    )

    app.dependency_overrides.clear()

    # Reaches readiness evaluation, status code is 200 (NOT 422)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    body = response.json()
    assert body["change_id"] == "test-http-readiness"
    assert "status" in body
    assert "checks" in body

    # Zero DB mutations or commits
    assert uow.changes.get_by_name("p-readiness-test", "test-http-readiness") is None
    assert len(uow.events.list_events(limit=100)) == events_before
    assert len(getattr(uow.metrics, "_facts", [])) == metrics_before
    assert uow.committed is False


def test_readiness_caller_classification_audit():
    import inspect

    from minime.api import app as api_app
    from minime.services import scheduler_service

    # Query route in app.py uses evaluate_change_readiness_pure
    app_src = inspect.getsource(api_app)
    assert "service.evaluate_change_readiness_pure(" in app_src
    assert "service.evaluate_change_readiness(" not in app_src

    # Command scheduler service uses evaluate_change_readiness_pure (zero-commit Phase A)
    sched_src = inspect.getsource(scheduler_service)
    assert "evaluate_change_readiness_pure" in sched_src

