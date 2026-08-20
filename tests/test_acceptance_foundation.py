"""Acceptance scenarios for 001-foundation OpenSpec capabilities."""

import pytest

from conftest import create_isolated_openspec_change
from minime.adapters.github import GitHubAdapter
from minime.adapters.openspec import OpenSpecAdapter
from minime.config import DatabaseConfig
from minime.domain.enums import ChangeStatus, EventType
from minime.domain.models import Change, Event, MetricFact, Project, ProjectBinding
from minime.logging import (
    clear_correlation_context,
    get_correlation_context,
    redact_secrets,
    set_correlation_context,
)
from minime.services.project_service import (
    ProjectService,
)
from minime.services.readiness_service import ReadinessService
from minime.services.status_service import StatusService

# --- Capability: postgres-durable-state ---


def test_acceptance_postgres_durable_state_configuration(monkeypatch):
    """Scenario: mini me starts with valid PostgreSQL configuration."""
    monkeypatch.setenv(
        "MINIME_DATABASE_URL", "postgresql+psycopg://minime:pass@localhost:5432/minime"
    )
    db_config = DatabaseConfig()
    url = db_config.resolve_url()
    assert url.startswith("postgresql")

    # Reject SQLite
    monkeypatch.setenv("MINIME_DATABASE_URL", "sqlite:///minime.db")
    with pytest.raises(ValueError, match="strictly requires PostgreSQL"):
        db_config.resolve_url()


def test_acceptance_postgres_daemon_restart(in_memory_uow):
    """Scenario: Daemon restarts without forgetting registered or discovered work."""
    # Commit project, change, and event
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        change_id="change-001",
        project_id="mini-me",
        name="synthetic-change",
        status=ChangeStatus.READY,
    )
    in_memory_uow.changes.save(change)

    event = Event(
        event_id="evt-001",
        event_type=EventType.CHANGE_DISCOVERED,
        project_id="mini-me",
        change_id="synthetic-change",
        payload={"schema": "spec-driven"},
    )
    in_memory_uow.events.save(event)
    in_memory_uow.commit()

    # Simulate restart by reading from persistence
    restored_proj = in_memory_uow.projects.get_by_id("mini-me")
    assert restored_proj is not None
    assert restored_proj.repository == "silverberdi/mini-me"

    restored_change = in_memory_uow.changes.get_by_name("mini-me", "synthetic-change")
    assert restored_change is not None
    assert restored_change.status == ChangeStatus.READY

    events = in_memory_uow.events.list_events(project_id="mini-me", change_id="synthetic-change")
    assert len(events) == 1
    assert events[0].event_type == EventType.CHANGE_DISCOVERED


# --- Capability: project-registry ---


def test_acceptance_project_display_name_change(in_memory_uow):
    """Scenario: Project display name changes while immutable project_id remains unchanged."""
    service = ProjectService(in_memory_uow)
    project = service.register_project(
        project_id="core-app",
        display_name="Core Application",
        repository="org/core-app",
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
    )
    assert project.project_id == "core-app"

    updated = service.update_project(
        project_id="core-app",
        display_name="Core Platform Service",
    )
    assert updated.project_id == "core-app"
    assert updated.display_name == "Core Platform Service"


def test_acceptance_project_policy_incomplete(in_memory_uow):
    """Scenario: Required project policy is incomplete."""
    service = ProjectService(in_memory_uow)
    with pytest.raises(ValueError) as excinfo:
        service.register_project(
            project_id="",
            display_name="",
            repository="",
        )
    err = str(excinfo.value)
    assert "project_id is required" in err
    assert "display_name is required" in err
    assert "repository is required" in err


def test_acceptance_complementary_roles_policy(in_memory_uow):
    """Scenario: Same primary agent is configured for both roles."""
    service = ProjectService(in_memory_uow)
    with pytest.raises(ValueError, match="cannot be both implementer and reviewer"):
        service.register_project(
            project_id="bad-roles",
            display_name="Bad Roles",
            repository="org/repo",
            implementer="codex",
            reviewer="codex",
        )


