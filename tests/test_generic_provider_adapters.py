"""Unit tests for generic provider adapters and capacity recovery probing."""

from datetime import datetime, timezone

import pytest

from minime.adapters.provider_adapter import (
    FakeProviderAdapter,
    get_provider_adapter,
    register_provider_adapter,
)
from minime.domain.enums import (
    CapacitySignalSource,
    JobStatus,
    ProviderHealthStatus,
    ProviderResultClass,
    SchedulerMode,
)
from minime.domain.models import (
    Job,
    NormalizedProviderResult,
    Project,
)
from minime.services.openrouter_eligibility import (
    OpenRouterEligibilityEvaluator,
    is_material_execution_started,
)
from minime.services.provider_health_service import ProviderHealthService


@pytest.mark.asyncio
async def test_fake_provider_adapter_registration(in_memory_uow):
    """Prove that future provider (e.g., Cursor) plugs in through adapter without scheduler rewrite."""
    cursor_adapter = FakeProviderAdapter(name="cursor", available=True)
    register_provider_adapter(cursor_adapter)

    retrieved = get_provider_adapter("cursor")
    assert retrieved.provider_name == "cursor"
    assert "implementer" in retrieved.supported_roles
    assert await retrieved.probe_availability() is True
    assert cursor_adapter.probe_call_count == 1


@pytest.mark.asyncio
async def test_generic_provider_probing_lifecycle(in_memory_uow):
    """Test positive and negative probe transitions through generic health service."""
    health_svc = ProviderHealthService(in_memory_uow)

    # Initially unavailable
    health_svc.record_outcome(
        NormalizedProviderResult(
            provider="codex",
            role="implementer",
            result_class=ProviderResultClass.RATE_LIMIT,
            summary="Codex capacity exhausted",
        )
    )
    health = health_svc.get_health("codex")
    assert health.status == ProviderHealthStatus.TEMPORARILY_UNAVAILABLE

    # Register mock adapter with failing probe
    mock_adapter = FakeProviderAdapter(name="codex", available=False)
    register_provider_adapter(mock_adapter)

    # Negative probe preserves unavailable state
    success = await health_svc.check_and_probe_provider("codex")
    assert success is False
    assert health_svc.get_health("codex").status == ProviderHealthStatus.TEMPORARILY_UNAVAILABLE

    # Positive probe recovers to AVAILABLE
    mock_adapter.available = True
    success = await health_svc.check_and_probe_provider("codex")
    assert success is True
    assert health_svc.get_health("codex").status == ProviderHealthStatus.AVAILABLE
    assert health_svc.get_health("codex").consecutive_failures == 0

    # Ensure 0 runs or jobs were created
    assert in_memory_uow.jobs.list_active_jobs() == []
    assert in_memory_uow.orchestration_runs.list_runs() == []


@pytest.mark.asyncio
async def test_operator_reported_reset(in_memory_uow):
    """Test operator-reported return time persistence."""
    health_svc = ProviderHealthService(in_memory_uow)
    future_time = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)

    window = health_svc.set_operator_expected_reset("codex", future_time)
    assert window.source_signal == CapacitySignalSource.OPERATOR_REPORTED
    assert window.capacity_reset_at == future_time

    latest = in_memory_uow.capacity_windows.get_latest_for_provider("codex")
    assert latest is not None
    assert latest.capacity_reset_at == future_time
    assert latest.source_signal == CapacitySignalSource.OPERATOR_REPORTED


def test_drain_eligibility_requires_material_execution():
    """Verify that drain fallback is strictly denied for BACKLOG/READY work without material execution."""
    evaluator = OpenRouterEligibilityEvaluator()

    project = Project(
        project_id="test-proj",
        display_name="Test",
        repository="owner/repo",
        openrouter_drain_allowed=True,
    )

    # 1. Job with 0 attempts and no candidate (NOT materially started)
    not_started_job = Job(
        project_id="test-proj",
        change_name="new-feature",
        status=JobStatus.RUNNING,
        implementer_role="codex",
        attempt_count=0,
        candidate_sha=None,
    )
    assert not is_material_execution_started(not_started_job)

    res = evaluator.evaluate_10_points(
        scheduler_mode=SchedulerMode.DRAIN,
        job=not_started_job,
        role="implementer",
        is_new_ready_change=False,
        primary_health_records=[],
        project=project,
        policy=None,
        headroom=None,
    )
    assert res.eligible is False

    # 2. In-flight job with material execution started (attempt_count = 1)
    started_job = Job(
        project_id="test-proj",
        change_name="in-flight-feature",
        status=JobStatus.RUNNING,
        implementer_role="codex",
        attempt_count=1,
        candidate_sha=None,
    )
    assert is_material_execution_started(started_job)


def test_drain_denied_for_new_ready_change():
    """Verify that drain fallback is rejected when is_new_ready_change is True."""
    evaluator = OpenRouterEligibilityEvaluator()
    project = Project(
        project_id="test-proj",
        display_name="Test",
        repository="owner/repo",
        openrouter_drain_allowed=True,
    )
    job = Job(
        project_id="test-proj",
        change_name="ready-feature",
        status=JobStatus.RUNNING,
        implementer_role="codex",
        attempt_count=1,
    )

    res = evaluator.evaluate_10_points(
        scheduler_mode=SchedulerMode.DRAIN,
        job=job,
        role="implementer",
        is_new_ready_change=True,
        primary_health_records=[],
        project=project,
        policy=None,
        headroom=None,
    )
    assert res.eligible is False
    assert "Cannot admit new READY" in (res.denial_reason or "")
