"""Tests for autonomous candidate worktree creation and execution startup upon admission."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from tests.conftest import (
    InMemoryPersistenceUnitOfWork,
    attach_local_bare_origin,
    create_isolated_openspec_change,
    init_git_repo,
    publish_local_intake_ref,
)

from minime.adapters.github import GitHubAdapter
from minime.domain.enums import (
    AdmissionDecision,
    ChangeStatus,
    ExternalOutcome,
    ExternalReasonCode,
    IntakeWorkspaceCreationState,
    IntakeWorkspacePublicationState,
    OrchestrationStage,
    ProviderHealthStatus,
    RetrySafety,
)
from minime.domain.models import (
    Change,
    ExternalActionResult,
    IntakeWorkspaceOwnership,
    Project,
    ProjectBinding,
    ProjectManagedRepositoryBinding,
    ProviderHealth,
)
from minime.services.readiness_service import ReadinessService
from minime.services.scheduler_service import SchedulerService


def test_autonomous_admission_and_run_creation(
    tmp_path: Path, in_memory_uow: InMemoryPersistenceUnitOfWork
):
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="mini-me",
        name="016-autonomous-queue-work-selection",
        status=ChangeStatus.READY,
    )
    in_memory_uow.changes.save(change)

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=45,
        openspec_change_name="016-autonomous-queue-work-selection",
        is_valid=True,
    )
    in_memory_uow.bindings.save(binding)

    in_memory_uow.provider_health.save(
        ProviderHealth(
            health_id="ph-codex",
            provider="codex",
            status=ProviderHealthStatus.AVAILABLE,
        )
    )
    in_memory_uow.provider_health.save(
        ProviderHealth(
            health_id="ph-antigravity",
            provider="antigravity",
            status=ProviderHealthStatus.AVAILABLE,
        )
    )

    init_git_repo(tmp_path)
    import subprocess

    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/silverberdi/mini-me.git"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / ".minime-managed-project.json").write_text(
        json.dumps(
            {
                "project_id": "mini-me",
                "canonical_repository_identity": "github.com/silverberdi/mini-me",
            }
        ),
        encoding="utf-8",
    )
    mb = ProjectManagedRepositoryBinding(
        project_id="mini-me",
        canonical_repository_identity="github.com/silverberdi/mini-me",
        managed_repository_root=str(tmp_path),
        worktree_parent_dir=str(tmp_path / ".minime" / "worktrees"),
    )
    (tmp_path / ".minime" / "worktrees").mkdir(parents=True, exist_ok=True)
    in_memory_uow.project_managed_repository_bindings.save(mb)
    attach_local_bare_origin(tmp_path, uow=in_memory_uow, project_id="mini-me")
    create_isolated_openspec_change(tmp_path, change_name="016-autonomous-queue-work-selection")
    published_sha = publish_local_intake_ref(tmp_path, "016-autonomous-queue-work-selection")
    managed_binding = in_memory_uow.project_managed_repository_bindings.get_by_project_id(
        "mini-me"
    )
    in_memory_uow.intake_workspace_ownerships.save(
        IntakeWorkspaceOwnership(
            workspace_id="ws-016-autonomous-queue-work-selection",
            project_id="mini-me",
            item_key="016-autonomous-queue-work-selection",
            saga_id="saga-016-autonomous-queue-work-selection",
            change_name="016-autonomous-queue-work-selection",
            canonical_workspace_path=str(tmp_path),
            canonical_repository_identity=managed_binding.canonical_repository_identity,
            base_sha=published_sha,
            head_sha=published_sha,
            creation_state=IntakeWorkspaceCreationState.ACTIVE,
            publication_state=IntakeWorkspacePublicationState.PUBLISHED,
            published_ref="refs/minime/intake/016-autonomous-queue-work-selection",
            published_sha=published_sha,
        )
    )

    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.validate_issue_binding.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="fake",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=True,
    )

    scheduler = SchedulerService(
        uow=in_memory_uow,
        project_root=tmp_path,
        readiness_service=ReadinessService(in_memory_uow, github_adapter=mock_gh),
    )

    # Execute admission
    decision, decision_record, run = scheduler.admit_work_item(
        "mini-me", "016-autonomous-queue-work-selection"
    )

    assert decision == AdmissionDecision.ADMITTED
    assert decision_record.decision == AdmissionDecision.ADMITTED
    assert run is not None
    assert run.project_id == "mini-me"
    assert run.change_name == "016-autonomous-queue-work-selection"
    assert run.current_stage == OrchestrationStage.ADMITTED
    assert run.is_active is True

    # Repeated tick / admission must be refused / idempotent
    dec2, rec2, run2 = scheduler.admit_work_item("mini-me", "016-autonomous-queue-work-selection")
    assert dec2 == AdmissionDecision.REFUSED
    assert run2 is None
    assert rec2.decision == AdmissionDecision.REFUSED
