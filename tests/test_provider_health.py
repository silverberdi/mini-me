"""Unit tests for ProviderOutcomeParser and ProviderHealthService."""

from datetime import timedelta

import pytest

from minime.domain.enums import (
    EventType,
    ProviderHealthStatus,
    ProviderResultClass,
)
from minime.domain.models import NormalizedProviderResult, utc_now
from minime.services.provider_health_service import ProviderHealthService
from minime.services.provider_outcome_parser import ProviderOutcomeParser


def test_outcome_parser_domain_verdict_is_success():
    """Verify that domain verdicts (e.g. CHANGES_REQUIRED) are treated as transport success."""
    result = ProviderOutcomeParser.parse_runner_output(
        provider="antigravity",
        role="reviewer",
        model="gemini-2.5",
        exit_code=0,
        timed_out=False,
        stdout_lines=['{"verdict": "CHANGES_REQUIRED", "findings": []}'],
        stderr_lines=[],
        domain_verdict_valid=True,
    )
    assert result.result_class == ProviderResultClass.SUCCESS
    assert result.provider == "antigravity"
    assert result.role == "reviewer"


def test_outcome_parser_quota_limit_and_reset_hints():
    """Verify quota limit detection and extraction of reset hints."""
    output = "Error 403: insufficient_quota. Monthly limit reached. Try again in 7200 seconds."
    result = ProviderOutcomeParser.parse_runner_output(
        provider="codex",
        role="implementer",
        model="gpt-5",
        exit_code=1,
        timed_out=False,
        stdout_lines=[],
        stderr_lines=[output],
    )
    assert result.result_class == ProviderResultClass.QUOTA_LIMIT
    assert result.retry_after == "7200"
    assert result.capacity_reset_at is not None
    assert result.capacity_reset_at > utc_now()


def test_outcome_parser_rate_limit_and_header_retry_after():
    """Verify rate limit detection and header Retry-After parsing."""
    output = "HTTP 429 Too Many Requests\nRetry-After: 60"
    result = ProviderOutcomeParser.parse_runner_output(
        provider="antigravity",
        role="reviewer",
        model="gemini-2.5",
        exit_code=1,
        timed_out=False,
        stdout_lines=[output],
        stderr_lines=[],
    )
    assert result.result_class == ProviderResultClass.RATE_LIMIT
    assert result.retry_after == "60"
    assert result.capacity_reset_at is not None


def test_outcome_parser_transient_network_error():
    """Verify transient error classification."""
    output = "Connection reset by peer (ECONNRESET)"
    result = ProviderOutcomeParser.parse_runner_output(
        provider="codex",
        role="implementer",
        model="gpt-5",
        exit_code=1,
        timed_out=False,
        stdout_lines=[],
        stderr_lines=[output],
    )
    assert result.result_class == ProviderResultClass.TRANSIENT_ERROR


def test_outcome_parser_timeout():
    """Verify timeout classification."""
    result = ProviderOutcomeParser.parse_runner_output(
        provider="codex",
        role="implementer",
        model="gpt-5",
        exit_code=-1,
        timed_out=True,
        stdout_lines=[],
        stderr_lines=[],
    )
    assert result.result_class == ProviderResultClass.TIMEOUT


@pytest.mark.asyncio
async def test_provider_health_service_quota_exhaustion_lifecycle(in_memory_uow):
    """Test full quota exhaustion, capacity window recording, and events."""
    service = ProviderHealthService(in_memory_uow, failure_threshold=3)

    # Initially available
    health = service.get_health("codex")
    assert health.status == ProviderHealthStatus.AVAILABLE

    # Record quota exhaustion
    reset_time = utc_now() + timedelta(hours=2)
    outcome = NormalizedProviderResult(
        result_class=ProviderResultClass.QUOTA_LIMIT,
        provider="codex",
        role="implementer",
        retry_after="7200",
        capacity_reset_at=reset_time,
        summary="Quota exhausted",
    )
    updated = service.record_outcome(outcome)
    assert updated.status == ProviderHealthStatus.EXHAUSTED

    # Capacity window recorded
    window = in_memory_uow.capacity_windows.get_latest_for_provider("codex")
    assert window is not None
    assert window.retry_after_seconds == 7200

    # Event recorded
    events = in_memory_uow.events.list_events()
    exhaust_events = [e for e in events if e.event_type == EventType.PRIMARY_CAPACITY_EXHAUSTED]
    assert len(exhaust_events) == 1

    # Pair availability check fails
    pair_avail, reason = service.is_pair_available("codex", "antigravity")
    assert not pair_avail
    assert "codex" in reason


