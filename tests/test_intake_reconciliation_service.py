"""Unit and PostgreSQL integration tests for IntakeReconciliationService."""

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    ChangeStatus,
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    IntakeReconciliationDisposition,
    ReadinessState,
    SagaStatus,
    SagaType,
    WorkItemSource,
    WorkItemStatus,
)
from minime.domain.models import (
    BacklogItem,
    Change,
    DurableSaga,
    ExternalActionResult,
    OrchestrationExternalAction,
    Project,
    RecoveryClaimContext,
)
from minime.services.intake_reconciliation_service import IntakeReconciliationService
from minime.services.intake_service import IntakeService
from minime.services.openspec_generator import OpenSpecGenerator
from minime.services.saga_engine import SagaEngine


class FakeGitHubAdapter:
    def __init__(self, issues=None):
        self.issues = issues or {}
        self.close_calls = []

    def get_issue(self, repository: str, number: int):
        data = self.issues.get((repository, number))
        if not data:
            return ExternalActionResult(outcome=ExternalOutcome.FAILURE, source_adapter="github")
        return ExternalActionResult(outcome=ExternalOutcome.SUCCESS, source_adapter="github", data=data)

    def close_issue(self, repository: str, number: int, comment: str = ""):
        self.close_calls.append((repository, number, comment))
        if (repository, number) in self.issues:
            self.issues[(repository, number)]["state"] = "closed"
        return ExternalActionResult(outcome=ExternalOutcome.SUCCESS, source_adapter="github", external_id=str(number))


class FakeContextDiscoveryService:
    def __init__(self, projections=None):
        self.projections = projections or []

    def discover_context_pure(self, project_id: str):
        return None, self.projections


def _setup_harness(tmp_path: Path, issue_state: str = "open", marker_key: str = "issue_create:p1:c1"):
    repo_dir = tmp_path / "managed-repo"
    worktree_dir = tmp_path / "worktrees"

    uow = InMemoryPersistenceUnitOfWork()

    project = Project(
        project_id="p1",
        display_name="Project One",
        repository="github.com/org/managed-repo",
        openspec_path="openspec",
    )
    uow.projects.save(project)

    setup_managed_repository_fixture(
        uow,
        project_id="p1",
        repo_root=repo_dir,
        worktree_parent_dir=worktree_dir,
        canonical_repository_identity="github.com/org/managed-repo",
    )

    item = BacklogItem(
        project_id="p1",
        item_key="key1",
        title="Test Item",
        openspec_change_name="c1",
        source=WorkItemSource.ROADMAP,
        status=WorkItemStatus.PREPARING,
        github_issue_number=101,
    )
    uow.backlog_items.save(item)

    change = Change(
        change_id="c1",
        project_id="p1",
        name="c1",
        status=ChangeStatus.DISCOVERED,
        last_readiness_status=ReadinessState.READY,
    )
    uow.changes.save(change)

    saga = DurableSaga(
        id="saga-1",
        saga_type=SagaType.INTAKE,
        project_id="p1",
        work_item_key="key1",
        change_name="c1",
        status=SagaStatus.IN_PROGRESS,
        current_phase="STARTED",
    )
    uow.durable_sagas.save(saga)

    claim_obj = uow.claims.acquire_or_reacquire("intake:p1:key1", "worker-1", lease_seconds=3600)
    claim = RecoveryClaimContext(
        claim_key=claim_obj.claim_key,
        owner_instance_id=claim_obj.owner_instance_id,
        fence_token=claim_obj.fence_token,
        lease_expires_at=claim_obj.lease_expires_at,
    )

    issue_act = OrchestrationExternalAction(
        id="act-issue",
        saga_id="saga-1",
        action_key="issue_create:p1:c1",
        action_type=ExternalActionType.ISSUE_CREATE,
        target_identity="c1",
        request_fingerprint="key1",
        status=ExternalActionStatus.COMPLETED,
        remote_identifier="101",
    )
    uow.orchestration_external_actions.reserve(issue_act)

    author_act = OrchestrationExternalAction(
        id="act-author",
        saga_id="saga-1",
        action_key="openspec_author:p1:c1",
        action_type=ExternalActionType.OPENSPEC_SYNC,
        target_identity="c1",
        request_fingerprint="key1",
        status=ExternalActionStatus.COMPLETED,
    )
    uow.orchestration_external_actions.reserve(author_act)

    # Intake artifacts are authored only inside the durable Git intake workspace.
    # This fixture intentionally uses the production reservation/activation path
    # rather than fabricating an ownership record or writing into managed base.
    intake = IntakeService(uow, project_root=repo_dir, github_adapter=FakeGitHubAdapter())
    ownership = intake._reserve_intake_workspace(project, item, saga)
    intake._activate_intake_workspace(ownership, project)

    gen = OpenSpecGenerator(repo_dir, uow)
    generated = gen.generate_from_backlog_item(item, project.display_name)
    gen.write_change_to_disk(
        project.openspec_path,
        generated,
        project_id=project.project_id,
        uow=uow,
        target_workspace_path=ownership.canonical_workspace_path,
    )

    gh_fake = FakeGitHubAdapter({
        ("github.com/org/managed-repo", 101): {
            "body": f"Title\n<!-- minime-opkey: {marker_key} -->",
            "state": issue_state,
        }
    })

    return uow, repo_dir, claim, gh_fake


