"""Unit and integration tests for 018.3 autonomous post-merge closure."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from minime.domain.enums import (
    EventType,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProjectStatus,
)
from minime.domain.interfaces import GitHubAdapterInterface, PersistenceUnitOfWork
from minime.domain.models import Job, OrchestrationRun, Project, ProjectBinding
from minime.services.openspec_sync import OpenSpecSyncService
from minime.services.post_merge_service import (
    PostMergeReconciliationService,
)


class InMemoryUnitOfWork(PersistenceUnitOfWork):
    """In-memory UnitOfWork mock for isolated service testing."""

    def __init__(self):
        self._runs = {}
        self._jobs = {}
        self._projects = {}
        self._bindings = {}
        self._events = []
        self._metrics = []

        self.orchestration_runs = MagicMock()
        self.orchestration_runs.get_by_id.side_effect = lambda rid: self._runs.get(rid)
        self.orchestration_runs.list_runs.side_effect = self._list_runs
        self.orchestration_runs.save.side_effect = self._save_run

        self.jobs = MagicMock()
        self.jobs.get_by_id.side_effect = lambda jid: self._jobs.get(jid)
        self.jobs.save.side_effect = self._save_job

        self.projects = MagicMock()
        self.projects.get_by_id.side_effect = lambda pid: self._projects.get(pid)
        self.projects.save.side_effect = lambda p: self._projects.update({p.project_id: p})

        self.bindings = MagicMock()
        self.bindings.get_by_project_and_change.side_effect = lambda pid, cname: self._bindings.get(
            f"{pid}:{cname}"
        )
        self.bindings.save.side_effect = lambda b: self._bindings.update(
            {f"{b.project_id}:{b.openspec_change_name}": b}
        )

        self.events = MagicMock()
        self.events.save.side_effect = lambda e: self._events.append(e)

        self.metrics = MagicMock()
        self.metrics.save.side_effect = lambda m: self._metrics.append(m)

        self.preview_sessions = MagicMock()
        self.preview_sessions.get_active_for_change.return_value = None

        self.provider_health = MagicMock()
        self.provider_health.get_by_provider.return_value = None
        self.provider_health.list_all.return_value = []

        self.reviews = MagicMock()
        self.reviews.get_by_job_id.return_value = None

        self.audits = MagicMock()
        self.audits.get_by_job_id.return_value = None

        self.check_results = MagicMock()
        self.check_results.list_by_job.return_value = []

        self.operator_actions = MagicMock()
        self.operator_actions.get_by_request_id.return_value = None

    def _save_run(self, run: OrchestrationRun):
        self._runs[run.run_id] = run

    def _save_job(self, job: Job):
        self._jobs[job.job_id] = job

    def _list_runs(self, project_id=None, change_name=None, is_active=None):
        results = list(self._runs.values())
        if project_id:
            results = [r for r in results if r.project_id == project_id]
        if change_name:
            results = [r for r in results if r.change_name == change_name]
        if is_active is not None:
            results = [r for r in results if r.is_active == is_active]
        return results

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def mock_github_adapter():
    adapter = MagicMock(spec=GitHubAdapterInterface)
    adapter.get_pull_request_details.return_value = {
        "number": 54,
        "url": "https://github.com/silverberdi/mini-me/pull/54",
        "state": "closed",
        "is_merged": True,
        "merged_at": "2026-09-03T10:00:00Z",
        "merged_by": {"login": "silverberdi", "type": "User"},
        "merged_by_login": "silverberdi",
        "merge_commit_sha": "abcdef1234567890abcdef1234567890abcdef12",
        "head_sha": "695855fc6b6caf022be3f6b32c973c18c51c6afd",
        "head_branch": "minime/018.2-proving-diagnostic-status",
        "base_sha": "1234567890abcdef1234567890abcdef12345678",
        "base_branch": "main",
        "title": "018.2-proving-diagnostic-status",
    }
    adapter.close_issue.return_value = True
    adapter.update_project_item_status.return_value = True
    adapter.delete_remote_branch.return_value = True
    return adapter


def test_openspec_sync_and_archive(tmp_path: Path):
    project_root = tmp_path
    openspec_dir = project_root / "openspec"
    change_dir = openspec_dir / "changes" / "test-change"
    specs_dir = change_dir / "specs" / "test-cap"
    specs_dir.mkdir(parents=True)

    delta_content = """# Spec: Test Capability

## Requirement: Autonomous Action
The system SHALL execute autonomous actions.

### Scenarios

