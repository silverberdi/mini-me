"""Tests for operational observability, stage duration tracking, and token accounting."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from minime.domain.enums import ExecutionOutcome, OrchestrationStage
from minime.domain.models import (
    BudgetLedgerEntry,
    EvidenceDiagnostic,
    Job,
    JobAttempt,
    OrchestrationRun,
    OrchestrationStageEvent,
    Review,
)
from minime.services.contract_review_service import (
    DeepSeekResponseDiagnostics,
    DeepSeekReviewResponse,
    persist_deepseek_response_diagnostic,
)
from minime.services.efficiency_telemetry_service import EfficiencyTelemetryService


def test_operational_duration_breakdown_calculation(in_memory_uow):
    now = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    run_id = "run-breakdown-1"
    job_id = "job-breakdown-1"
    project_id = "proj-1"
    change_name = "efficiency-test"

    run = OrchestrationRun(
        run_id=run_id,
        project_id=project_id,
        change_name=change_name,
        base_sha="base-123",
        active_job_id=job_id,
        created_at=now,
        updated_at=now + timedelta(seconds=120),
    )
    in_memory_uow.orchestration_runs.save(run)

    job = Job(
        job_id=job_id,
        project_id=project_id,
        change_name=change_name,
        implementer_role="antigravity",
    )
    in_memory_uow.jobs.save(job)

    # Job attempts (implementer active compute)
    in_memory_uow.job_attempts.save(
        JobAttempt(
            attempt_id="att-1",
            job_id=job_id,
            attempt_number=1,
            executor_role="antigravity",
            model_identity="gemini-2.5-pro",
            normalized_outcome=ExecutionOutcome.COMPLETED,
            duration_ms=45000,
        )
    )

    # Stage events with recorded stage_duration_ms
    stage_sequence = [
        (OrchestrationStage.ADMITTED, OrchestrationStage.PREPARING_EXECUTION, 5000),
        (OrchestrationStage.PREPARING_EXECUTION, OrchestrationStage.IMPLEMENTING, 8000),
        (OrchestrationStage.IMPLEMENTING, OrchestrationStage.RUNNING_CHECKS, 45000),
        (OrchestrationStage.RUNNING_CHECKS, OrchestrationStage.COMPLEMENTARY_REVIEW, 12000),
        (OrchestrationStage.COMPLEMENTARY_REVIEW, OrchestrationStage.PREPARING_PR, 15000),
        (OrchestrationStage.PREPARING_PR, OrchestrationStage.COMPLETED, 10000),
    ]
    for from_stage, to_stage, dur_ms in stage_sequence:
        in_memory_uow.orchestration_stage_events.save(
            OrchestrationStageEvent(
                run_id=run_id,
                from_stage=from_stage,
                to_stage=to_stage,
                evidence_references={"stage_duration_ms": dur_ms},
            )
        )

    # Diagnostics with transport retries & stalls
    in_memory_uow.evidence_diagnostics.save(
        EvidenceDiagnostic(
            job_id=job_id,
            stage_type="CONTRACT_REVIEW",
            diagnostic_status="PASS",
            environment_identity="native_provider",
            candidate_sha="sha1",
            evidence_reference={
                "transport_retry_count": 2,
                "transport_stall_ms": 3200,
            },
        )
    )

    # Budget ledger token and cost entries
    in_memory_uow.budget_ledger.save(
        BudgetLedgerEntry(
            id="entry-1",
            project_id=project_id,
            job_id=job_id,
            change_id=change_name,
            provider="deepseek",
            stage="CONTRACT_REVIEW",
            role="reviewer",
            canonical_model_identity="deepseek-chat",
            prompt_tokens=1500,
            completion_tokens=250,
            total_tokens=1750,
            amount_usd=Decimal("0.003500"),
            entry_type="STANDARD_SETTLEMENT",
        )
    )
    in_memory_uow.budget_ledger.save(
        BudgetLedgerEntry(
            id="entry-2",
            project_id=project_id,
            job_id=job_id,
            change_id=change_name,
            provider="deepseek",
            stage="CODE_REVIEW",
            role="reviewer",
            canonical_model_identity="deepseek-chat",
            prompt_tokens=2200,
            completion_tokens=400,
            total_tokens=2600,
            amount_usd=Decimal("0.005200"),
            entry_type="STANDARD_SETTLEMENT",
        )
    )

    service = EfficiencyTelemetryService(in_memory_uow)
    breakdown = service.get_operational_duration_breakdown(run_id)

    assert breakdown["run_id"] == run_id
    assert breakdown["project_id"] == project_id
    assert breakdown["admission_duration_ms"] == 5000
    assert breakdown["contract_review_duration_ms"] == 8000
    assert breakdown["implementer_active_compute_duration_ms"] == 45000
    assert breakdown["checks_duration_ms"] == 12000
    assert breakdown["code_review_duration_ms"] == 15000
    assert breakdown["pr_preparation_duration_ms"] == 10000
    assert breakdown["transport_retry_count"] == 2
    assert breakdown["transport_stall_ms"] == 3200
    assert breakdown["total_duration_ms"] == 120000
    assert breakdown["total_prompt_tokens"] == 3700
    assert breakdown["total_completion_tokens"] == 650
    assert breakdown["total_cost_usd"] == 0.0087
    assert breakdown["tokens_by_stage"]["CONTRACT_REVIEW"]["prompt_tokens"] == 1500
    assert breakdown["tokens_by_stage"]["CODE_REVIEW"]["prompt_tokens"] == 2200


def test_operational_telemetry_secret_redaction(in_memory_uow):
    run_id = "run-secret-1"
    secret_token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"

    run = OrchestrationRun(
        run_id=run_id,
        project_id="proj-1",
        change_name=f"test-change-with-{secret_token}",
        base_sha="base-123",
        active_job_id=None,
    )
    in_memory_uow.orchestration_runs.save(run)

    service = EfficiencyTelemetryService(in_memory_uow)
    breakdown = service.get_operational_duration_breakdown(run_id)

    assert secret_token not in str(breakdown)
    assert "[REDACTED_TOKEN]" in breakdown["change_name"]


def test_persist_deepseek_response_diagnostic_records_evidence_diagnostic(in_memory_uow):
    review = Review(
        review_id="rev-123",
        project_id="proj-1",
        change_name="change-test",
        job_id="job-123",
        orchestration_run_id="run-123",
        review_stage="CODE_REVIEW",
        candidate_sha="abc123sha",
        contract_hash="hash123",
        reviewer_role="deepseek",
        reviewer_model="deepseek-chat",
        base_sha="base-123",
    )
    diag = DeepSeekResponseDiagnostics(
        http_status=200,
        transport_retry_count=3,
        transport_stall_ms=2500,
        prompt_tokens=420,
        completion_tokens=80,
    )
    response = DeepSeekReviewResponse(
        exit_code=0,
        content="ACCEPTED",
        model="deepseek-chat",
        prompt_tokens=420,
        completion_tokens=80,
        response_diagnostics=diag,
    )

    persist_deepseek_response_diagnostic(in_memory_uow, review, response)

    diags = in_memory_uow.evidence_diagnostics.list_by_job("job-123")
    assert len(diags) == 1
    assert diags[0].stage_type == "CODE_REVIEW"
    assert diags[0].diagnostic_status == "PASS"
    assert diags[0].evidence_reference["transport_retry_count"] == 3
    assert diags[0].evidence_reference["transport_stall_ms"] == 2500
    assert diags[0].evidence_reference["prompt_tokens"] == 420
    assert diags[0].evidence_reference["completion_tokens"] == 80


def test_stage_transition_records_stage_duration_fact(in_memory_uow):
    from minime.domain.enums import OrchestrationStage
    from minime.domain.models import OrchestrationRun
    from minime.services.orchestration_service import OrchestrationService

    orch = OrchestrationService(in_memory_uow)
    run = OrchestrationRun(
        run_id="run-trans-1",
        project_id="proj-1",
        change_name="change-trans",
        base_sha="base-trans",
        current_stage=OrchestrationStage.ADMITTED,
    )
    in_memory_uow.orchestration_runs.save(run)

    # First transition: ADMITTED -> PREPARING_EXECUTION
    orch._advance_stage(run, OrchestrationStage.PREPARING_EXECUTION)

    # Second transition: PREPARING_EXECUTION -> IMPLEMENTING
    orch._advance_stage(run, OrchestrationStage.IMPLEMENTING)

    events = in_memory_uow.orchestration_stage_events.list_by_run("run-trans-1")
    assert len(events) == 2
    assert "stage_duration_ms" in events[1].evidence_references
    assert isinstance(events[1].evidence_references["stage_duration_ms"], int)

    metrics = in_memory_uow.metrics.list_facts(change_id="change-trans", metric_name="stage_duration_ms")
    assert len(metrics) >= 1
    assert metrics[-1].stage == OrchestrationStage.PREPARING_EXECUTION.value

