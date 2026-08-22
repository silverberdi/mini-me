"""Integration tests for continuation governance in ExecutionPipelineService."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from minime.domain.enums import (
    EvidenceDiagnosticStatus,
    ExecutionOutcome,
    JobStatus,
    ProviderHealthStatus,
    ReadinessState,
)
from minime.domain.models import (
    Change,
    EvidenceDiagnostic,
    Job,
    Project,
)
from minime.services.candidate_manifest import CandidateManifestService
from minime.services.checks_runner import ChecksRunResult
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.implementer_runner import ImplementerResult
from minime.services.openspec_tasks import OpenSpecTask
from minime.services.outcome_governance import (
    CompletionVerificationResult,
)
from minime.services.restart_recovery_service import RestartRecoveryService
from minime.services.reviewer_runner import ReviewerResult


class InMemoryRepo:
    def __init__(self):
        self._items = {}

    def get_by_id(self, item_id: str):
        return self._items.get(item_id)

    def save(self, item):
        item_id = (
            getattr(item, "job_id", None)
            or getattr(item, "attempt_id", None)
            or getattr(item, "handoff_id", None)
            or getattr(item, "manifest_id", None)
            or getattr(item, "diagnostic_id", None)
            or getattr(item, "project_id", None)
            or getattr(item, "authorship_id", None)
            or getattr(item, "review_id", None)
            or getattr(item, "audit_id", None)
        )
        if item_id:
            self._items[item_id] = item

    def list_all(self):
        return list(self._items.values())


class MockUnitOfWork:
    def __init__(self):
        self.jobs = MagicMock()
        self._jobs_dict = {}
        self.jobs.get_by_id = lambda jid: self._jobs_dict.get(jid)
        self.jobs.save = lambda j: self._jobs_dict.update({j.job_id: j})
        self.jobs.set_waiting_capacity = lambda jid, p, r=None, reset=None: self._set_waiting(
            jid, p, r
        )
        self.jobs.transition = lambda jid, status, error_message=None, **kwargs: (
            self._transition_job(jid, status, error_message)
        )

        self.projects = MagicMock()
        self._projects_dict = {}
        self.projects.get_by_id = lambda pid: self._projects_dict.get(pid)

        self.changes = MagicMock()
        self._changes_dict = {}
        self.changes.get_by_name = lambda pid, cname: self._changes_dict.get(f"{pid}:{cname}")

        self.events = MagicMock()
        self.events.save = MagicMock()

        self.metrics = MagicMock()
        self.metrics.save = MagicMock()

        self.job_logs = MagicMock()
        self.job_logs.save = MagicMock()

        self.reviews = MagicMock()
        self._reviews_dict = {}
        self.reviews.get_by_id = lambda rid: self._reviews_dict.get(rid)
        self.reviews.save = lambda r: self._reviews_dict.update({r.review_id: r})
        self.reviews.transition = MagicMock()

        self.review_findings = MagicMock()
        self.review_findings.list_by_review = lambda rid: []
        self.review_findings.save = MagicMock()

        self.audits = MagicMock()
        self._audits_dict = {}
        self.audits.get_by_id = lambda aid: self._audits_dict.get(aid)
        self.audits.save = lambda a: self._audits_dict.update({a.audit_id: a})
        self.audits.transition = MagicMock()

        self.audit_findings = MagicMock()
        self.audit_findings.save = MagicMock()

        self.check_results = MagicMock()
        self.check_results.save = MagicMock()

        self.job_attempts = MagicMock()
        self._attempts = {}
        self.job_attempts.save = lambda a: self._attempts.update({a.attempt_id: a})
        self.job_attempts.list_by_job = lambda jid: [
            a for a in self._attempts.values() if a.job_id == jid
        ]

        self.blocker_claims = MagicMock()
        self._blocker_claims = {}
        self.blocker_claims.save = lambda b: self._blocker_claims.update({b.claim_id: b})
        self.blocker_claims.list_by_job = lambda jid: [
            b for b in self._blocker_claims.values() if b.job_id == jid
        ]

        self.job_handoffs = MagicMock()
        self._handoffs = {}
        self.job_handoffs.save = lambda h: self._handoffs.update({h.handoff_id: h})
        self.job_handoffs.get_by_id = lambda hid: self._handoffs.get(hid)
        self.job_handoffs.get_latest_handoff = lambda jid: next(
            (
                h
                for h in sorted(self._handoffs.values(), key=lambda x: x.created_at, reverse=True)
                if h.job_id == jid
            ),
            None,
        )

        self.candidate_manifests = MagicMock()
        self._manifests = {}
        self.candidate_manifests.save = lambda m: self._manifests.update({m.manifest_id: m})
        self.candidate_manifests.get_latest_manifest = lambda jid: next(
            (
                m
                for m in sorted(self._manifests.values(), key=lambda x: x.created_at, reverse=True)
                if m.job_id == jid
            ),
            None,
        )

        self.candidate_authorships = MagicMock()
        self._authorships = {}
        self.candidate_authorships.save = lambda ca: self._authorships.update(
            {ca.authorship_id: ca}
        )
        self.candidate_authorships.list_by_job = lambda jid: [
            ca for ca in self._authorships.values() if ca.job_id == jid
        ]

        self.evidence_diagnostics = MagicMock()
        self._diagnostics = {}
        self.evidence_diagnostics.save = lambda ed: self._diagnostics.update({ed.diagnostic_id: ed})
        self.evidence_diagnostics.list_by_job = lambda jid: [
            ed for ed in self._diagnostics.values() if ed.job_id == jid
        ]

        self.pricing_snapshots = MagicMock()
        self.pricing_snapshots.get_latest_verified_for_model = lambda m, c: None

    def _set_waiting(self, jid, p, r=None):
        job = self._jobs_dict.get(jid)
        if job:
            job.status = JobStatus.WAITING_CAPACITY
            job.error_message = r
        return job

    def _transition_job(self, jid, status, error=None):
        job = self._jobs_dict.get(jid)
        if job:
            job.status = status if isinstance(status, JobStatus) else JobStatus(status)
            if error:
                job.error_message = error
        return job

    def commit(self):
        pass


@pytest.mark.asyncio
async def test_continuation_pipeline_multi_attempt_success(tmp_path: Path):
    """Test that a premature stop triggers corrective retry and passes on attempt 2."""
    uow = MockUnitOfWork()
    project = Project(
        project_id="proj-1",
        name="test-project",
        display_name="Test Project",
        repository="silverberdi/test-project",
        repo_path=str(tmp_path),
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
    )
    uow._projects_dict[project.project_id] = project

    change = Change(
        project_id=project.project_id,
        name="007-continuation",
        last_readiness_status=ReadinessState.READY,
    )
    uow._changes_dict[f"{project.project_id}:{change.name}"] = change

    # Mock WorktreeManager
    mock_worktree_mgr = MagicMock()
    mock_worktree = MagicMock()
    mock_worktree.path = tmp_path / "worktree"
    mock_worktree.path.mkdir(parents=True, exist_ok=True)
    mock_worktree.base_sha = "base123"
    mock_worktree_mgr.create_worktree = AsyncMock(return_value=mock_worktree)
    mock_worktree_mgr.current_sha = AsyncMock(
        side_effect=[
            "sha-attempt-1",
            "sha-attempt-1",
            "sha-attempt-2",
            "sha-attempt-2",
            "sha-attempt-2",
        ]
    )
    mock_worktree_mgr.cleanup_worktree = AsyncMock()

    # Mock task tracker
    mock_task_tracker = MagicMock()
    mock_task_tracker.format_prompt_context = MagicMock(return_value="Prompt context")
    mock_task_tracker.parse_tasks = MagicMock(
        return_value=[
            OpenSpecTask(task_id="1.1", text="task 1", section=None, complete=True),
            OpenSpecTask(task_id="1.2", text="task 2", section=None, complete=True),
        ]
    )

    # Mock OutcomeGovernanceService
    mock_outcome_gov = MagicMock()
    # Attempt 1: Incomplete tasks -> PREMATURE_STOP
    # Attempt 2: All complete -> COMPLETED
    mock_outcome_gov.verify_completion = MagicMock(
        side_effect=[
            CompletionVerificationResult(
                is_complete=False,
                incomplete_tasks=[
                    OpenSpecTask(task_id="1.2", text="task 2", section=None, complete=False)
                ],
                modified_files=["file1.py"],
                reason="Task 1.2 incomplete",
            ),
            CompletionVerificationResult(
                is_complete=True,
                incomplete_tasks=[],
                modified_files=["file1.py", "file2.py"],
            ),
        ]
    )
    mock_outcome_gov.classify_outcome = MagicMock(
        side_effect=[ExecutionOutcome.PREMATURE_STOP, ExecutionOutcome.COMPLETED]
    )
    mock_outcome_gov.evaluate_progress = MagicMock(return_value="MADE_PROGRESS")

    # Mock checks runner
    mock_checks_runner = MagicMock()
    mock_check_res = MagicMock()
    mock_check_res.passed = True
    mock_check_run = ChecksRunResult(passed=True, results=[], diagnostics=[])
    mock_checks_runner.run = AsyncMock(return_value=mock_check_run)

    # Mock implementer runner
    mock_imp_runner = MagicMock()
    mock_imp_runner.run = AsyncMock(
        return_value=ImplementerResult(
            stdout=["Completed part 1"], stderr=[], exit_code=0, duration_ms=100, timed_out=False
        )
    )

    # Mock reviewer runner
    mock_rev_runner = MagicMock()
    mock_rev_runner.run = AsyncMock(
        return_value=ReviewerResult(
            stdout=['{"verdict": "READY_TO_MERGE", "summary": "Looks great"}'],
            stderr=[],
            exit_code=0,
            duration_ms=100,
            timed_out=False,
        )
    )

    # Mock reviewer view
    mock_rev_view_mgr = MagicMock()
    mock_rev_view_mgr.create_readonly_view = MagicMock(return_value=tmp_path / "view")
    mock_rev_view_mgr.cleanup_readonly_view = MagicMock()

    pipeline = ExecutionPipelineService(
        uow=uow,
        project_root=tmp_path,
        implementer_runner=mock_imp_runner,
        reviewer_runner=mock_rev_runner,
        worktree_manager=mock_worktree_mgr,
        reviewer_view_manager=mock_rev_view_mgr,
        checks_runner=mock_checks_runner,
        task_tracker=mock_task_tracker,
        outcome_governance=mock_outcome_gov,
    )

    # Mock provider health
    pipeline.health_service.get_health = MagicMock(
        return_value=MagicMock(status=ProviderHealthStatus.AVAILABLE)
    )
    pipeline.health_service.record_outcome = MagicMock()

    from unittest.mock import patch

    with (
        patch(
            "minime.services.execution_pipeline.validate_pre_review_integrity",
            return_value=(True, None),
        ),
        patch(
            "minime.services.execution_pipeline.validate_post_review_integrity",
            return_value=(True, None),
        ),
    ):
        job = pipeline.queue_job("proj-1", "007-continuation")
        res_job = await pipeline.execute_queued_job(job.job_id)

    # Verify that job completed with attempt_count == 2
    assert res_job.attempt_count == 2
    assert len(uow._attempts) == 2
    assert res_job.latest_outcome == ExecutionOutcome.COMPLETED


@pytest.mark.asyncio
async def test_reviewer_visibility_blindness_escalation(tmp_path: Path):
    """Test that when reviewer snapshot is missing candidate files, it triggers REVIEW_ENVIRONMENT_INVALID and NEEDS_HUMAN."""
    uow = MockUnitOfWork()
    project = Project(
        project_id="proj-1",
        name="test-project",
        display_name="Test Project",
        repository="silverberdi/test-project",
        repo_path=str(tmp_path),
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
    )
    uow._projects_dict[project.project_id] = project

    change = Change(
        project_id=project.project_id,
        name="007-continuation",
        last_readiness_status=ReadinessState.READY,
    )
    uow._changes_dict[f"{project.project_id}:{change.name}"] = change

    mock_worktree_mgr = MagicMock()
    mock_worktree = MagicMock()
    mock_worktree.path = tmp_path / "worktree"
    mock_worktree.path.mkdir(parents=True, exist_ok=True)
    mock_worktree.base_sha = "base123"
    mock_worktree_mgr.create_worktree = AsyncMock(return_value=mock_worktree)
    mock_worktree_mgr.current_sha = AsyncMock(return_value="sha123")
    mock_worktree_mgr.cleanup_worktree = AsyncMock()

    mock_task_tracker = MagicMock()
    mock_task_tracker.format_prompt_context = MagicMock(return_value="Prompt context")
    mock_task_tracker.parse_tasks = MagicMock(return_value=[])

    mock_outcome_gov = MagicMock()
    mock_outcome_gov.verify_completion = MagicMock(
        return_value=CompletionVerificationResult(
            is_complete=True, incomplete_tasks=[], modified_files=[]
        )
    )
    mock_outcome_gov.classify_outcome = MagicMock(return_value=ExecutionOutcome.COMPLETED)
    mock_outcome_gov.evaluate_progress = MagicMock(return_value="FULL_COMPLETION")

    mock_checks_runner = MagicMock()
    mock_checks_runner.run = AsyncMock(
        return_value=ChecksRunResult(passed=True, results=[], diagnostics=[])
    )

    mock_imp_runner = MagicMock()
    mock_imp_runner.run = AsyncMock(
        return_value=ImplementerResult(
            stdout=["Done"], stderr=[], exit_code=0, duration_ms=50, timed_out=False
        )
    )

    mock_rev_view_mgr = MagicMock()
    mock_rev_view_mgr.create_readonly_view = MagicMock(return_value=tmp_path / "view")
    mock_rev_view_mgr.cleanup_readonly_view = MagicMock()

    # Manifest service that reports snapshot missing file
    manifest_service = CandidateManifestService()
    # Mock verify_reviewer_visibility to return False
    manifest_service.verify_reviewer_visibility = MagicMock(
        return_value=(
            False,
            EvidenceDiagnostic(
                job_id="job-1",
                stage_type="REVIEW",
                check_name="reviewer_snapshot_visibility",
                diagnostic_status=EvidenceDiagnosticStatus.REVIEW_ENVIRONMENT_INVALID,
                environment_identity=str(tmp_path / "view"),
                candidate_sha="sha123",
                reason="Reviewer workspace snapshot missing candidate files: file_missing.py",
            ),
        )
    )

    pipeline = ExecutionPipelineService(
        uow=uow,
        project_root=tmp_path,
        implementer_runner=mock_imp_runner,
        worktree_manager=mock_worktree_mgr,
        reviewer_view_manager=mock_rev_view_mgr,
        checks_runner=mock_checks_runner,
        task_tracker=mock_task_tracker,
        outcome_governance=mock_outcome_gov,
        manifest_service=manifest_service,
    )
    pipeline.health_service.get_health = MagicMock(
        return_value=MagicMock(status=ProviderHealthStatus.AVAILABLE)
    )
    pipeline.health_service.record_outcome = MagicMock()

    from unittest.mock import patch

    with patch(
        "minime.services.execution_pipeline.validate_pre_review_integrity",
        return_value=(True, None),
    ):
        job = pipeline.queue_job("proj-1", "007-continuation")
        res_job = await pipeline.execute_queued_job(job.job_id)

    assert res_job.status == JobStatus.NEEDS_HUMAN
    assert "Reviewer workspace snapshot missing candidate files" in (res_job.error_message or "")
    assert len(uow._diagnostics) > 0


def test_restart_recovery_preserves_needs_human_and_counters():
    """Test that restart reconciliation preserves NEEDS_HUMAN jobs and their attempt counters."""
    uow = MockUnitOfWork()
    job = Job(
        job_id="job-human-1",
        project_id="proj-1",
        change_name="007-continuation",
        implementer_role="codex",
        status=JobStatus.NEEDS_HUMAN,
        attempt_count=2,
        reassignment_count=1,
        is_mixed_authorship=True,
        latest_outcome=ExecutionOutcome.FALSE_BLOCKER,
        escalation_reason="Repeated false blocker streak exceeded",
    )
    uow._jobs_dict[job.job_id] = job

    recovery_service = RestartRecoveryService(
        uow=uow,
        project_root=Path("/tmp"),
    )

    reconciled = recovery_service._reconcile_job(job, "recov-cycle-1")

    assert reconciled.status == JobStatus.NEEDS_HUMAN
    assert reconciled.attempt_count == 2
    assert reconciled.reassignment_count == 1
    assert reconciled.is_mixed_authorship is True
    assert reconciled.escalation_reason == "Repeated false blocker streak exceeded"


@pytest.mark.asyncio
async def test_reassignment_creates_handoff_and_tracks_mixed_authorship(tmp_path: Path):
    """Test that exhausted corrective retries triggers REASSIGN_AGENT, persists handoff, and records mixed authorship."""
    uow = MockUnitOfWork()
    project = Project(
        project_id="proj-1",
        name="test-project",
        display_name="Test Project",
        repository="silverberdi/test-project",
        repo_path=str(tmp_path),
        base_branch="main",
        implementer="codex",
        reviewer="antigravity",
    )
    uow._projects_dict[project.project_id] = project

    change = Change(
        project_id=project.project_id,
        name="007-continuation",
        last_readiness_status=ReadinessState.READY,
    )
    uow._changes_dict[f"{project.project_id}:{change.name}"] = change

    mock_worktree_mgr = MagicMock()
    mock_worktree = MagicMock()
    mock_worktree.path = tmp_path / "worktree"
    mock_worktree.path.mkdir(parents=True, exist_ok=True)
    mock_worktree.base_sha = "base123"
    mock_worktree_mgr.create_worktree = AsyncMock(return_value=mock_worktree)
    mock_worktree_mgr.current_sha = AsyncMock(
        side_effect=["sha1", "sha1", "sha2", "sha2", "sha3", "sha3", "sha4", "sha4"]
    )
    mock_worktree_mgr.cleanup_worktree = AsyncMock()

    mock_task_tracker = MagicMock()
    mock_task_tracker.format_prompt_context = MagicMock(return_value="Prompt context")
    mock_task_tracker.parse_tasks = MagicMock(
        return_value=[
            OpenSpecTask(task_id="1.1", text="task 1", section=None, complete=True),
            OpenSpecTask(task_id="1.2", text="task 2", section=None, complete=True),
        ]
    )

    # Attempt 1: NO_PROGRESS (codex) -> retry 1
    # Attempt 2: NO_PROGRESS (codex) -> retry 2
    # Attempt 3: NO_PROGRESS (codex) -> reassign to antigravity
    # Attempt 4: COMPLETED (antigravity)
    mock_outcome_gov = MagicMock()
    mock_outcome_gov.verify_completion = MagicMock(
        side_effect=[
            CompletionVerificationResult(
                is_complete=False,
                incomplete_tasks=[
                    OpenSpecTask(task_id="1.2", text="task 2", section=None, complete=False)
                ],
                modified_files=["a.py"],
            ),
            CompletionVerificationResult(
                is_complete=False,
                incomplete_tasks=[
                    OpenSpecTask(task_id="1.2", text="task 2", section=None, complete=False)
                ],
                modified_files=["a.py"],
            ),
            CompletionVerificationResult(
                is_complete=False,
                incomplete_tasks=[
                    OpenSpecTask(task_id="1.2", text="task 2", section=None, complete=False)
                ],
                modified_files=["a.py"],
            ),
            CompletionVerificationResult(
                is_complete=True, incomplete_tasks=[], modified_files=["a.py", "b.py"]
            ),
        ]
    )
    mock_outcome_gov.classify_outcome = MagicMock(
        side_effect=[
            ExecutionOutcome.NO_PROGRESS,
            ExecutionOutcome.NO_PROGRESS,
            ExecutionOutcome.NO_PROGRESS,
            ExecutionOutcome.COMPLETED,
        ]
    )
    mock_outcome_gov.evaluate_progress = MagicMock(
        side_effect=["NO_PROGRESS", "NO_PROGRESS", "NO_PROGRESS", "FULL_COMPLETION"]
    )

    mock_checks_runner = MagicMock()
    mock_checks_runner.run = AsyncMock(
        return_value=ChecksRunResult(passed=True, results=[], diagnostics=[])
    )

    mock_imp_runner = MagicMock()
    mock_imp_runner.run = AsyncMock(
        return_value=ImplementerResult(
            stdout=["Work done"], stderr=[], exit_code=0, duration_ms=50, timed_out=False
        )
    )

    mock_rev_runner = MagicMock()
    mock_rev_runner.run = AsyncMock(
        return_value=ReviewerResult(
            stdout=['{"verdict": "READY_TO_MERGE", "summary": "Good"}'],
            stderr=[],
            exit_code=0,
            duration_ms=50,
            timed_out=False,
        )
    )

    mock_rev_view_mgr = MagicMock()
    mock_rev_view_mgr.create_readonly_view = MagicMock(return_value=tmp_path / "view")
    mock_rev_view_mgr.cleanup_readonly_view = MagicMock()

    pipeline = ExecutionPipelineService(
        uow=uow,
        project_root=tmp_path,
        implementer_runner=mock_imp_runner,
        reviewer_runner=mock_rev_runner,
        worktree_manager=mock_worktree_mgr,
        reviewer_view_manager=mock_rev_view_mgr,
        checks_runner=mock_checks_runner,
        task_tracker=mock_task_tracker,
        outcome_governance=mock_outcome_gov,
    )
    pipeline.health_service.get_health = MagicMock(
        return_value=MagicMock(status=ProviderHealthStatus.AVAILABLE)
    )
    pipeline.health_service.record_outcome = MagicMock()
    pipeline._run_audit_stage = AsyncMock(
        side_effect=lambda job, project, worktree_path, check_run_results, review_id: job
    )

    from unittest.mock import patch

    with (
        patch(
            "minime.services.execution_pipeline.validate_pre_review_integrity",
            return_value=(True, None),
        ),
        patch(
            "minime.services.execution_pipeline.validate_post_review_integrity",
            return_value=(True, None),
        ),
    ):
        job = pipeline.queue_job("proj-1", "007-continuation")
        res_job = await pipeline.execute_queued_job(job.job_id)

    assert res_job.reassignment_count == 1
    assert res_job.attempt_count == 4
    assert res_job.is_mixed_authorship is True
    assert len(uow._handoffs) >= 1
    assert res_job.latest_outcome == ExecutionOutcome.COMPLETED