# --- Capability: repository-binding ---


def test_acceptance_presentation_metadata_never_authorizes_repo_change(in_memory_uow, tmp_path):
    """Scenario: Presentation metadata names another project."""
    create_isolated_openspec_change(tmp_path, "synthetic-change")

    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="proj-a",
        display_name="Project A",
        repository="org/repo-a",
        base_branch="main",
    )

    # Durable binding to Repo A
    binding = ProjectBinding(
        project_id="proj-a",
        repository="org/repo-a",
        github_issue_number=42,
        openspec_change_name="synthetic-change",
    )
    in_memory_uow.bindings.save(binding)

    # Issue presentation metadata claims Repo B
    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="proj-a",
        change_name="synthetic-change",
        project_root=str(tmp_path),
        github_repo="org/repo-b",
    )
    assert eval_result.is_ready is False
    assert any("Repository mismatch" in r for r in eval_result.unmet_reasons)


def test_acceptance_missing_binding_blocks_readiness(in_memory_uow, tmp_path):
    """Scenario: Registered project lacks a durable ProjectBinding."""
    create_isolated_openspec_change(tmp_path, "synthetic-change")

    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="proj-a",
        display_name="Project A",
        repository="org/repo-a",
        base_branch="main",
    )

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="proj-a",
        change_name="synthetic-change",
        project_root=str(tmp_path),
    )
    assert eval_result.is_ready is False
    assert any("Missing durable project binding" in r for r in eval_result.unmet_reasons)


def test_acceptance_binding_mismatch_blocks_readiness(in_memory_uow, tmp_path):
    """Scenario: Issue points at another repository."""
    create_isolated_openspec_change(tmp_path, "synthetic-change")

    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="proj-a",
        display_name="Project A",
        repository="org/repo-a",
        base_branch="main",
    )

    binding = ProjectBinding(
        project_id="proj-a",
        repository="org/repo-b",  # Mismatch with registered repo-a
        github_issue_number=42,
        openspec_change_name="synthetic-change",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="proj-a",
        change_name="synthetic-change",
        project_root=str(tmp_path),
    )
    assert eval_result.is_ready is False
    assert any("Repository mismatch" in r for r in eval_result.unmet_reasons)


# --- Capability: openspec-readiness ---


def test_acceptance_active_openspec_discovery(in_memory_uow, tmp_path):
    """Scenario: Registered project contains an active change."""
    create_isolated_openspec_change(tmp_path, "synthetic-change-one")
    create_isolated_openspec_change(tmp_path, "synthetic-change-two")

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    adapter = OpenSpecAdapter()
    changes = adapter.discover_changes(project, project_root=str(tmp_path))
    assert len(changes) == 2
    names = [c.name for c in changes]
    assert "synthetic-change-one" in names
    assert "synthetic-change-two" in names


def test_acceptance_runtime_state_outside_openspec(in_memory_uow, tmp_path):
    """Scenario: Runtime status changes without modifying OpenSpec."""
    change_dir = create_isolated_openspec_change(tmp_path, "synthetic-change")
    proposal_path = change_dir / "proposal.md"
    initial_content = proposal_path.read_text(encoding="utf-8")

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=1,
        openspec_change_name="synthetic-change",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="mini-me",
        change_name="synthetic-change",
        project_root=str(tmp_path),
    )
    assert eval_result.is_ready is True
    assert proposal_path.read_text(encoding="utf-8") == initial_content


def test_acceptance_roadmap_gating(in_memory_uow, tmp_path):
    """Scenario: Future roadmap change exists on disk while prior stage is active."""
    create_isolated_openspec_change(tmp_path, "future-stage-change")

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=1,
        openspec_change_name="future-stage-change",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="mini-me",
        change_name="future-stage-change",
        project_root=str(tmp_path),
        current_active_change="active-stage-change",
    )
    assert eval_result.is_ready is False
    assert any("Roadmap gating" in r for r in eval_result.unmet_reasons)


