"""Tests for OperationsDashboardService read model and queries."""

from __future__ import annotations

from minime.domain.enums import (
    AuditRiskLevel,
    AuditStatus,
    ChangeStatus,
    HumanGate,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProjectStatus,
    ReadinessState,
    ReviewVerdict,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    AuditRecord,
    Change,
    CheckResult,
    Job,
    OrchestrationRun,
    Project,
    ProjectBinding,
    Review,
)
from minime.services.dashboard_service import OperationsDashboardService


def test_dashboard_overview_empty_state(in_memory_uow: PersistenceUnitOfWork) -> None:
    service = OperationsDashboardService(in_memory_uow)

    overview = service.get_overview()
    assert overview.system_status.healthy is True
    assert overview.system_status.active_runs_count == 0
    assert overview.system_status.total_changes_count == 0
    assert overview.system_status.attention_runs_count == 0
    assert overview.attention_items == []
    assert overview.active_executions == []
    assert overview.changes == []


def test_dashboard_overview_with_runs_and_attention(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    service = OperationsDashboardService(in_memory_uow)

    # 1. Project
    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="owner/test-proj",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
        status=ProjectStatus.ACTIVE,
    )
    in_memory_uow.projects.save(project)

    # 2. Changes
    c1 = Change(
        project_id="test-proj",
        name="001-active-feature",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    c2 = Change(
        project_id="test-proj",
        name="002-blocked-feature",
        status=ChangeStatus.BLOCKED,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(c1)
    in_memory_uow.changes.save(c2)

    # 3. Active run for c1
    r1 = OrchestrationRun(
        run_id="run-active-1",
        project_id="test-proj",
        change_name="001-active-feature",
        current_stage=OrchestrationStage.IMPLEMENTING,
        is_active=True,
        current_generation=1,
        current_candidate_sha="abc111222333444555",
        base_sha="base000111",
    )
    in_memory_uow.orchestration_runs.save(r1)

    # 4. Attention run for c2 (NEEDS_HUMAN)
    r2 = OrchestrationRun(
        run_id="run-blocked-2",
        project_id="test-proj",
        change_name="002-blocked-feature",
        current_stage=OrchestrationStage.RUNNING_CHECKS,
        is_active=False,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_reason="Deterministic checks failed on test_safety",
        current_generation=1,
        current_candidate_sha="def999888777666555",
        base_sha="base000111",
    )
    in_memory_uow.orchestration_runs.save(r2)

    overview = service.get_overview()

    assert overview.system_status.active_runs_count == 1
    assert overview.system_status.attention_runs_count == 1
    assert len(overview.changes) == 2

    # Check active execution
    assert len(overview.active_executions) == 1
    assert overview.active_executions[0].run_id == "run-active-1"
    assert overview.active_executions[0].stage == "IMPLEMENTING"

    # Check attention item
    assert len(overview.attention_items) == 1
    assert overview.attention_items[0].run_id == "run-blocked-2"
    assert overview.attention_items[0].human_gate == "NEEDS_HUMAN"
    assert "test_safety" in overview.attention_items[0].reason


def test_dashboard_change_detail_pipeline_phases(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    service = OperationsDashboardService(in_memory_uow)

    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="owner/test-proj",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="test-proj",
        name="003-audited-feature",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        job_id="job-1",
        project_id="test-proj",
        change_name="003-audited-feature",
        implementer_role="codex",
        status=JobStatus.READY_TO_MERGE,
        candidate_sha="cand123456",
        base_sha="base123456",
    )
    in_memory_uow.jobs.save(job)

    run = OrchestrationRun(
        run_id="run-3",
        project_id="test-proj",
        change_name="003-audited-feature",
        active_job_id="job-1",
        current_stage=OrchestrationStage.PR_PREPARED,
        is_active=False,
        stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
        current_generation=1,
        current_candidate_sha="cand123456",
        base_sha="base123456",
    )
    in_memory_uow.orchestration_runs.save(run)

    # Check result
    cr = CheckResult(
        check_id="cr-1",
        job_id="job-1",
        check_name="pytest",
        command="pytest",
        exit_code=0,
        duration_ms=120,
        output_snippet="=== 415 passed ===",
    )
    in_memory_uow.check_results.save(cr)

    # Review
    rev = Review(
        review_id="rev-1",
        job_id="job-1",
        project_id="test-proj",
        change_name="003-audited-feature",
        reviewer_role="antigravity",
        candidate_sha="cand123456",
        base_sha="base123456",
        verdict=ReviewVerdict.READY_TO_MERGE,
    )
    in_memory_uow.reviews.save(rev)

    # Audit
    aud = AuditRecord(
        audit_id="aud-1",
        job_id="job-1",
        project_id="test-proj",
        change_name="003-audited-feature",
        provider="deepseek",
        model="deepseek-chat",
        candidate_sha="cand123456",
        base_sha="base123456",
        status=AuditStatus.AUDIT_COMPLETED,
        risk=AuditRiskLevel.LOW,
    )
    in_memory_uow.audits.save(aud)

    # Binding
    binding = ProjectBinding(
        project_id="test-proj",
        repository="owner/test-proj",
        github_issue_number=15,
        github_pr_number=42,
        github_pr_url="https://github.com/owner/test-proj/pull/42",
        openspec_change_name="003-audited-feature",
    )
    in_memory_uow.bindings.save(binding)

    detail = service.get_change_detail("test-proj", "003-audited-feature")

    assert detail.status == "COMPLETED"
    assert detail.run_id == "run-3"
    assert len(detail.pipeline) == 6

    phase_map = {p.name: p.status for p in detail.pipeline}
    assert phase_map["readiness"] == "passed"
    assert phase_map["implementation"] == "passed"
    assert phase_map["checks"] == "passed"
    assert phase_map["review"] == "passed"
    assert phase_map["audit"] == "passed"
    assert phase_map["pr_merge"] == "passed"

    assert len(detail.checks) == 1
    assert detail.checks[0].check_name == "pytest"
    assert detail.checks[0].status == "PASS"

    assert detail.review.verdict == "READY_TO_MERGE"
    assert detail.review.is_stale_to_current_candidate is False

    assert detail.audit.status == "AUDIT_COMPLETED"
    assert detail.audit.risk == "low"
    assert detail.audit.is_stale_to_current_candidate is False

    assert detail.github.issue_number == 15
    assert detail.github.pr_number == 42
    assert detail.github.pr_url == "https://github.com/owner/test-proj/pull/42"


def test_dashboard_attention_includes_recovery_blocked(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    service = OperationsDashboardService(in_memory_uow)

    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="owner/test-proj",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="test-proj",
        name="004-recovery-blocked-feature",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        job_id="job-rec-1",
        project_id="test-proj",
        change_name="004-recovery-blocked-feature",
        implementer_role="codex",
        status=JobStatus.RECOVERY_BLOCKED,
        recovery_blocked_reason="Worktree contains unresolved merge conflict on auth.py",
    )
    in_memory_uow.jobs.save(job)

    run = OrchestrationRun(
        run_id="run-rec-1",
        project_id="test-proj",
        change_name="004-recovery-blocked-feature",
        active_job_id="job-rec-1",
        current_stage=OrchestrationStage.PREPARING_EXECUTION,
        is_active=False,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        stop_reason="Automatic recovery failed due to conflict",
        current_generation=1,
        current_candidate_sha="cand999",
        base_sha="base999",
    )
    in_memory_uow.orchestration_runs.save(run)

    overview = service.get_overview()
    assert overview.system_status.attention_runs_count == 1
    assert len(overview.attention_items) == 1
    item = overview.attention_items[0]
    assert item.run_id == "run-rec-1"
    assert "Automatic recovery failed" in item.reason or "unresolved merge conflict" in item.reason


def test_dashboard_failed_checks_blocks_downstream_phases(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    service = OperationsDashboardService(in_memory_uow)

    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="owner/test-proj",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="test-proj",
        name="005-failed-checks-feature",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        job_id="job-fc-1",
        project_id="test-proj",
        change_name="005-failed-checks-feature",
        implementer_role="codex",
        status=JobStatus.CHECKS_FAILED,
        candidate_sha="cand-fail-1",
        base_sha="base-fail-1",
    )
    in_memory_uow.jobs.save(job)

    run = OrchestrationRun(
        run_id="run-fc-1",
        project_id="test-proj",
        change_name="005-failed-checks-feature",
        active_job_id="job-fc-1",
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        is_active=False,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        current_generation=1,
        current_candidate_sha="cand-fail-1",
        base_sha="base-fail-1",
    )
    in_memory_uow.orchestration_runs.save(run)

    detail = service.get_change_detail("test-proj", "005-failed-checks-feature")
    phase_map = {p.name: p.status for p in detail.pipeline}

    assert phase_map["checks"] == "failed"
    assert phase_map["review"] == "blocked"
    assert phase_map["audit"] == "blocked"
    assert phase_map["pr_merge"] == "blocked"


def test_dashboard_pipeline_requires_persisted_evidence(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    service = OperationsDashboardService(in_memory_uow)

    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="owner/test-proj",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="test-proj",
        name="006-no-evidence-feature",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        job_id="job-ne-1",
        project_id="test-proj",
        change_name="006-no-evidence-feature",
        implementer_role="codex",
        status=JobStatus.RUNNING,
        candidate_sha="cand-ne-1",
        base_sha="base-ne-1",
    )
    in_memory_uow.jobs.save(job)

    # Run advanced to PR_PREPARED but no review or audit record exists in DB
    run = OrchestrationRun(
        run_id="run-ne-1",
        project_id="test-proj",
        change_name="006-no-evidence-feature",
        active_job_id="job-ne-1",
        current_stage=OrchestrationStage.PR_PREPARED,
        is_active=False,
        stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
        current_generation=1,
        current_candidate_sha="cand-ne-1",
        base_sha="base-ne-1",
    )
    in_memory_uow.orchestration_runs.save(run)

    detail = service.get_change_detail("test-proj", "006-no-evidence-feature")
    phase_map = {p.name: p.status for p in detail.pipeline}

    # Review, audit, and PR/Merge must NOT report passed without evidence records
    assert phase_map["review"] == "not_started"
    assert phase_map["audit"] == "not_started"
    assert phase_map["pr_merge"] == "not_started"


def test_dashboard_pr_prepared_with_changes_required_blocks_pr_merge(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    from minime.domain.models import Review

    service = OperationsDashboardService(in_memory_uow)

    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="test-proj",
        name="007-rejected-feature",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        job_id="job-rej-1",
        project_id="test-proj",
        change_name="007-rejected-feature",
        implementer_role="codex",
        status=JobStatus.RUNNING,
        candidate_sha="cand-rej-1",
        base_sha="base-rej-1",
    )
    in_memory_uow.jobs.save(job)

    # Review with CHANGES_REQUIRED
    rev = Review(
        review_id="rev-rej-1",
        job_id="job-rej-1",
        project_id="test-proj",
        change_name="007-rejected-feature",
        reviewer_role="antigravity",
        candidate_sha="cand-rej-1",
        base_sha="base-rej-1",
        verdict=ReviewVerdict.CHANGES_REQUIRED,
    )
    in_memory_uow.reviews.save(rev)

    run = OrchestrationRun(
        run_id="run-rej-1",
        project_id="test-proj",
        change_name="007-rejected-feature",
        active_job_id="job-rej-1",
        current_stage=OrchestrationStage.PR_PREPARED,
        is_active=False,
        current_generation=1,
        current_candidate_sha="cand-rej-1",
        base_sha="base-rej-1",
    )
    in_memory_uow.orchestration_runs.save(run)

    detail = service.get_change_detail("test-proj", "007-rejected-feature")
    phase_map = {p.name: p.status for p in detail.pipeline}

    assert phase_map["review"] == "failed"
    assert phase_map["audit"] == "blocked"
    assert phase_map["pr_merge"] == "blocked"


def test_dashboard_implementation_phase_requires_candidate_sha(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    service = OperationsDashboardService(in_memory_uow)

    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="test-proj",
        name="008-no-sha-feature",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        job_id="job-ns-1",
        project_id="test-proj",
        change_name="008-no-sha-feature",
        implementer_role="codex",
        status=JobStatus.RUNNING,
    )
    in_memory_uow.jobs.save(job)

    # Run advanced to RUNNING_CHECKS but current_candidate_sha is None
    run = OrchestrationRun(
        run_id="run-ns-1",
        project_id="test-proj",
        change_name="008-no-sha-feature",
        active_job_id="job-ns-1",
        current_stage=OrchestrationStage.RUNNING_CHECKS,
        is_active=True,
        current_generation=1,
        current_candidate_sha=None,
        base_sha="base-ns-1",
    )
    in_memory_uow.orchestration_runs.save(run)

    detail = service.get_change_detail("test-proj", "008-no-sha-feature")
    phase_map = {p.name: p.status for p in detail.pipeline}

    assert phase_map["implementation"] == "running"
    assert "progress" in detail.pipeline[1].summary.lower()


def test_dashboard_terminally_completed_change_has_no_attention_or_blockers(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    service = OperationsDashboardService(in_memory_uow)

    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    # Change is terminally DONE (archived/completed)
    change = Change(
        project_id="test-proj",
        name="016-completed-feature",
        status=ChangeStatus.DONE,
        last_readiness_status=ReadinessState.NOT_READY,
    )
    in_memory_uow.changes.save(change)

    # Run was completed via post-merge, but had leftover human_gate value
    run = OrchestrationRun(
        run_id="run-c-1",
        project_id="test-proj",
        change_name="016-completed-feature",
        current_stage=OrchestrationStage.COMPLETED,
        stop_outcome=OrchestrationStopOutcome.COMPLETED,
        human_gate=HumanGate.READY_FOR_HUMAN_MERGE,
        stop_reason="Autonomous post-merge closure completed successfully.",
        is_active=False,
        current_generation=1,
        current_candidate_sha="cand12345678",
        base_sha="base12345678",
    )
    in_memory_uow.orchestration_runs.save(run)

    overview = service.get_overview()

    # Must produce 0 attention items
    assert overview.attention_items == []
    assert overview.system_status.attention_runs_count == 0

    # Change summary must show COMPLETED with NO gate
    summary = next(c for c in overview.changes if c.change_name == "016-completed-feature")
    assert summary.status == "COMPLETED"
    assert summary.current_stage == "COMPLETED"
    assert summary.stop_outcome == "COMPLETED"
    assert summary.human_gate is None

    # Detail must show COMPLETED and 0 blockers
    detail = service.get_change_detail("test-proj", "016-completed-feature")
    assert detail.status == "COMPLETED"
    assert detail.current_stage == "COMPLETED"
    assert detail.stop_outcome == "COMPLETED"
    assert detail.human_gate is None
    assert detail.blocker_details == []

    # All pipeline phases must show passed
    phase_map = {p.name: p.status for p in detail.pipeline}
    for phase_name in ["readiness", "implementation", "checks", "review", "audit", "pr_merge"]:
        assert phase_map[phase_name] == "passed"


def test_dashboard_multiple_runs_selects_completed_run_over_failed_intermediate_run(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    service = OperationsDashboardService(in_memory_uow)

    project = Project(
        project_id="test-proj",
        display_name="Test Project",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="test-proj",
        name="018.2-proving-diagnostic-status",
        status=ChangeStatus.DONE,
        last_readiness_status=ReadinessState.NOT_READY,
    )
    in_memory_uow.changes.save(change)

    # Older failed run that hit NEEDS_HUMAN
    r_failed = OrchestrationRun(
        run_id="run-failed-attempt",
        project_id="test-proj",
        change_name="018.2-proving-diagnostic-status",
        current_stage=OrchestrationStage.EVALUATING_ATTEMPT,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_reason="Provider failure occurred; reassigning to alternative executor.",
        is_active=False,
        current_generation=1,
        current_candidate_sha="failed12345",
        base_sha="base12345",
    )
    in_memory_uow.orchestration_runs.save(r_failed)

    # Later successful run that completed post-merge
    r_completed = OrchestrationRun(
        run_id="run-completed-success",
        project_id="test-proj",
        change_name="018.2-proving-diagnostic-status",
        current_stage=OrchestrationStage.COMPLETED,
        stop_outcome=OrchestrationStopOutcome.COMPLETED,
        human_gate=None,
        stop_reason="Autonomous post-merge closure completed successfully.",
        is_active=False,
        current_generation=2,
        current_candidate_sha="success12345",
        base_sha="base12345",
    )
    in_memory_uow.orchestration_runs.save(r_completed)

    overview = service.get_overview()

    # Must produce NO attention items for the completed change
    assert overview.attention_items == []

    summary = next(c for c in overview.changes if c.change_name == "018.2-proving-diagnostic-status")
    assert summary.status == "COMPLETED"
    assert summary.current_run_id == "run-completed-success"
    assert summary.current_stage == "COMPLETED"
    assert summary.stop_outcome == "COMPLETED"
    assert summary.human_gate is None

