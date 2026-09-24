"""End-to-end lifecycle gate chain and CLOSED semantics tests (Phase F)."""

from __future__ import annotations

from pathlib import Path

from conftest import ReadinessGitHubStub, create_isolated_openspec_change, init_git_repo
from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import EventType, ReviewStatus, ReviewVerdict
from minime.domain.models import (
    Change,
    Event,
    Job,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
    ProjectBinding,
    ProjectManagedRepositoryBinding,
    Review,
)
from minime.services.authorship_service import AuthorshipService
from minime.services.lifecycle_gates import GateStatus, VerifyGate
from minime.services.openspec_integrity import OpenSpecIntegrityService
from minime.services.openspec_sync import OpenSpecSyncService
from minime.services.orchestration_service import OrchestrationService
from minime.services.readiness_service import ReadinessService
from minime.services.review_evidence import validate_review_authority


def _project(**overrides) -> Project:
    kwargs = dict(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )
    kwargs.update(overrides)
    return Project(**kwargs)


def _record_event(uow, change_name: str, event_type: EventType) -> None:
    uow.events.save(Event(event_type=event_type, project_id="mini-me", change_id=change_name))


def test_lifecycle_gate_chain_end_to_end(in_memory_uow, tmp_path: Path):
    """Strict-validity -> APPLY -> VERIFY -> sync -> archive -> integrity audit PASS."""
    init_git_repo(tmp_path)
    create_isolated_openspec_change(
        tmp_path, "chain-change", tasks_content="- [x] 1.1 Do thing\n"
    )
    project = _project()
    in_memory_uow.projects.save(project)
    in_memory_uow.bindings.save(
        ProjectBinding(
            project_id="mini-me",
            repository="silverberdi/mini-me",
            github_issue_number=1,
            openspec_change_name="chain-change",
            is_valid=True,
        )
    )
    in_memory_uow.changes.save(Change(project_id="mini-me", name="chain-change"))

    # 1. Strict-validity (Phase A)
    readiness = ReadinessService(
        in_memory_uow, github_adapter=ReadinessGitHubStub()
    ).evaluate_change_readiness("mini-me", "chain-change", str(tmp_path))
    assert readiness.is_ready

    # 2. APPLY attribution (Phase B)
    admission = OrchestrationService(
        in_memory_uow, project_root=tmp_path, github_adapter=ReadinessGitHubStub()
    ).admit_change("mini-me", "chain-change", tmp_path)
    assert admission.admitted is True

    # 3. VERIFY (Phase C)
    verify = VerifyGate(OpenSpecAdapter()).evaluate(
        project=project,
        change_name="chain-change",
        project_root=tmp_path,
        candidate_sha="cand-sha",
        changed_paths=["src/impl.py"],
    )
    assert verify.status is GateStatus.PASS

    # 4. Sync verification (Phase D)
    in_memory_uow.project_managed_repository_bindings.save(
        ProjectManagedRepositoryBinding(
            project_id="mini-me",
            canonical_repository_identity="github.com/silverberdi/mini-me",
            managed_repository_root=str(tmp_path.resolve()),
            worktree_parent_dir=str((tmp_path / ".minime" / "worktrees").resolve()),
        )
    )
    sync_service = OpenSpecSyncService(tmp_path, uow=in_memory_uow)
    synced = sync_service.sync_change_specs("openspec", "chain-change", project_id="mini-me")
    assert sync_service.verify_sync("openspec", "chain-change", synced)

    # 5. Archive verification (Phase D)
    archived = sync_service.archive_change("openspec", "chain-change", project_id="mini-me")
    assert sync_service.verify_archive("openspec", "chain-change", archived)

    # 6. Integrity audit (Phase E) — repository is now healthy.
    audit = OpenSpecIntegrityService(in_memory_uow, project_root=tmp_path).run_audit("mini-me")
    assert audit.overall_status == "PASS"


def test_review_authority_remains_functional_in_gate_chain(in_memory_uow):
    """The existing review candidate binding gate still passes for a bound candidate."""
    project = _project()
    in_memory_uow.projects.save(project)
    run = OrchestrationRun(
        run_id="run-1",
        project_id="mini-me",
        change_name="chain-change",
        base_sha="base-sha",
        active_job_id="job-1",
    )
    job = Job(
        job_id="job-1",
        project_id="mini-me",
        change_name="chain-change",
        implementer_role="codex",
        candidate_sha="cand-sha",
        base_sha="base-sha",
    )
    candidate = OrchestrationCandidate(
        run_id="run-1",
        generation=1,
        candidate_sha="cand-sha",
        base_sha="base-sha",
        manifest_id="manifest-1",
        manifest_hash="hash-1",
    )
    in_memory_uow.reviews.save(
        Review(
            job_id="job-1",
            project_id="mini-me",
            change_name="chain-change",
            reviewer_role="antigravity",
            orchestration_run_id="run-1",
            candidate_generation=1,
            candidate_sha="cand-sha",
            base_sha="base-sha",
            manifest_id="manifest-1",
            manifest_hash="hash-1",
            status=ReviewStatus.REVIEW_COMPLETED,
            verdict=ReviewVerdict.READY_TO_MERGE,
        )
    )

    valid, verdict, reason = validate_review_authority(
        in_memory_uow, run, job, candidate, AuthorshipService()
    )
    assert valid is True
    assert verdict == ReviewVerdict.READY_TO_MERGE
    assert reason is None


def test_closed_not_satisfied_when_delivery_unproven(in_memory_uow):
    """OpenSpec lifecycle complete but deployment unproven -> CLOSED not satisfied."""
    for event_type in (
        EventType.READY_FOR_HUMAN_MERGE,
        EventType.POST_MERGE_SYNC_VERIFIED,
        EventType.POST_MERGE_ARCHIVE_VERIFIED,
    ):
        _record_event(in_memory_uow, "closed-partial", event_type)

    service = OpenSpecIntegrityService(in_memory_uow, project_root=".")
    result = service.evaluate_closed("mini-me", "closed-partial")

    assert result.openspec_lifecycle_complete is True
    assert result.delivery_complete is False
    assert result.satisfied is False
    assert "deploy" in result.missing_requirements


def test_closed_satisfied_with_lifecycle_and_delivery(in_memory_uow):
    """OpenSpec lifecycle + delivery complete -> CLOSED satisfied."""
    for event_type in (
        EventType.READY_FOR_HUMAN_MERGE,
        EventType.POST_MERGE_SYNC_VERIFIED,
        EventType.POST_MERGE_ARCHIVE_VERIFIED,
        EventType.MERGE_DETECTED,
        EventType.PRODUCTION_DEPLOYED,
        EventType.PRODUCTION_VERIFIED,
    ):
        _record_event(in_memory_uow, "closed-full", event_type)

    service = OpenSpecIntegrityService(in_memory_uow, project_root=".")
    result = service.evaluate_closed("mini-me", "closed-full")

    assert result.openspec_lifecycle_complete is True
    assert result.delivery_complete is True
    assert result.satisfied is True
    assert result.missing_requirements == ()


