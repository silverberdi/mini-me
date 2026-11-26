"""Focused contract tests for the Dashboard temporal telemetry projection."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tests.conftest import InMemoryPersistenceUnitOfWork

from minime.domain.enums import OrchestrationStage
from minime.domain.models import (
    BudgetLedgerEntry,
    OrchestrationRun,
    OrchestrationStageEvent,
    Project,
    ProviderEfficiencyMetrics,
)
from minime.services.temporal_multiseries_telemetry_service import (
    TemporalMultiseriesTelemetryService,
    TemporalTelemetryPointDTO,
)

NOW = datetime.now(UTC).replace(microsecond=0)


def _run(run_id: str, project_id: str, days_ago: int = 1) -> OrchestrationRun:
    when = NOW - timedelta(days=days_ago)
    return OrchestrationRun(
        run_id=run_id,
        project_id=project_id,
        change_name=f"change-{run_id}",
        base_sha="a" * 40,
        created_at=when,
        updated_at=when,
        current_stage=OrchestrationStage.COMPLETED,
        is_active=False,
    )


def _service() -> tuple[InMemoryPersistenceUnitOfWork, TemporalMultiseriesTelemetryService]:
    uow = InMemoryPersistenceUnitOfWork()
    uow.projects.save(Project(project_id="p1", display_name="Uno", repository="owner/p1"))
    uow.projects.save(Project(project_id="p2", display_name="Dos", repository="owner/p2"))
    return uow, TemporalMultiseriesTelemetryService(uow)


def test_point_rejects_missing_timestamp_or_verifiable_source() -> None:
    with pytest.raises(ValidationError):
        TemporalTelemetryPointDTO(timestamp="", value=1, source_timestamps=[])


def test_autonomy_is_completed_run_share_and_retries_do_not_change_it() -> None:
    uow, service = _service()
    clean = _run("clean", "p1", 2)
    retry = _run("retry", "p2", 1)
    clean.stop_details = {"resolved_human_gates": []}
    retry.stop_details = {"resolved_human_gates": []}
    uow.orchestration_runs.save(clean)
    uow.orchestration_runs.save(retry)
    for run in (clean, retry):
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            run_id=run.run_id,
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.COMPLETED,
            created_at=run.created_at,
            event_type="RUN_COMPLETED",
        ))
    uow.provider_efficiency.save(ProviderEfficiencyMetrics(
        run_id="clean", project_id="p1", change_name=clean.change_name,
        productive_attempt_count=4,
    ))
    uow.provider_efficiency.save(ProviderEfficiencyMetrics(
        run_id="retry", project_id="p2", change_name=retry.change_name,
        productive_attempt_count=4, no_progress_attempt_count=2,
        same_sha_retry_count=1, corrective_retry_count=1,
    ))

    projection = service.project("autonomy")
    values = {s.project_id: s.points[0].value for s in projection.series if s.project_id}
    assert values == {"p1": 100.0, "p2": 100.0}
    assert projection.series[0].label == "Global (Todos los proyectos)"


def test_autonomy_window_uses_completion_time_for_long_running_runs() -> None:
    uow, service = _service()
    run = _run("long-running", "p1", 60)
    run.updated_at = NOW - timedelta(days=1)
    run.stop_details = {"resolved_human_gates": []}
    uow.orchestration_runs.save(run)
    uow.orchestration_stage_events.save(OrchestrationStageEvent(
        run_id=run.run_id,
        from_stage=OrchestrationStage.IMPLEMENTING,
        to_stage=OrchestrationStage.COMPLETED,
        created_at=run.updated_at,
        event_type="RUN_COMPLETED",
    ))

    projection = service.project("autonomy", window_days=30)

    assert projection.no_data is False
    assert projection.series[1].points[-1].value == 100.0


def test_time_excludes_human_gate_wait_and_orders_axis() -> None:
    uow, service = _service()
    run = _run("timed", "p1", 1)
    uow.orchestration_runs.save(run)
    uow.orchestration_stage_events.save(OrchestrationStageEvent(
        run_id=run.run_id, to_stage=OrchestrationStage.IMPLEMENTING,
        from_stage=OrchestrationStage.IMPLEMENTING,
        created_at=run.created_at,
        evidence_references={"active_machine_duration_ms": 120000},
    ))
    uow.orchestration_stage_events.save(OrchestrationStageEvent(
        run_id=run.run_id, to_stage=OrchestrationStage.PROPOSING,
        from_stage=OrchestrationStage.PROPOSING,
        created_at=run.created_at,
        evidence_references={"stage_duration_ms": 3600000, "interval_type": "human_gate_wait"},
    ))

    projection = service.project("time")
    point = projection.series[1].points[0]
    assert point.value == 2.0
    assert projection.excluded["human_gate_wait_intervals"] == 1
    assert projection.axis == sorted(projection.axis)


def test_cost_requires_liquidated_settlement_and_ignores_tokens() -> None:
    uow, service = _service()
    run = _run("costed", "p1", 1)
    uow.orchestration_runs.save(run)
    uow.budget_ledger.save(BudgetLedgerEntry(
        project_id="p1", job_id="job", change_id=run.change_name,
        provider="openrouter", billing_origin="openrouter", role="execution",
        canonical_model_identity="openrouter/model", amount_usd=Decimal("4.25"),
        total_tokens=999999, entry_type="SETTLEMENT", reservation_id="res",
        created_at=run.created_at,
    ))
    projection = service.project("cost")
    assert projection.series[1].points[0].value == 4.25

    uow.budget_ledger = type(uow.budget_ledger)()
    projection = service.project("cost")
    assert projection.no_data is True


def test_time_recognizes_duration_ms_key() -> None:
    uow, service = _service()
    run = _run("timed-duration", "p1", 1)
    uow.orchestration_runs.save(run)
    uow.orchestration_stage_events.save(OrchestrationStageEvent(
        run_id=run.run_id, to_stage=OrchestrationStage.IMPLEMENTING,
        from_stage=OrchestrationStage.IMPLEMENTING,
        created_at=run.created_at,
        evidence_references={"duration_ms": 180000},
    ))
    projection = service.project("time")
    point = projection.series[1].points[0]
    assert point.value == 3.0


def test_autonomy_derived_from_stage_events_when_metrics_absent() -> None:
    uow, service = _service()
    run = _run("event-autonomy", "p1", 1)
    run.stop_details = {"resolved_human_gates": []}
    uow.orchestration_runs.save(run)
    # Retries and failed stage attempts are not operator-intervention counts.
    for _ in range(3):
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            event_type="STAGE_INVOCATION_COMPLETED",
            run_id=run.run_id, to_stage=OrchestrationStage.IMPLEMENTING,
            from_stage=OrchestrationStage.IMPLEMENTING,
            created_at=run.created_at,
            evidence_references={"status": "COMPLETE", "recovery_count": 0},
        ))
    uow.orchestration_stage_events.save(OrchestrationStageEvent(
        event_type="STAGE_INVOCATION_COMPLETED",
        run_id=run.run_id, to_stage=OrchestrationStage.PROPOSING,
        from_stage=OrchestrationStage.PROPOSING,
        created_at=run.created_at,
        evidence_references={"status": "FAILED", "recovery_count": 0},
    ))
    projection = service.project("autonomy")
    point = projection.series[1].points[0]
    assert point.value == 100.0


def test_autonomy_penalizes_failed_abandoned_and_human_required_events() -> None:
    uow, service = _service()
    run = _run("event-penalties", "p1", 1)
    run.stop_details = {"resolved_human_gates": [{"gate_id": "gate-1", "response": "continue"}]}
    uow.orchestration_runs.save(run)
    # 4 completed stages
    for _ in range(4):
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            event_type="STAGE_INVOCATION_COMPLETED",
            run_id=run.run_id, to_stage=OrchestrationStage.IMPLEMENTING,
            from_stage=OrchestrationStage.IMPLEMENTING,
            created_at=run.created_at,
            evidence_references={"status": "COMPLETE", "recovery_count": 0},
        ))
    # 1 failed, 1 abandoned, 1 human required
    uow.orchestration_stage_events.save(OrchestrationStageEvent(
        event_type="STAGE_INVOCATION_FAILED",
        run_id=run.run_id, to_stage=OrchestrationStage.PROPOSING,
        from_stage=OrchestrationStage.PROPOSING,
        created_at=run.created_at,
    ))
    uow.orchestration_stage_events.save(OrchestrationStageEvent(
        event_type="STAGE_INVOCATION_ABANDONED",
        run_id=run.run_id, to_stage=OrchestrationStage.PROPOSING,
        from_stage=OrchestrationStage.PROPOSING,
        created_at=run.created_at,
    ))
    uow.orchestration_stage_events.save(OrchestrationStageEvent(
        event_type="STAGE_INVOCATION_HUMAN_REQUIRED",
        run_id=run.run_id, to_stage=OrchestrationStage.PROPOSING,
        from_stage=OrchestrationStage.PROPOSING,
        created_at=run.created_at,
    ))
    projection = service.project("autonomy")
    point = projection.series[1].points[0]
    assert point.value == 0.0


def test_autonomy_returns_no_data_when_completed_run_lacks_intervention_evidence() -> None:
    uow, service = _service()
    run = _run("ambiguous-autonomy", "p1", 1)
    uow.orchestration_runs.save(run)
    uow.orchestration_stage_events.save(OrchestrationStageEvent(
        event_type="RUN_COMPLETED",
        run_id=run.run_id,
        to_stage=OrchestrationStage.COMPLETED,
        from_stage=OrchestrationStage.IMPLEMENTING,
        created_at=run.created_at,
    ))

    projection = service.project("autonomy")

    assert projection.no_data is True
    assert projection.series[0].no_data is True
    assert projection.excluded["unverified_or_incomplete"] == 1


def test_autonomy_recognizes_clean_completed_run_without_explicit_gate_list() -> None:
    uow, service = _service()
    run = _run("clean-autonomous", "p1", 1)
    run.stop_details = {
        "pr1_url": "https://github.com/silverberdi/test/pull/1",
        "pr2_url": "https://github.com/silverberdi/test/pull/2",
        "test_evidence": {"status": "PASSED"},
    }
    uow.orchestration_runs.save(run)
    uow.orchestration_stage_events.save(OrchestrationStageEvent(
        event_type="RUN_COMPLETED",
        run_id=run.run_id,
        to_stage=OrchestrationStage.COMPLETED,
        from_stage=OrchestrationStage.IMPLEMENTING,
        created_at=run.created_at,
    ))

    projection = service.project("autonomy")

    assert projection.no_data is False
    assert projection.series[1].points[0].value == 100.0
    assert projection.excluded.get("unverified_or_incomplete", 0) == 0


def test_autonomy_projection_exposes_clean_recovered_and_operator_outcomes() -> None:
    uow, service = _service()
    clean = _run("outcome-clean", "p1", 1)
    recovered = _run("outcome-recovered", "p1", 1)
    operator = _run("outcome-operator", "p2", 1)
    clean.stop_details = {"resolved_human_gates": []}
    recovered.stop_details = {"resolved_human_gates": []}
    operator.stop_details = {"resolved_human_gates": [{"gate_id": "gate-1"}]}
    for run in (clean, recovered, operator):
        uow.orchestration_runs.save(run)
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            run_id=run.run_id,
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.COMPLETED,
            event_type="RUN_COMPLETED",
            created_at=run.updated_at,
        ))
    for kind in ("SRE_UNBLOCKER_ATTEMPTED", "SRE_UNBLOCKER_RESOLVED"):
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            run_id=recovered.run_id,
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            event_type=kind,
            created_at=recovered.updated_at,
        ))

    projection = service.project("autonomy")
    points = {series.project_id: series.points[0] for series in projection.series if series.project_id}

    assert points["p1"].value == 100.0
    assert points["p1"].autonomy_outcomes == {
        "no_intervention": 1, "autonomous_recovery": 1,
    }
    assert points["p2"].value == 0.0
    assert points["p2"].autonomy_outcomes == {"operator_needed": 1}


def test_temporal_telemetry_respects_custom_window_days() -> None:
    uow, service = _service()
    projection_7 = service.project("autonomy", window_days=7)
    assert len(projection_7.axis) == 7
    assert projection_7.window_days == 7
    assert projection_7.granularity == "daily"

    projection_14 = service.project("autonomy", window_days=14)
    assert len(projection_14.axis) == 14
    assert projection_14.window_days == 14
    assert projection_14.granularity == "daily"

    projection_90 = service.project("autonomy", window_days=90)
    assert projection_90.window_days == 90
    assert projection_90.granularity == "weekly"
    assert len(projection_90.axis) >= 13


def test_dashboard_service_overview_passes_window_days() -> None:
    from minime.services.dashboard_service import OperationsDashboardService

    uow, _ = _service()
    dashboard_svc = OperationsDashboardService(uow)
    overview = dashboard_svc.get_overview(window_days=7)
    assert len(overview.temporal_telemetry["autonomy"].axis) == 7