def _get_harness_target(uow, repo_dir, project_id="p1", item_key="key1", change_name="c1"):
    intake_repo = getattr(uow, "intake_workspace_ownerships", None)
    ow = intake_repo.get_active_by_item_key(project_id, item_key) if intake_repo else None
    if not ow and intake_repo:
        active_list = intake_repo.list_active()
        for item in active_list:
            if item.project_id == project_id and (item.change_name == change_name or item.item_key == item_key):
                ow = item
                break
    if ow and Path(ow.canonical_workspace_path).exists():
        return Path(ow.canonical_workspace_path) / "openspec" / "changes" / change_name
    return repo_dir / "openspec" / "changes" / change_name


def test_invalid_discovery_happy_path(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    target = _get_harness_target(uow, repo_dir)
    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    res = service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)

    assert res.disposition == IntakeReconciliationDisposition.INVALID_DISCOVERY
    assert res.backlog_status == WorkItemStatus.CANCELLED
    assert res.change_status == ChangeStatus.CANCELLED
    assert res.saga_status == SagaStatus.CANCELLED
    assert res.already_converged is False
    assert len(gh_fake.close_calls) == 1

    assert not target.exists()


def test_deferred_roadmap_happy_path(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    proj_item = BacklogItem(project_id="p1", item_key="key1", title="Test Item", status=WorkItemStatus.BACKLOG)
    discovery = FakeContextDiscoveryService(projections=[proj_item])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    res = service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.DEFERRED_ROADMAP, claim)

    assert res.disposition == IntakeReconciliationDisposition.DEFERRED_ROADMAP
    assert res.backlog_status == WorkItemStatus.BLOCKED
    assert res.change_status == ChangeStatus.BLOCKED
    assert res.saga_status == SagaStatus.CANCELLED


