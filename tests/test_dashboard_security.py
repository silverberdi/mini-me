"""Tests proving secret redaction and credential safety on dashboard read models."""

from __future__ import annotations

from minime.domain.enums import (
    AuditRiskLevel,
    AuditStatus,
    ChangeStatus,
    EvidenceDiagnosticStatus,
    FindingSeverity,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ReadinessState,
    ReviewVerdict,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    AuditFinding,
    AuditRecord,
    Change,
    EvidenceDiagnostic,
    Job,
    OrchestrationRun,
    OrchestrationStageEvent,
    Project,
    Review,
    ReviewFinding,
)
from minime.services.dashboard_service import OperationsDashboardService


def test_dashboard_redacts_api_keys_and_tokens(
    in_memory_uow: PersistenceUnitOfWork,
) -> None:
    service = OperationsDashboardService(in_memory_uow)

    project = Project(
        project_id="secure-proj",
        display_name="Secure Project",
        repository="owner/secure-proj",
        base_branch="main",
        openspec_path="openspec",
    )
    in_memory_uow.projects.save(project)

    change = Change(
        project_id="secure-proj",
        name="012-secret-test",
        status=ChangeStatus.IN_PROGRESS,
        last_readiness_status=ReadinessState.READY,
    )
    in_memory_uow.changes.save(change)

    job = Job(
        job_id="job-sec",
        project_id="secure-proj",
        change_name="012-secret-test",
        implementer_role="codex",
    )
    in_memory_uow.jobs.save(job)

    secret_key = "sk-ant-api03-abcdef1234567890abcdef1234567890"
    secret_ds = "sk-deepseek-998877665544332211"
    secret_gh = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    secret_aws = "AKIAIOSFODNN7EXAMPLE"
    secret_slack = "xoxb-1234567890-abcdefghijkl"
    secret_pat = "github_pat_11ABCD_efghijklmnopqrstuv"

    # Stopped run with secret in stop_reason
    run = OrchestrationRun(
        run_id="run-sec",
        project_id="secure-proj",
        change_name="012-secret-test",
        active_job_id="job-sec",
        base_sha="base-sec",
        current_stage=OrchestrationStage.IMPLEMENTING,
        is_active=False,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        stop_reason=f"Failed connecting to provider using token={secret_key} and access_key={secret_aws}",
    )
    in_memory_uow.orchestration_runs.save(run)

    # Review with secret finding
    rev = Review(
        review_id="rev-sec",
        job_id="job-sec",
        project_id="secure-proj",
        change_name="012-secret-test",
        reviewer_role="antigravity",
        candidate_sha="cand-sha-sec",
        base_sha="base-sha-sec",
        verdict=ReviewVerdict.CHANGES_REQUIRED,
        summary=f"Found leaked token={secret_gh} and slack={secret_slack} and pat={secret_pat} in configuration",
    )
    in_memory_uow.reviews.save(rev)
    rf = ReviewFinding(
        finding_id="rf-1",
        review_id="rev-sec",
        severity=FindingSeverity.BLOCKER,
        violated_requirement=f"Do not commit token={secret_gh}",
        expected_correction="Remove secret",
    )
    in_memory_uow.review_findings.save(rf)

    # Audit with secret
    aud = AuditRecord(
        audit_id="aud-sec",
        job_id="job-sec",
        project_id="secure-proj",
        change_name="012-secret-test",
        provider="deepseek",
        candidate_sha="cand-sha-sec",
        base_sha="base-sha-sec",
        summary=f"Audit caught api_key={secret_ds} and secret_key={secret_aws}",
        status=AuditStatus.AUDIT_COMPLETED,
        risk=AuditRiskLevel.HIGH,
    )
    in_memory_uow.audits.save(aud)
    af = AuditFinding(
        finding_id="af-1",
        audit_id="aud-sec",
        severity="critical",
        category="security",
        message=f"Hardcoded secret={secret_ds}",
    )
    in_memory_uow.audit_findings.save(af)

    # Diagnostic with secret command
    diag = EvidenceDiagnostic(
        job_id="job-sec",
        stage_type="CHECKS",
        check_name="pytest",
        environment_identity="local",
        candidate_sha="cand-sha-sec",
        diagnostic_status=EvidenceDiagnosticStatus.FAIL,
        reason=f"pytest failed with api_key={secret_key}",
    )
    in_memory_uow.evidence_diagnostics.save(diag)

    # Stage event with secret
    se = OrchestrationStageEvent(
        run_id="run-sec",
        from_stage=OrchestrationStage.PREPARING_EXECUTION,
        to_stage=OrchestrationStage.IMPLEMENTING,
        evidence_references={"reason": f"Started agent with token={secret_key}"},
    )
    in_memory_uow.orchestration_stage_events.save(se)

    # 1. Overview Check
    overview = service.get_overview()
    overview_json = overview.model_dump_json()
    assert secret_key not in overview_json
    assert secret_ds not in overview_json
    assert secret_gh not in overview_json
    assert secret_aws not in overview_json
    assert secret_slack not in overview_json
    assert secret_pat not in overview_json

    # 2. Detail Check
    detail = service.get_change_detail("secure-proj", "012-secret-test")
    detail_json = detail.model_dump_json()
    assert secret_key not in detail_json
    assert secret_ds not in detail_json
    assert secret_gh not in detail_json
    assert secret_aws not in detail_json
    assert secret_slack not in detail_json
    assert secret_pat not in detail_json
    assert "[REDACTED" in detail_json
