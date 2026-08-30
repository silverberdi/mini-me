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