@pytest.mark.asyncio
async def test_provider_health_service_probing_lifecycle(in_memory_uow):
    """Test capacity reset probing requiring positive evidence before recovering available status."""
    service = ProviderHealthService(in_memory_uow, failure_threshold=3)

    # Put provider into exhausted state with past reset timestamp
    past_reset = utc_now() - timedelta(minutes=5)
    outcome = NormalizedProviderResult(
        result_class=ProviderResultClass.QUOTA_LIMIT,
        provider="antigravity",
        role="reviewer",
        capacity_reset_at=past_reset,
        summary="Quota exhausted",
    )
    service.record_outcome(outcome)
    assert service.get_health("antigravity").status == ProviderHealthStatus.EXHAUSTED

    # Case 1: Elapsed reset + probe fails -> remains exhausted
    async def failing_probe() -> bool:
        return False

    res1 = await service.check_and_probe_provider("antigravity", probe_fn=failing_probe)
    assert not res1
    assert service.get_health("antigravity").status == ProviderHealthStatus.EXHAUSTED

    probe_failed_events = [
        e
        for e in in_memory_uow.events.list_events()
        if e.event_type == EventType.PROVIDER_PROBE_FAILED
    ]
    assert len(probe_failed_events) == 1

    # Case 2: Elapsed reset + probe succeeds -> transitions to AVAILABLE
    async def successful_probe() -> bool:
        return True

    res2 = await service.check_and_probe_provider("antigravity", probe_fn=successful_probe)
    assert res2
    assert service.get_health("antigravity").status == ProviderHealthStatus.AVAILABLE

    recovered_events = [
        e
        for e in in_memory_uow.events.list_events()
        if e.event_type == EventType.PRIMARY_CAPACITY_RECOVERED
    ]
    assert len(recovered_events) == 1


@pytest.mark.asyncio
async def test_provider_health_transient_failure_threshold(in_memory_uow):
    """Test that transient errors accumulate consecutive failures and trigger temporarily_unavailable at threshold."""
    service = ProviderHealthService(in_memory_uow, failure_threshold=3)

    for i in range(1, 4):
        outcome = NormalizedProviderResult(
            result_class=ProviderResultClass.TRANSIENT_ERROR,
            provider="codex",
            role="implementer",
            summary=f"Transient failure #{i}",
        )
        h = service.record_outcome(outcome)
        assert h.consecutive_failures == i

    assert service.get_health("codex").status == ProviderHealthStatus.TEMPORARILY_UNAVAILABLE

    # Success resets consecutive failures and restores available
    succ_outcome = NormalizedProviderResult(
        result_class=ProviderResultClass.SUCCESS,
        provider="codex",
        role="implementer",
        summary="Success after recovery",
    )
    h_restored = service.record_outcome(succ_outcome)
    assert h_restored.status == ProviderHealthStatus.AVAILABLE
    assert h_restored.consecutive_failures == 0


def test_zero_provider_health_records_does_not_persist(in_memory_uow):
    service = ProviderHealthService(in_memory_uow)
    results = service.list_existing_health()

    assert len(results) >= 2
    for r in results:
        assert r.status == ProviderHealthStatus.UNKNOWN

    # Zero DB rows persisted
    assert len(in_memory_uow.provider_health.list_all()) == 0


def test_missing_provider_health_is_unknown_not_available(in_memory_uow):
    service = ProviderHealthService(in_memory_uow)
    assert service.get_existing_health("codex") is None

    avail, reason = service.is_pair_available("codex", "antigravity")
    assert avail is False
    assert "unknown" in reason.lower() or "codex" in reason.lower()


def test_scheduler_status_pure_with_missing_primary_health_does_not_authorize_admission(
    in_memory_uow,
):
    from minime.domain.enums import SchedulerMode
    from minime.services.capacity_lifecycle_service import CapacityLifecycleService

    capacity_service = CapacityLifecycleService(in_memory_uow)
    status = capacity_service.get_scheduler_status_pure()

    assert status.admission_allowed is False
    assert status.mode in {SchedulerMode.WAIT, SchedulerMode.DRAIN}
    assert status.primary_capacity_available is False


def test_persisted_available_health_authorizes_run(in_memory_uow):
    from minime.domain.enums import SchedulerMode
    from minime.domain.models import ProviderHealth
    from minime.services.capacity_lifecycle_service import CapacityLifecycleService

    for prov in ["codex", "antigravity"]:
        in_memory_uow.provider_health.save(
            ProviderHealth(
                health_id=f"ph-{prov}",
                provider=prov,
                status=ProviderHealthStatus.AVAILABLE,
                updated_at=utc_now(),
            )
        )
    in_memory_uow.commit()

    capacity_service = CapacityLifecycleService(in_memory_uow)
    status = capacity_service.get_scheduler_status_pure()

    assert status.admission_allowed is True
    assert status.mode == SchedulerMode.RUN
    assert status.primary_capacity_available is True
