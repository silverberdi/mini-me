"""Tests proving candidate authority and stale evidence isolation in dashboard."""

from __future__ import annotations

from minime.domain.enums import (
    AuditRiskLevel,
    AuditStatus,
    ChangeStatus,
    JobStatus,
    OrchestrationStage,
    ReadinessState,
    ReviewVerdict,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    AuditRecord,
    Change,
    Job,
    OrchestrationCandidate,
    OrchestrationRun,
    Project,
    Review,
)
from minime.services.dashboard_service import OperationsDashboardService


def test_stale_review_and_audit_isolation_on_new_generation(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    service = OperationsDashboardService(in_memory_uow)

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
        implementer="codex",
        reviewer="antigravity",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="mini-me",
        name="010-governance",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        job_id="job-gen2",
        project_id="mini-me",
        change_name="010-governance",
        implementer_role="codex",
        status=JobStatus.RUNNING,
        candidate_sha="sha-generation-2",
        base_sha="sha-base",
    )
    in_memory_uow.jobs.save(job)

    # Historical candidate gen-1 (superseded)
    c1 = OrchestrationCandidate(
        candidate_id="cand-1",
        run_id="run-remediated",
        generation=1,
        candidate_sha="sha-generation-1",
        base_sha="sha-base",
        manifest_hash="hash-gen1",
        is_frozen=True,
        superseded_by_id="cand-2",
    )
    # Active candidate gen-2 (current)
    c2 = OrchestrationCandidate(
        candidate_id="cand-2",
        run_id="run-remediated",
        generation=2,
        candidate_sha="sha-generation-2",
        base_sha="sha-base",
        manifest_hash="hash-gen2",
        is_frozen=True,
    )
    in_memory_uow.orchestration_candidates.save(c1)
    in_memory_uow.orchestration_candidates.save(c2)

    # Older Review bound to generation-1 SHA
    rev_gen1 = Review(
        review_id="rev-old",
        job_id="job-gen2",
        project_id="mini-me",
        change_name="010-governance",
        reviewer_role="antigravity",
        candidate_sha="sha-generation-1",
        base_sha="sha-base",
        verdict=ReviewVerdict.READY_TO_MERGE,
    )
    in_memory_uow.reviews.save(rev_gen1)

    # Older Audit bound to generation-1 SHA
    aud_gen1 = AuditRecord(
        audit_id="aud-old",
        job_id="job-gen2",
        project_id="mini-me",
        change_name="010-governance",
        provider="deepseek",
        model="deepseek-chat",
        candidate_sha="sha-generation-1",
        base_sha="sha-base",
        status=AuditStatus.AUDIT_COMPLETED,
        risk=AuditRiskLevel.LOW,
    )
    in_memory_uow.audits.save(aud_gen1)

    # Orchestration run currently at generation 2
    run = OrchestrationRun(
        run_id="run-remediated",
        project_id="mini-me",
        change_name="010-governance",
        active_job_id="job-gen2",
        current_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        is_active=True,
        current_generation=2,
        current_candidate_sha="sha-generation-2",
        base_sha="sha-base",
    )
    in_memory_uow.orchestration_runs.save(run)

    detail = service.get_change_detail("mini-me", "010-governance")

    # 1. Authority must be generation 2
    assert detail.candidate_authority is not None
    assert detail.candidate_authority.generation == 2
    assert detail.candidate_authority.candidate_sha == "sha-generation-2"

    # 2. History must contain both generation 1 and 2
    assert len(detail.candidate_history) == 2
    assert detail.candidate_history[0].generation == 1
    assert detail.candidate_history[0].is_superseded is True
    assert detail.candidate_history[1].generation == 2
    assert detail.candidate_history[1].is_superseded is False

    # 3. Review must be flagged as stale
    assert detail.review.is_stale_to_current_candidate is True
    assert detail.review.candidate_sha == "sha-generation-1"

    # 4. Audit must be flagged as stale
    assert detail.audit.is_stale_to_current_candidate is True
    assert detail.audit.candidate_sha == "sha-generation-1"

    # 5. Pipeline review phase must NOT report passed
    phase_map = {p.name: p.status for p in detail.pipeline}
    assert phase_map["review"] == "running"
    assert "progress" in detail.pipeline[3].summary.lower() or "pending" in detail.pipeline[3].summary.lower()


def test_stale_changes_required_review_not_presented_as_current_failure(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    service = OperationsDashboardService(in_memory_uow)

    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="mini-me",
        name="011-remediation",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        job_id="job-remediation",
        project_id="mini-me",
        change_name="011-remediation",
        implementer_role="codex",
        status=JobStatus.RUNNING,
        candidate_sha="sha-gen2",
        base_sha="sha-base",
    )
    in_memory_uow.jobs.save(job)

    # Older Review with CHANGES_REQUIRED on generation-1
    rev_gen1 = Review(
        review_id="rev-cr-old",
        job_id="job-remediation",
        project_id="mini-me",
        change_name="011-remediation",
        reviewer_role="antigravity",
        candidate_sha="sha-gen1",
        base_sha="sha-base",
        verdict=ReviewVerdict.CHANGES_REQUIRED,
    )
    in_memory_uow.reviews.save(rev_gen1)

    # Run is currently at REVIEW_REMEDIATION for generation 2
    run = OrchestrationRun(
        run_id="run-rem",
        project_id="mini-me",
        change_name="011-remediation",
        active_job_id="job-remediation",
        current_stage=OrchestrationStage.REVIEW_REMEDIATION,
        is_active=True,
        current_generation=2,
        current_candidate_sha="sha-gen2",
        base_sha="sha-base",
    )
    in_memory_uow.orchestration_runs.save(run)

    detail = service.get_change_detail("mini-me", "011-remediation")
    phase_map = {p.name: p.status for p in detail.pipeline}

    # Review phase must report pending/running for updated candidate, NOT failed
    assert phase_map["review"] == "running"
    assert "pending" in detail.pipeline[3].summary.lower() or "progress" in detail.pipeline[3].summary.lower()


def test_timeline_deduplicates_events_on_combined_filters(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    from minime.domain.enums import EventType
    from minime.domain.models import Event, OrchestrationStageEvent

    service = OperationsDashboardService(in_memory_uow)

    # Add stage event
    se = OrchestrationStageEvent(
        event_id="evt-shared-1",
        run_id="run-combo",
        from_stage=OrchestrationStage.RUNNING_CHECKS,
        to_stage=OrchestrationStage.COMPLEMENTARY_REVIEW,
        evidence_references={"reason": "Checks passed"},
    )
    in_memory_uow.orchestration_stage_events.save(se)

    # Add general event with identical event_id
    ge = Event(
        event_id="evt-shared-1",
        project_id="mini-me",
        change_id="012-dedup",
        event_type=EventType.JOB_CHECKS_PASSED,
        payload={"reason": "Checks passed"},
    )
    in_memory_uow.events.save(ge)

    events = service.get_events_timeline(project_id="mini-me", change_name="012-dedup", run_id="run-combo")
    # Must be deduplicated by event_id
    assert len(events) == 1
    assert events[0].event_id == "evt-shared-1"
