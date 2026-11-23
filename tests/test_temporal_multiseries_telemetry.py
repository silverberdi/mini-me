"""Focused contract tests for the Dashboard temporal telemetry projection."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from minime.domain.models import (
    BudgetLedgerEntry,
    OrchestrationRun,
    OrchestrationStageEvent,
    Project,
    ProviderEfficiencyMetrics,
)
from minime.domain.enums import OrchestrationStage
from minime.services.temporal_multiseries_telemetry_service import (
    TemporalMultiseriesTelemetryService,
    TemporalTelemetryPointDTO,
)
from tests.conftest import InMemoryPersistenceUnitOfWork


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


def test_autonomy_is_bounded_and_rework_lowers_score() -> None:
    uow, service = _service()
    clean = _run("clean", "p1", 2)
    retry = _run("retry", "p2", 1)
    uow.orchestration_runs.save(clean)
    uow.orchestration_runs.save(retry)
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
    assert 0 <= values["p1"] <= 100
    assert 0 <= values["p2"] <= 100
    assert values["p2"] < values["p1"]
    assert projection.series[0].label == "Global (Todos los proyectos)"


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
    uow.orchestration_runs.save(run)
    # 3 completed stages, 1 recovery penalty
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
    # 3 productive / (3 + 1) = 75.0%
    assert point.value == 75.0