# --- Capability: github-work-binding ---


def test_acceptance_github_issue_mandatory_for_readiness(in_memory_uow, tmp_path):
    """Scenario: Persist GitHub work identifiers without display-name authority; issue number is mandatory."""
    create_isolated_openspec_change(tmp_path, "synthetic-change")

    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=None,
        openspec_change_name="synthetic-change",
    )
    in_memory_uow.bindings.save(binding)

    readiness_service = ReadinessService(in_memory_uow)
    eval_result = readiness_service.evaluate_change_readiness(
        project_id="mini-me",
        change_name="synthetic-change",
        project_root=str(tmp_path),
    )
    assert eval_result.is_ready is False
    assert any("Missing GitHub Issue binding" in r for r in eval_result.unmet_reasons)


def test_acceptance_github_outage_reconcilable(in_memory_uow):
    """Scenario: GitHub synchronization is temporarily unavailable."""
    adapter = GitHubAdapter()
    failure_evt = adapter.record_sync_failure(
        project_id="mini-me",
        change_id="synthetic-change",
        operation="sync_issues",
        error_message="GitHub service unavailable (503)",
    )
    in_memory_uow.events.save(failure_evt)

    events = in_memory_uow.events.list_events(project_id="mini-me")
    assert len(events) == 1
    assert events[0].event_type == EventType.SYNC_FAILED

    # Reconcile
    reconciled_evt = adapter.record_sync_reconciled(
        project_id="mini-me",
        change_id="synthetic-change",
        operation="sync_issues",
    )
    in_memory_uow.events.save(reconciled_evt)
    all_events = in_memory_uow.events.list_events(project_id="mini-me")
    assert len(all_events) == 2


# --- Capability: status-observability ---


def test_acceptance_status_surface(in_memory_uow):
    """Scenario: Operator requests Foundation status."""
    service = ProjectService(in_memory_uow)
    service.register_project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
    )
    status_service = StatusService(in_memory_uow)
    status_data = status_service.get_system_status()

    assert "database" in status_data
    assert status_data["database"]["engine"] == "PostgreSQL"
    assert status_data["projects_count"] == 1
    assert status_data["projects"][0]["project_id"] == "mini-me"


def test_acceptance_structured_correlation_and_redaction():
    """Scenario: Operation emits diagnostic evidence with stable correlation IDs and secret redaction."""
    set_correlation_context(project_id="mini-me", change_id="synthetic-change", operation_id="op-101")
    ctx = get_correlation_context()
    assert ctx["project_id"] == "mini-me"
    assert ctx["change_id"] == "synthetic-change"
    assert ctx["operation_id"] == "op-101"

    text = "Secret: postgresql://user:pass1234@localhost/db and token=secret_token_abc"
    redacted = redact_secrets(text)
    assert "pass1234" not in redacted
    assert "secret_token_abc" not in redacted
    assert "[REDACTED]" in redacted

    clear_correlation_context()


def test_acceptance_metrics_facts_retention(in_memory_uow):
    """Scenario: Readiness changes over time; timestamped facts are retained."""
    fact1 = MetricFact(
        metric_name="readiness_evaluation",
        project_id="mini-me",
        change_id="synthetic-change",
        fact_value=0.0,
        details={"is_ready": False, "unmet_reasons": ["missing design.md"]},
    )
    in_memory_uow.metrics.save(fact1)

    fact2 = MetricFact(
        metric_name="readiness_evaluation",
        project_id="mini-me",
        change_id="synthetic-change",
        fact_value=1.0,
        details={"is_ready": True, "unmet_reasons": []},
    )
    in_memory_uow.metrics.save(fact2)

    facts = in_memory_uow.metrics.list_facts(project_id="mini-me", change_id="synthetic-change")
    assert len(facts) == 2
    assert facts[0].fact_value == 1.0  # Most recent first
    assert facts[1].fact_value == 0.0