def test_invalid_rejected_if_discovery_still_returns_key(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    proj_item = BacklogItem(project_id="p1", item_key="key1", title="Test Item", status=WorkItemStatus.BACKLOG)
    discovery = FakeContextDiscoveryService(projections=[proj_item])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="INVALID_DISCOVERY requires item absence from pure discovery"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_deferred_rejected_for_non_roadmap(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    item = uow.backlog_items.get_by_project_and_key("p1", "key1")
    item.source = WorkItemSource.LOCAL_BACKLOG
    uow.backlog_items.save(item)

    proj_item = BacklogItem(project_id="p1", item_key="key1", title="Test Item", status=WorkItemStatus.BACKLOG)
    discovery = FakeContextDiscoveryService(projections=[proj_item])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="DEFERRED_ROADMAP requires a ROADMAP source item"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.DEFERRED_ROADMAP, claim)


def test_deferred_rejected_when_pure_projection_ready(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    proj_item = BacklogItem(project_id="p1", item_key="key1", title="Test Item", status=WorkItemStatus.READY)
    discovery = FakeContextDiscoveryService(projections=[proj_item])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="DEFERRED_ROADMAP requires a non-ready ROADMAP projection"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.DEFERRED_ROADMAP, claim)


def test_missing_issue_create_proof_rejected(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    act = uow.orchestration_external_actions.list_by_saga("saga-1")[0]
    uow.orchestration_external_actions.update_status(act.action_key, ExternalActionStatus.FAILED)

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="missing exact completed intake ISSUE_CREATE evidence"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_wrong_issue_create_saga_rejected(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    act = uow.orchestration_external_actions.get_by_action_key("issue_create:p1:c1")
    uow.orchestration_external_actions._store[act.action_id] = act.model_copy(update={"saga_id": "other-saga"})

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="wrong ISSUE_CREATE saga"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_issue_marker_mismatch_rejected(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path, marker_key="wrong:marker")
    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="issue close checkpoint not proven"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_already_closed_issue_does_not_close_again(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path, issue_state="closed")
    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    res = service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)
    assert res.issue_reconciled is True
    assert len(gh_fake.close_calls) == 0


def test_open_issue_closes_exactly_once(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path, issue_state="open")
    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)
    assert len(gh_fake.close_calls) == 1


def test_missing_openspec_sync_proof_rejected(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    author_act = next(a for a in uow.orchestration_external_actions.list_by_saga("saga-1") if a.action_key == "openspec_author:p1:c1")
    uow.orchestration_external_actions.update_status(author_act.action_key, ExternalActionStatus.FAILED)

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="missing exact completed intake OPENSPEC_SYNC evidence"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_manifest_equals_writer_output(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    worktree_dir = tmp_path / "worktrees"
    uow = InMemoryPersistenceUnitOfWork()

    project = Project(project_id="p1", display_name="Display", repository="github.com/org/repo", openspec_path="openspec")
    uow.projects.save(project)

    setup_managed_repository_fixture(
        uow,
        project_id="p1",
        repo_root=repo_dir,
        worktree_parent_dir=worktree_dir,
        canonical_repository_identity="github.com/org/repo",
    )

    item = BacklogItem(project_id="p1", item_key="key1", title="Title", openspec_change_name="c1")
    uow.backlog_items.save(item)

    saga = DurableSaga(
        id="manifest-saga",
        saga_type=SagaType.INTAKE,
        project_id="p1",
        work_item_key="key1",
        change_name="c1",
        status=SagaStatus.IN_PROGRESS,
        current_phase="STARTED",
    )
    uow.durable_sagas.save(saga)
    intake = IntakeService(uow, project_root=repo_dir, github_adapter=FakeGitHubAdapter())
    ownership = intake._reserve_intake_workspace(project, item, saga)
    intake._activate_intake_workspace(ownership, project)

    gen = OpenSpecGenerator(repo_dir, uow)
    generated = gen.generate_from_backlog_item(item, project.display_name)
    manifest = gen.build_artifact_manifest(generated)
    target_dir = gen.write_change_to_disk(
        project.openspec_path,
        generated,
        project_id=project.project_id,
        uow=uow,
        target_workspace_path=ownership.canonical_workspace_path,
    )

    actual_files = {str(p.relative_to(target_dir)) for p in target_dir.rglob("*") if p.is_file()}
    assert set(manifest.files) == actual_files

    base_repo = Path(ownership.canonical_workspace_path)

    ls_files = subprocess.run(["git", "-C", str(base_repo), "ls-files", "--", str(target_dir)], capture_output=True, text=True).stdout.strip()
    assert ls_files == ""

    status = subprocess.run(["git", "-C", str(base_repo), "status", "--porcelain", "--", str(target_dir)], capture_output=True, text=True).stdout.strip()
    assert "??" in status


def test_tracked_file_rejects_rollback(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    target = _get_harness_target(uow, repo_dir)
    ow = uow.intake_workspace_ownerships.get_active_by_item_key("p1", "c1") or uow.intake_workspace_ownerships.get_active_by_item_key("p1", "key1")
    base_repo = Path(ow.canonical_workspace_path) if ow else repo_dir
    subprocess.run(["git", "-C", str(base_repo), "add", str(target)], check=True)

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="tracked file rejects rollback"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_unexpected_untracked_file_rejects_rollback(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    target = _get_harness_target(uow, repo_dir)
    (target / "unexpected.txt").write_text("evil")

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="unexpected untracked file rejects rollback"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_symlink_escape_rejects_rollback(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    target = _get_harness_target(uow, repo_dir)
    outside = tmp_path / "outside.txt"
    outside.write_text("external")
    (target / "link.txt").symlink_to(outside)

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="symlink escape rejects rollback"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_absent_target_is_idempotent_success(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    target = _get_harness_target(uow, repo_dir)

    for p in sorted((p for p in target.rglob("*") if p.is_file()), reverse=True):
        p.unlink()
    for p in sorted((p for p in target.rglob("*") if p.is_dir()), reverse=True):
        p.rmdir()
    target.rmdir()
    assert not target.exists()

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    res = service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)
    assert res.openspec_reconciled is True


def test_saga_cancelled_last(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    res = service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)
    saga = uow.durable_sagas.get_by_id("saga-1")
    assert saga.status == SagaStatus.CANCELLED
    assert res.saga_status == SagaStatus.CANCELLED


def test_second_complete_invocation_idempotent(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    res1 = service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)
    assert res1.already_converged is False

    res2 = service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)
    assert res2.already_converged is True
    assert res2.backlog_status == WorkItemStatus.CANCELLED
    assert res2.change_status == ChangeStatus.CANCELLED
    assert res2.saga_status == SagaStatus.CANCELLED


def test_cancelled_saga_cannot_resume(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)
    saga_engine = SagaEngine(uow)

    resumed = saga_engine.resume_saga("saga-1", claim_context=claim)
    assert resumed.status == SagaStatus.CANCELLED


def test_wrong_openspec_sync_saga_rejected(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    author_act = uow.orchestration_external_actions.get_by_action_key("openspec_author:p1:c1")
    uow.orchestration_external_actions._store[author_act.action_id] = author_act.model_copy(update={"saga_id": "other-saga"})

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="wrong OPENSPEC_SYNC saga"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_wrong_openspec_sync_target_rejected(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    author_act = uow.orchestration_external_actions.get_by_action_key("openspec_author:p1:c1")
    uow.orchestration_external_actions._store[author_act.action_id] = author_act.model_copy(update={"target_identity": "other-target"})

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="wrong OPENSPEC_SYNC target"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_wrong_openspec_sync_fingerprint_rejected(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    author_act = uow.orchestration_external_actions.get_by_action_key("openspec_author:p1:c1")
    uow.orchestration_external_actions._store[author_act.action_id] = author_act.model_copy(update={"request_fingerprint": "other-fingerprint"})

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="wrong OPENSPEC_SYNC fingerprint"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_wrong_issue_create_target_rejected(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    issue_act = uow.orchestration_external_actions.get_by_action_key("issue_create:p1:c1")
    uow.orchestration_external_actions._store[issue_act.action_id] = issue_act.model_copy(update={"target_identity": "other-target"})

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="wrong ISSUE_CREATE target"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_wrong_issue_create_fingerprint_rejected(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    issue_act = uow.orchestration_external_actions.get_by_action_key("issue_create:p1:c1")
    uow.orchestration_external_actions._store[issue_act.action_id] = issue_act.model_copy(update={"request_fingerprint": "other-fingerprint"})

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="wrong ISSUE_CREATE fingerprint"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_terminal_state_missing_rollback_checkpoint_rejected(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    saga = uow.durable_sagas.get_by_id("saga-1")
    saga.status = SagaStatus.CANCELLED
    uow.durable_sagas.save(saga)

    item = uow.backlog_items.get_by_project_and_key("p1", "key1")
    item_updated = item.model_copy(update={"status": WorkItemStatus.CANCELLED})
    uow.backlog_items._store[item.item_id] = item_updated

    change = uow.changes.get_by_name("p1", "c1")
    change_updated = change.model_copy(update={"status": ChangeStatus.CANCELLED})
    uow.changes._store[change.change_id] = change_updated

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="terminal state missing required reconciliation checkpoints"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_ignored_file_rejects_rollback(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    target = _get_harness_target(uow, repo_dir)
    ow = uow.intake_workspace_ownerships.get_active_by_item_key("p1", "key1")
    base_repo = Path(ow.canonical_workspace_path) if ow else repo_dir
    gitignore = base_repo / ".gitignore"
    gitignore.write_text("*.ignored\n")
    (target / "extra.ignored").write_text("ignored content")

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="unexpected untracked file rejects rollback"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_ready_backlog_refused_for_reconciliation(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    item = uow.backlog_items.get_by_project_and_key("p1", "key1")
    item_updated = item.model_copy(update={"status": WorkItemStatus.READY})
    uow.backlog_items._store[item.item_id] = item_updated

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="invalid backlog source state for INVALID_DISCOVERY reconciliation"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


def test_ready_change_refused_for_reconciliation(tmp_path: Path):
    uow, repo_dir, claim, gh_fake = _setup_harness(tmp_path)
    change = uow.changes.get_by_name("p1", "c1")
    change_updated = change.model_copy(update={"status": ChangeStatus.READY})
    uow.changes._store[change.change_id] = change_updated

    discovery = FakeContextDiscoveryService(projections=[])
    service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)

    with pytest.raises(ValueError, match="invalid change source state for INVALID_DISCOVERY reconciliation"):
        service.reconcile_abandoned_intake("p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)


# ==============================================================================
# PostgreSQL Integration Test
# ==============================================================================

def _get_pg_url() -> str | None:
    return os.environ.get("MINIME_TEST_DATABASE_URL") or "postgresql+psycopg://testuser@localhost:54333/minime_test"


def test_postgres_intake_reconciliation_integration(tmp_path: Path):
    url = _get_pg_url()
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception:
        pytest.skip("PostgreSQL test database server is not reachable.")

    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    repo_dir = tmp_path / "pg-repo"
    worktree_dir = tmp_path / "worktrees"

    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)

        project = Project(
            project_id="pg-p1",
            display_name="PG Project",
            repository="github.com/org/pg-repo",
            openspec_path="openspec",
        )
        uow.projects.save(project)

        setup_managed_repository_fixture(
            uow,
            project_id="pg-p1",
            repo_root=repo_dir,
            worktree_parent_dir=worktree_dir,
            canonical_repository_identity="github.com/org/pg-repo",
        )

        item = BacklogItem(
            project_id="pg-p1",
            item_key="key1",
            title="PG Item",
            openspec_change_name="pg-c1",
            source=WorkItemSource.ROADMAP,
            status=WorkItemStatus.PREPARING,
            github_issue_number=202,
        )
        uow.backlog_items.save(item)

        change = Change(
            change_id="pg-c1",
            project_id="pg-p1",
            name="pg-c1",
            status=ChangeStatus.DISCOVERED,
            last_readiness_status=ReadinessState.READY,
        )
        uow.changes.save(change)

        saga = DurableSaga(
            id="pg-saga-1",
            saga_type=SagaType.INTAKE,
            project_id="pg-p1",
            work_item_key="key1",
            change_name="pg-c1",
            status=SagaStatus.IN_PROGRESS,
            current_phase="STARTED",
        )
        uow.durable_sagas.save(saga)

        claim_obj = uow.claims.acquire_or_reacquire("intake:pg-p1:key1", "pg-worker", lease_seconds=3600)
        claim = RecoveryClaimContext(
            claim_key=claim_obj.claim_key,
            owner_instance_id=claim_obj.owner_instance_id,
            fence_token=claim_obj.fence_token,
            lease_expires_at=claim_obj.lease_expires_at,
        )

        issue_act = OrchestrationExternalAction(
            id="pg-act-issue",
            saga_id="pg-saga-1",
            action_key="issue_create:pg-p1:pg-c1",
            action_type=ExternalActionType.ISSUE_CREATE,
            target_identity="pg-c1",
            request_fingerprint="key1",
            status=ExternalActionStatus.COMPLETED,
            remote_identifier="202",
        )
        uow.orchestration_external_actions.reserve(issue_act)

        author_act = OrchestrationExternalAction(
            id="pg-act-author",
            saga_id="pg-saga-1",
            action_key="openspec_author:pg-p1:pg-c1",
            action_type=ExternalActionType.OPENSPEC_SYNC,
            target_identity="pg-c1",
            request_fingerprint="key1",
            status=ExternalActionStatus.COMPLETED,
        )
        uow.orchestration_external_actions.reserve(author_act)

        intake = IntakeService(uow, project_root=repo_dir, github_adapter=FakeGitHubAdapter())
        ownership = intake._reserve_intake_workspace(project, item, saga)
        intake._activate_intake_workspace(ownership, project)

        gen = OpenSpecGenerator(repo_dir, uow)
        generated = gen.generate_from_backlog_item(item, project.display_name)
        gen.write_change_to_disk(
            project.openspec_path,
            generated,
            project_id=project.project_id,
            uow=uow,
            target_workspace_path=ownership.canonical_workspace_path,
        )
        uow.commit()

    gh_fake = FakeGitHubAdapter({
        ("github.com/org/pg-repo", 202): {
            "body": "Title\n<!-- minime-opkey: issue_create:pg-p1:pg-c1 -->",
            "state": "open",
        }
    })

    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        discovery = FakeContextDiscoveryService(projections=[])
        service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)
        claim_obj = uow.claims.get_by_key("intake:pg-p1:key1")
        claim = RecoveryClaimContext(
            claim_key=claim_obj.claim_key,
            owner_instance_id=claim_obj.owner_instance_id,
            fence_token=claim_obj.fence_token,
            lease_expires_at=claim_obj.lease_expires_at,
        )

        res1 = service.reconcile_abandoned_intake("pg-p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)

        assert res1.backlog_status == WorkItemStatus.CANCELLED
        assert res1.change_status == ChangeStatus.CANCELLED
        assert res1.saga_status == SagaStatus.CANCELLED
        assert res1.already_converged is False
        assert len(gh_fake.close_calls) == 1

        actions = uow.orchestration_external_actions.list_by_saga("pg-saga-1")
        action_types = {a.action_type for a in actions if a.status == ExternalActionStatus.COMPLETED}
        assert ExternalActionType.ISSUE_CLOSE in action_types
        assert ExternalActionType.OPENSPEC_ROLLBACK in action_types

    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        discovery = FakeContextDiscoveryService(projections=[])
        service = IntakeReconciliationService(uow, project_root=repo_dir, github_adapter=gh_fake, context_discovery_service=discovery)
        claim_obj = uow.claims.get_by_key("intake:pg-p1:key1")
        claim = RecoveryClaimContext(
            claim_key=claim_obj.claim_key,
            owner_instance_id=claim_obj.owner_instance_id,
            fence_token=claim_obj.fence_token,
            lease_expires_at=claim_obj.lease_expires_at,
        )

        res2 = service.reconcile_abandoned_intake("pg-p1", "key1", IntakeReconciliationDisposition.INVALID_DISCOVERY, claim)
        assert res2.already_converged is True
        assert len(gh_fake.close_calls) == 1
