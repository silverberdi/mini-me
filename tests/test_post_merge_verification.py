"""Deterministic post-merge SYNC/ARCHIVE verification tests (Phase D)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from minime.domain.enums import (
    EventType,
    ExternalOutcome,
    ExternalReasonCode,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProjectStatus,
    RetrySafety,
)
from minime.domain.models import (
    ExternalActionResult,
    Job,
    OrchestrationRun,
    Project,
    ProjectBinding,
)
from minime.services.openspec_sync import OpenSpecSyncService
from minime.services.post_merge_service import PostMergeReconciliationService
from test_post_merge_closure import InMemoryUnitOfWork


def _github_adapter():
    adapter = MagicMock()
    pr_details = {
        "number": 54,
        "state": "closed",
        "is_merged": True,
        "merged_at": "2026-09-03T10:00:00Z",
        "merged_by_login": "silverberdi",
        "merge_commit_sha": "abcdef1234567890abcdef1234567890abcdef12",
        "head_sha": "695855fc6b6caf022be3f6b32c973c18c51c6afd",
    }
    adapter.get_pull_request_details.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="mock",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=pr_details,
        external_id="54",
    )
    adapter.close_issue.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="mock",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.UNSAFE,
        data=True,
    )
    adapter.update_project_item_status.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="mock",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.UNSAFE,
        data=True,
    )
    adapter.delete_remote_branch.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="mock",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.UNSAFE,
        data=True,
    )
    return adapter


def _make_change(
    tmp_path: Path,
    name: str = "test-change",
    delta: str = "# Spec: Cap1\n\n## Requirement: R1\n",
) -> Path:
    change_dir = tmp_path / "openspec" / "changes" / name
    specs_dir = change_dir / "specs" / "cap1"
    specs_dir.mkdir(parents=True)
    (specs_dir / "spec.md").write_text(delta)
    (change_dir / "tasks.md").write_text("- [x] 1.1 Done\n")
    return change_dir


def _setup_uow(uow: InMemoryUnitOfWork, change_name: str = "test-change", run_id: str = "run-123"):
    uow.projects.save(
        Project(
            project_id="mini-me",
            display_name="mini me",
            repository="silverberdi/mini-me",
            base_branch="main",
            openspec_path="openspec",
            status=ProjectStatus.ACTIVE,
        )
    )
    uow.bindings.save(
        ProjectBinding(
            project_id="mini-me",
            repository="silverberdi/mini-me",
            github_issue_number=53,
            github_pr_number=54,
            openspec_change_name=change_name,
            is_valid=True,
        )
    )
    uow.orchestration_runs.save(
        OrchestrationRun(
            run_id=run_id,
            project_id="mini-me",
            change_name=change_name,
            base_sha="base123",
            current_stage=OrchestrationStage.PR_PREPARED,
            stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
            active_job_id="job-123",
            current_candidate_sha="cand123",
            is_active=True,
        )
    )
    uow.jobs.save(
        Job(
            job_id="job-123",
            project_id="mini-me",
            change_name=change_name,
            status=JobStatus.READY_TO_MERGE,
            implementer_role="codex",
        )
    )


# --- OpenSpecSyncService verification ---------------------------------------


def test_verify_sync_confirms_requirements(tmp_path: Path):
    _make_change(tmp_path)
    service = OpenSpecSyncService(tmp_path)
    synced = service.sync_change_specs("openspec", "test-change")
    assert synced.outcome == ExternalOutcome.SUCCESS
    assert "cap1" in synced.data
    verify_res = service.verify_sync("openspec", "test-change", synced)
    assert verify_res.outcome == ExternalOutcome.SUCCESS
    assert verify_res.data is True


def test_verify_sync_detects_missing_requirement(tmp_path: Path):
    _make_change(tmp_path)
    service = OpenSpecSyncService(tmp_path)
    synced = service.sync_change_specs("openspec", "test-change")
    # Corrupt the canonical spec so the requirement is no longer present.
    canonical = tmp_path / "openspec" / "specs" / "cap1" / "spec.md"
    canonical.write_text("# Spec: Cap1\n\n## Requirement: DIFFERENT\n")
    verify_res = service.verify_sync("openspec", "test-change", synced)
    assert verify_res.outcome == ExternalOutcome.FAILURE
    assert verify_res.data is False


def test_archive_change_raises_on_collision(tmp_path: Path):
    change_dir = _make_change(tmp_path)
    archive_root = tmp_path / "openspec" / "changes" / "archive" / "2026-09-03-test-change"
    archive_root.mkdir(parents=True)
    (archive_root / "spec.md").write_text("existing archive\n")

    service = OpenSpecSyncService(tmp_path)
    res = service.archive_change("openspec", "test-change", target_date="2026-09-03")
    assert res.outcome == ExternalOutcome.AMBIGUOUS
    assert res.reason_code == ExternalReasonCode.POSTCONDITION_NOT_PROVEN

    # Change must remain active after the collision.
    assert change_dir.exists()


# --- PostMergeReconciliationService terminal gating -------------------------


def test_post_merge_completes_when_sync_and_archive_verified(tmp_path: Path):
    uow = InMemoryUnitOfWork()
    _setup_uow(uow)
    _make_change(tmp_path)

    service = PostMergeReconciliationService(
        uow=uow, project_root=tmp_path, github_adapter=_github_adapter()
    )
    service.verify_candidate_ancestry = MagicMock(return_value=True)

    result = service.reconcile_post_merge("mini-me", "test-change", run_id="run-123")

    assert result.success is True
    assert result.terminal_stage == OrchestrationStage.COMPLETED
    assert result.terminal_job_status == JobStatus.COMPLETED

    updated_run = uow.orchestration_runs.get_by_id("run-123")
    assert updated_run.stop_outcome == OrchestrationStopOutcome.COMPLETED
    assert updated_run.is_active is False

    event_types = [e.event_type for e in uow._events]
    assert EventType.POST_MERGE_SYNC_VERIFIED in event_types
    assert EventType.POST_MERGE_ARCHIVE_VERIFIED in event_types


def test_post_merge_blocks_when_archive_fails(tmp_path: Path):
    uow = InMemoryUnitOfWork()
    _setup_uow(uow)
    _make_change(tmp_path)

    mock_sync = MagicMock(spec=OpenSpecSyncService)
    mock_sync.sync_change_specs.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="openspec_sync",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=["cap1"],
    )
    mock_sync.verify_sync.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="openspec_sync",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=True,
    )
    mock_sync.archive_change.return_value = ExternalActionResult(
        outcome=ExternalOutcome.AMBIGUOUS,
        source_adapter="openspec_archive",
        reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
        retry_safety=RetrySafety.UNKNOWN,
        data=None,
        error_message="Archive target collision.",
    )

    service = PostMergeReconciliationService(
        uow=uow,
        project_root=tmp_path,
        github_adapter=_github_adapter(),
        openspec_sync=mock_sync,
    )
    service.verify_candidate_ancestry = MagicMock(return_value=True)

    result = service.reconcile_post_merge("mini-me", "test-change", run_id="run-123")

    assert result.success is False
    assert result.terminal_stage is not OrchestrationStage.COMPLETED
    assert result.error_message is not None

    updated_run = uow.orchestration_runs.get_by_id("run-123")
    assert updated_run.stop_outcome == OrchestrationStopOutcome.WAITING_EXTERNAL
    assert updated_run.current_stage is not OrchestrationStage.COMPLETED
    assert updated_run.is_active is True


def test_post_merge_blocks_when_sync_evidence_missing(tmp_path: Path):
    uow = InMemoryUnitOfWork()
    _setup_uow(uow)
    _make_change(tmp_path)

    mock_sync = MagicMock(spec=OpenSpecSyncService)
    mock_sync.sync_change_specs.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="openspec_sync",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=["cap1"],
    )
    mock_sync.verify_sync.return_value = ExternalActionResult(
        outcome=ExternalOutcome.FAILURE,
        source_adapter="openspec_sync",
        reason_code=ExternalReasonCode.EVIDENCE_INSUFFICIENT,
        retry_safety=RetrySafety.SAFE,
        data=False,
    )

    service = PostMergeReconciliationService(
        uow=uow,
        project_root=tmp_path,
        github_adapter=_github_adapter(),
        openspec_sync=mock_sync,
    )
    service.verify_candidate_ancestry = MagicMock(return_value=True)

    result = service.reconcile_post_merge("mini-me", "test-change", run_id="run-123")

    assert result.success is False
    assert result.terminal_stage is not OrchestrationStage.COMPLETED

    updated_run = uow.orchestration_runs.get_by_id("run-123")
    assert updated_run.stop_outcome == OrchestrationStopOutcome.WAITING_EXTERNAL
    assert updated_run.is_active is True
    # Archive must not have run when sync evidence was never verified.
    mock_sync.archive_change.assert_not_called()


def test_post_merge_blocks_when_issue_close_unknown_or_ambiguous(tmp_path: Path):
    uow = InMemoryUnitOfWork()
    _setup_uow(uow)
    _make_change(tmp_path)

    adapter = _github_adapter()
    adapter.close_issue.return_value = ExternalActionResult(
        outcome=ExternalOutcome.UNKNOWN,
        source_adapter="mock",
        reason_code=ExternalReasonCode.UNOBSERVABLE,
        retry_safety=RetrySafety.SAFE,
        data=False,
    )

    service = PostMergeReconciliationService(uow=uow, project_root=tmp_path, github_adapter=adapter)
    service.verify_candidate_ancestry = MagicMock(return_value=True)

    result = service.reconcile_post_merge("mini-me", "test-change", run_id="run-123")

    assert result.success is False
    assert result.issue_closed is False
    assert result.terminal_stage is not OrchestrationStage.COMPLETED
    updated_run = uow.orchestration_runs.get_by_id("run-123")
    assert updated_run.stop_outcome == OrchestrationStopOutcome.WAITING_EXTERNAL
    assert updated_run.is_active is True
    assert "issue_closure" in result.error_message


def test_post_merge_blocks_when_project_item_update_fails(tmp_path: Path):
    uow = InMemoryUnitOfWork()
    _setup_uow(uow)
    _make_change(tmp_path)

    adapter = _github_adapter()
    adapter.update_project_item_status.return_value = ExternalActionResult(
        outcome=ExternalOutcome.FAILURE,
        source_adapter="mock",
        reason_code=ExternalReasonCode.CONFLICT,
        retry_safety=RetrySafety.UNSAFE,
        data=False,
    )

    service = PostMergeReconciliationService(uow=uow, project_root=tmp_path, github_adapter=adapter)
    service.verify_candidate_ancestry = MagicMock(return_value=True)

    result = service.reconcile_post_merge("mini-me", "test-change", run_id="run-123")

    assert result.success is False
    assert result.project_item_updated is False
    assert result.terminal_stage is not OrchestrationStage.COMPLETED
    assert "project_item_done" in result.error_message


def test_post_merge_blocks_when_worktree_cleanup_fails(tmp_path: Path):
    uow = InMemoryUnitOfWork()
    _setup_uow(uow)
    _make_change(tmp_path)

    # Create a fake worktree directory that cannot be removed
    wt_dir = tmp_path / ".minime" / "worktrees" / "job-123"
    wt_dir.mkdir(parents=True)

    service = PostMergeReconciliationService(uow=uow, project_root=tmp_path, github_adapter=_github_adapter())
    service.verify_candidate_ancestry = MagicMock(return_value=True)
    # Mock _clean_worktrees to return failure
    service._clean_worktrees = MagicMock(
        return_value=ExternalActionResult(
            outcome=ExternalOutcome.FAILURE,
            source_adapter="worktree_manager",
            reason_code=ExternalReasonCode.POSTCONDITION_NOT_PROVEN,
            retry_safety=RetrySafety.SAFE,
            data=False,
        )
    )

    result = service.reconcile_post_merge("mini-me", "test-change", run_id="run-123")

    assert result.success is False
    assert result.worktree_cleaned is False
    assert result.terminal_stage is not OrchestrationStage.COMPLETED
    assert "worktree_cleanup" in result.error_message
    event_types = [e.event_type for e in uow._events]
    assert EventType.WORKTREE_CLEANED not in event_types


def test_post_merge_blocks_when_remote_branch_cleanup_fails(tmp_path: Path):
    uow = InMemoryUnitOfWork()
    _setup_uow(uow)
    _make_change(tmp_path)

    adapter = _github_adapter()
    adapter.delete_remote_branch.return_value = ExternalActionResult(
        outcome=ExternalOutcome.UNKNOWN,
        source_adapter="mock",
        reason_code=ExternalReasonCode.UNOBSERVABLE,
        retry_safety=RetrySafety.UNSAFE,
        data=False,
    )

    service = PostMergeReconciliationService(uow=uow, project_root=tmp_path, github_adapter=adapter)
    service.verify_candidate_ancestry = MagicMock(return_value=True)

    result = service.reconcile_post_merge("mini-me", "test-change", run_id="run-123")

    assert result.success is False
    assert result.branch_cleaned is False
    assert result.terminal_stage is not OrchestrationStage.COMPLETED
    assert "branch_cleanup" in result.error_message


def test_archive_preservation_manifest_verification(tmp_path: Path):
    _make_change(tmp_path)
    service = OpenSpecSyncService(tmp_path)

    # Archive happy path
    arc_res = service.archive_change("openspec", "test-change", target_date="2026-09-03")
    assert arc_res.outcome == ExternalOutcome.SUCCESS
    assert arc_res.retry_safety == RetrySafety.UNSAFE
    archived_dir = arc_res.data

    # Verify archive happy path
    v_res = service.verify_archive("openspec", "test-change", arc_res)
    assert v_res.outcome == ExternalOutcome.SUCCESS
    assert v_res.data is True

    # Corrupt archive by deleting expected artifact
    (archived_dir / "tasks.md").unlink()
    v_fail = service.verify_archive("openspec", "test-change", arc_res)
    assert v_fail.outcome == ExternalOutcome.FAILURE
    assert v_fail.data is False
    assert "missing or empty expected files" in v_fail.error_message


def test_sync_and_archive_retry_safety_semantics(tmp_path: Path):
    _make_change(tmp_path)
    service = OpenSpecSyncService(tmp_path)

    # Mutating sync -> RetrySafety.UNSAFE
    sync_res = service.sync_change_specs("openspec", "test-change")
    assert sync_res.outcome == ExternalOutcome.SUCCESS
    assert sync_res.retry_safety == RetrySafety.UNSAFE

    # Mutating archive -> RetrySafety.UNSAFE
    archive_res = service.archive_change("openspec", "test-change", target_date="2026-09-03")
    assert archive_res.outcome == ExternalOutcome.SUCCESS
    assert archive_res.retry_safety == RetrySafety.UNSAFE

