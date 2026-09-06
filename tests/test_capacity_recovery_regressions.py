"""Recovery requires positive evidence even when reset metadata is absent or elapsed."""

from datetime import timedelta
from unittest.mock import Mock

import pytest

from minime.domain.enums import (
    EventType,
    OrchestrationStopOutcome,
    ProviderHealthStatus,
    ProviderResultClass,
)
from minime.domain.models import (
    CapacityWindow,
    NormalizedProviderResult,
    OrchestrationRun,
    Project,
    utc_now,
)
from minime.services.provider_health_service import ProviderHealthService
from minime.services.scheduler_service import SchedulerService


@pytest.mark.parametrize("provider", ["codex", "antigravity"])
@pytest.mark.parametrize("success", [False, True])
async def test_unknown_reset_allows_probe(in_memory_uow, provider, success):
    service = ProviderHealthService(in_memory_uow)
    service.record_outcome(
        NormalizedProviderResult(
            provider=provider,
            role="implementer",
            result_class=ProviderResultClass.RATE_LIMIT,
            summary="Capacity unavailable; reset unknown",
        )
    )
    assert in_memory_uow.capacity_windows.get_latest_for_provider(provider) is not None

    async def probe():
        return success

    assert await service.check_and_probe_provider(provider, probe) is success
    expected = (
        ProviderHealthStatus.AVAILABLE if success else ProviderHealthStatus.TEMPORARILY_UNAVAILABLE
    )
    assert service.get_health(provider).status == expected
    event_type = (
        EventType.PRIMARY_CAPACITY_RECOVERED if success else EventType.PROVIDER_PROBE_FAILED
    )
    assert any(e.event_type == event_type for e in in_memory_uow.events.list_events())
    assert in_memory_uow.jobs.list_active_jobs() == []
    assert in_memory_uow.orchestration_runs.list_runs() == []


async def test_probe_timeout_preserves_unavailability(in_memory_uow, monkeypatch):
    service = ProviderHealthService(in_memory_uow)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex",
            role="implementer",
            result_class=ProviderResultClass.RATE_LIMIT,
        )
    )

    async def probe():
        return True

    async def timeout(awaitable, *, timeout):
        assert 0 < timeout <= 30
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("minime.services.provider_health_service.asyncio.wait_for", timeout)
    assert not await service.check_and_probe_provider("codex", probe)
    assert service.get_health("codex").status == ProviderHealthStatus.TEMPORARILY_UNAVAILABLE
    assert any(
        e.event_type == EventType.PROVIDER_PROBE_FAILED for e in in_memory_uow.events.list_events()
    )


@pytest.mark.parametrize("provider", ["codex", "antigravity"])
def test_elapsed_reset_does_not_restore_capacity(in_memory_uow, tmp_path, provider):
    in_memory_uow.projects.save(
        Project(
            project_id="test",
            display_name="Test",
            repository="owner/test",
        )
    )
    service = ProviderHealthService(in_memory_uow)
    service.record_outcome(
        NormalizedProviderResult(
            provider=provider,
            role="implementer",
            result_class=ProviderResultClass.QUOTA_LIMIT,
        )
    )
    in_memory_uow.capacity_windows.save(
        CapacityWindow(
            provider=provider,
            capacity_reset_at=utc_now() - timedelta(minutes=1),
        )
    )
    run = OrchestrationRun(
        project_id="test",
        change_name="capacity-recovery",
        base_sha="a" * 40,
        stop_outcome=OrchestrationStopOutcome.WAITING_CAPACITY,
        stop_details={"provider": provider, "waiting_since": utc_now().isoformat()},
        is_active=True,
    )
    in_memory_uow.orchestration_runs.save(run)
    orchestration = Mock()
    scheduler = SchedulerService(
        in_memory_uow,
        project_root=tmp_path,
        orchestration_service=orchestration,
    )
    assert scheduler.reconcile_waiting_runs() == []
    orchestration.resume.assert_not_called()
    assert service.get_health(provider).status == ProviderHealthStatus.EXHAUSTED
