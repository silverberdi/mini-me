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


def test_evaluate_change_readiness_pure_executes_zero_db_commits_or_saves(mock_readiness_uow, tmp_path):
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


def test_evaluate_and_persist_change_readiness_persists_records_and_commits(mock_readiness_uow, tmp_path):
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