#### Scenario: Normal Execution
- GIVEN a ready task
- WHEN executed
- THEN state becomes DONE
"""
    (specs_dir / "spec.md").write_text(delta_content)
    (change_dir / "tasks.md").write_text("- [x] 1.1 Complete task\n")

    sync_service = OpenSpecSyncService(project_root)
    synced = sync_service.sync_change_specs("openspec", "test-change")
    assert "test-cap" in synced

    main_spec = openspec_dir / "specs" / "test-cap" / "spec.md"
    assert main_spec.exists()
    assert "## Requirement: Autonomous Action" in main_spec.read_text()

    # Archive
    archived_dir = sync_service.archive_change("openspec", "test-change", target_date="2026-09-03")
    assert archived_dir.exists()
    assert "2026-09-03-test-change" in str(archived_dir)
    assert not change_dir.exists()


def test_post_merge_reconciliation_full_cycle(tmp_path: Path, mock_github_adapter):
    uow = InMemoryUnitOfWork()

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        status=ProjectStatus.ACTIVE,
    )
    uow.projects.save(project)

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=53,
        github_pr_number=54,
        openspec_change_name="test-change",
        is_valid=True,
    )
    uow.bindings.save(binding)

    run = OrchestrationRun(
        run_id="run-123",
        project_id="mini-me",
        change_name="test-change",
        base_sha="base123",
        current_stage=OrchestrationStage.PR_PREPARED,
        stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
        active_job_id="job-123",
        current_candidate_sha="cand123",
        is_active=True,
    )
    uow.orchestration_runs.save(run)

    job = Job(
        job_id="job-123",
        project_id="mini-me",
        change_name="test-change",
        status=JobStatus.READY_TO_MERGE,
        implementer_role="codex",
    )
    uow.jobs.save(job)

    # Setup dummy change directory
    change_dir = tmp_path / "openspec" / "changes" / "test-change" / "specs" / "cap1"
    change_dir.mkdir(parents=True)
    (change_dir / "spec.md").write_text("# Spec: Cap1\n## Requirement: R1\n")
    (tmp_path / "openspec" / "changes" / "test-change" / "tasks.md").write_text("- [x] Done\n")

    service = PostMergeReconciliationService(
        uow=uow,
        project_root=tmp_path,
        github_adapter=mock_github_adapter,
    )
    # Mock ancestry check
    service.verify_candidate_ancestry = MagicMock(return_value=True)

    result = service.reconcile_post_merge("mini-me", "test-change", run_id="run-123")

    assert result.success is True
    assert result.already_closed is False
    assert result.is_merged is True
    assert result.merged_by == "silverberdi"
    assert result.ancestry_verified is True
    assert result.issue_closed is True
    assert result.project_item_updated is True
    assert result.openspec_synced is True
    assert result.openspec_archived is True
    assert result.terminal_stage == OrchestrationStage.COMPLETED
    assert result.terminal_job_status == JobStatus.COMPLETED
    assert result.native_phases_completed == 12

    # Verify run and job persisted state
    updated_run = uow.orchestration_runs.get_by_id("run-123")
    assert updated_run.current_stage == OrchestrationStage.COMPLETED
    assert updated_run.stop_outcome == OrchestrationStopOutcome.COMPLETED
    assert updated_run.is_active is False

    updated_job = uow.jobs.get_by_id("job-123")
    assert updated_job.status == JobStatus.COMPLETED

    # Verify events
    event_types = [e.event_type for e in uow._events]
    assert EventType.MERGE_DETECTED in event_types
    assert EventType.ISSUE_CLOSED in event_types
    assert EventType.PROJECT_ITEM_DONE in event_types
    assert EventType.OPEN_SPEC_SYNCED in event_types
    assert EventType.OPEN_SPEC_ARCHIVED in event_types
    assert EventType.POST_MERGE_COMPLETED in event_types

    # Test Idempotency (Rerunning on already-completed run)
    rerun_result = service.reconcile_post_merge("mini-me", "test-change", run_id="run-123")
    assert rerun_result.success is True
    assert rerun_result.already_closed is True
    assert rerun_result.native_phases_completed == 12


def test_control_plane_reconcile_post_merge(tmp_path: Path, mock_github_adapter):
    from minime.domain.enums import OperatorActionStatus, OperatorActionType
    from minime.domain.models import OperatorActionRequest
    from minime.services.control_plane_service import ControlPlaneService

    uow = InMemoryUnitOfWork()
    uow.operator_actions = MagicMock()
    uow.operator_actions.get_by_request_id.return_value = None

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        status=ProjectStatus.ACTIVE,
    )
    uow.projects.save(project)

    binding = ProjectBinding(
        project_id="mini-me",
        repository="silverberdi/mini-me",
        github_issue_number=53,
        github_pr_number=54,
        openspec_change_name="test-change",
        is_valid=True,
    )
    uow.bindings.save(binding)

    run = OrchestrationRun(
        run_id="run-cp-1",
        project_id="mini-me",
        change_name="test-change",
        base_sha="base123",
        current_stage=OrchestrationStage.PR_PREPARED,
        stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
        active_job_id="job-cp-1",
        current_candidate_sha="cand123",
        is_active=True,
    )
    uow.orchestration_runs.save(run)

    job = Job(
        job_id="job-cp-1",
        project_id="mini-me",
        change_name="test-change",
        status=JobStatus.READY_TO_MERGE,
        implementer_role="codex",
    )
    uow.jobs.save(job)

    # Setup dummy change directory
    change_dir = tmp_path / "openspec" / "changes" / "test-change" / "specs" / "cap1"
    change_dir.mkdir(parents=True)
    (change_dir / "spec.md").write_text("# Spec: Cap1\n## Requirement: R1\n")
    (tmp_path / "openspec" / "changes" / "test-change" / "tasks.md").write_text("- [x] Done\n")

    post_merge_service = PostMergeReconciliationService(
        uow=uow,
        project_root=tmp_path,
        github_adapter=mock_github_adapter,
    )
    post_merge_service.verify_candidate_ancestry = MagicMock(return_value=True)

    cp_service = ControlPlaneService(
        uow=uow,
        project_root=tmp_path,
        post_merge_service=post_merge_service,
    )

    # Check descriptors
    descriptors = cp_service.get_available_actions("run-cp-1")
    reconcile_desc = next(
        (d for d in descriptors if d.action == OperatorActionType.RECONCILE_POST_MERGE), None
    )
    assert reconcile_desc is not None
    assert reconcile_desc.enabled is True

    # Execute action
    req = OperatorActionRequest(
        action_request_id="req-1",
        project_id="mini-me",
        change_name="test-change",
        run_id="run-cp-1",
        action_type=OperatorActionType.RECONCILE_POST_MERGE,
    )
    res = cp_service.execute_action(req)
    assert res.status == OperatorActionStatus.COMPLETED
    assert res.resulting_stage == OrchestrationStage.COMPLETED
    assert res.resulting_outcome == OrchestrationStopOutcome.COMPLETED
