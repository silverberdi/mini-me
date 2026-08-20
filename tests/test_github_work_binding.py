"""Tests for GitHub work binding, durable identifiers, uniqueness, and sync failure reconciliation."""

import pytest

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import EventType, ReadinessState
from minime.domain.models import ProjectBinding
from minime.services.project_service import ProjectService
from minime.services.readiness_service import ReadinessService


def test_github_work_binding_repository_mismatch(in_memory_uow):
    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="proj-a",
        display_name="Project A",
        repository="org/repo-a",
        base_branch="main",
        openspec_path="openspec",
    )

    # Durable binding to repo-a
    binding = ProjectBinding(
        project_id="proj-a",
        repository="org/repo-a",
        github_issue_number=42,
        openspec_change_name="001-foundation",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)

    # When an external presentation/issue claims repository B, readiness fails
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="proj-a",
        change_name="001-foundation",
        project_root=".",
        github_repo="org/repo-b",
    )

    assert eval_result.is_ready is False
    assert any("Repository mismatch" in r for r in eval_result.unmet_reasons)


def test_github_issue_number_mandatory_for_ready(in_memory_uow):
    """Proves: Durable ProjectBinding with github_issue_number=None blocks READY with structured reason."""
    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="proj-a",
        display_name="Project A",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )

    # Binding without an issue number
    binding = ProjectBinding(
        project_id="proj-a",
        repository="silverberdi/mini-me",
        github_issue_number=None,
        openspec_change_name="001-foundation",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="proj-a",
        change_name="001-foundation",
        project_root=".",
    )

    assert eval_result.is_ready is False
    assert eval_result.status == ReadinessState.NOT_READY
    assert any("Missing GitHub Issue binding" in r for r in eval_result.unmet_reasons)

    # When issue number is provided on binding, evaluation passes to READY
    binding.github_issue_number = 101
    in_memory_uow.bindings.save(binding)

    eval_result2 = readiness_service.evaluate_change_readiness(
        project_id="proj-a",
        change_name="001-foundation",
        project_root=".",
    )
    assert eval_result2.is_ready is True
    assert eval_result2.status == ReadinessState.READY


def test_duplicate_binding_rejected(in_memory_uow):
    """Proves: Duplicate binding creation for (project_id, openspec_change_name) is rejected."""
    binding1 = ProjectBinding(
        binding_id="bind-1",
        project_id="proj-dup",
        repository="org/repo",
        github_issue_number=1,
        openspec_change_name="001-foundation",
    )
    in_memory_uow.bindings.save(binding1)

    binding2 = ProjectBinding(
        binding_id="bind-2",
        project_id="proj-dup",
        repository="org/repo",
        github_issue_number=2,
        openspec_change_name="001-foundation",
    )
    with pytest.raises(ValueError, match="Unique constraint violation"):
        in_memory_uow.bindings.save(binding2)


def test_github_sync_failure_and_reconciliation(in_memory_uow):
    adapter = GitHubAdapter()

    # Transient sync failure
    failure_event = adapter.record_sync_failure(
        project_id="proj-a",
        change_id="001-foundation",
        operation="sync_issues",
        error_message="GitHub API rate limit exceeded (503)",
    )
    in_memory_uow.events.save(failure_event)

    events = in_memory_uow.events.list_events(project_id="proj-a")
    assert len(events) == 1
    assert events[0].event_type == EventType.SYNC_FAILED
    assert events[0].payload["reconcilable"] is True

    # Reconciled event
    reconciled_event = adapter.record_sync_reconciled(
        project_id="proj-a",
        change_id="001-foundation",
        operation="sync_issues",
        details={"status": "all_issues_synced"},
    )
    in_memory_uow.events.save(reconciled_event)

    all_events = in_memory_uow.events.list_events(project_id="proj-a")
    assert len(all_events) == 2
    types = [e.event_type for e in all_events]
    assert EventType.SYNC_RECONCILED in types
