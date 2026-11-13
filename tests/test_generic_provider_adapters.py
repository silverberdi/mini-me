"""Unit tests for generic provider adapters and capacity recovery probing."""

from datetime import datetime, timezone

import pytest

from minime.adapters.provider_adapter import (
    FakeProviderAdapter,
    get_provider_adapter,
    register_provider_adapter,
)
from minime.config import ProbeConfig
from minime.domain.enums import (
    CapacitySignalSource,
    ProviderHealthStatus,
    ProviderResultClass,
)
from minime.domain.models import (
    NormalizedProviderResult,
    OrchestrationRun,
    Project,
    ProviderHealth,
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
    health_svc = ProviderHealthService(
        in_memory_uow,
        probe_config=ProbeConfig(
            cooldown_seconds=0, backoff_base_seconds=0, backoff_max_seconds=0, max_per_hour=100
        ),
    )

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


def test_capacity_lifecycle_selects_fallback_for_apply_without_reviewer_exhaustion(in_memory_uow):
    from datetime import timedelta

    from minime.domain.enums import OrchestrationStage
    from minime.domain.models import utc_now
    from minime.services.capacity_lifecycle_service import CapacityLifecycleService

    now = utc_now()
    project = Project(
        project_id="test-proj",
        display_name="Test",
        repository="owner/repo",
        implementer="codex",
        reviewer="antigravity",
        agent_profiles={
            "fallback": {
                "harness_id": "opencode",
                "provider_id": "openrouter",
                "model_id": "openrouter/deepseek/deepseek-chat",
            }
        },
    )
    in_memory_uow.projects.save(project)
    in_memory_uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-1",
            project_id="test-proj",
            change_name="change-1",
            base_sha="base-sha",
            current_stage=OrchestrationStage.IMPLEMENTING,
            current_candidate_sha="candidate-sha",
            is_active=True,
        )
    )
    for provider, status, result_class in (
        ("codex", ProviderHealthStatus.EXHAUSTED, ProviderResultClass.QUOTA_LIMIT),
        ("antigravity", ProviderHealthStatus.AVAILABLE, ProviderResultClass.SUCCESS),
    ):
        in_memory_uow.provider_health.save(
            ProviderHealth(
                provider=provider,
                status=status,
                last_result_class=result_class,
                last_failure_at=(now - timedelta(seconds=10)) if status == ProviderHealthStatus.EXHAUSTED else None,
                last_success_at=now if status == ProviderHealthStatus.AVAILABLE else None,
                updated_at=now,
            )
        )

    service = CapacityLifecycleService(in_memory_uow)
    # Apply's execution provider is exhausted; a healthy independent reviewer
    # must not prevent the configured fallback from continuing Apply.
    assert service.fallback_provider_for_inflight_apply("test-proj", "run-1", "codex") == "opencode"
    assert service.fallback_provider_for_inflight_apply("test-proj", "missing-run", "codex") is None

    in_memory_uow.projects.save(project.model_copy(update={"agent_profiles": {}}))
    assert service.fallback_provider_for_inflight_apply("test-proj", "run-1", "codex") is None
    in_memory_uow.projects.save(project)

    in_memory_uow.provider_health.save(
        ProviderHealth(
            provider="codex",
            status=ProviderHealthStatus.AVAILABLE,
            last_result_class=ProviderResultClass.SUCCESS,
            last_success_at=now,
            updated_at=now,
        )
    )
    assert service.can_execute_inflight_apply("test-proj", "run-1", "codex") is True
    assert service.fallback_provider_for_inflight_apply("test-proj", "run-1", "codex") is None

    in_memory_uow.provider_health.save(
        ProviderHealth(
            provider="antigravity",
            status=ProviderHealthStatus.EXHAUSTED,
            last_result_class=ProviderResultClass.QUOTA_LIMIT,
            last_failure_at=now - timedelta(seconds=10),
            updated_at=now,
        )
    )
    # Healthy Apply still stays on the configured execution provider even if
    # the reviewer provider is exhausted.
    assert service.fallback_provider_for_inflight_apply("test-proj", "run-1", "codex") is None


@pytest.mark.asyncio
async def test_opencode_adapter_classifies_model_routes():
    """OpenCode model identities are classified by transport namespace."""
    from minime.adapters.provider_adapter import OpenCodeProviderAdapter

    adapter = OpenCodeProviderAdapter()
    assert adapter._route_for("deepseek/deepseek-v4-pro") == "deepseek_direct"
    assert adapter._route_for("deepseek/deepseek-flash") == "deepseek_direct"
    assert adapter._route_for("openrouter/deepseek/deepseek-v4-pro") == "openrouter"
    assert adapter._route_for("openrouter/~deepseek/deepseek-flash-latest") == "openrouter"
    assert adapter._route_for("opencode/beam-free") == "opencode_native"
    assert adapter._route_for("random/thing") == "unknown"


@pytest.mark.asyncio
async def test_opencode_adapter_discovery_parses_models(monkeypatch, tmp_path):
    """discover_account_capabilities runs `opencode models` and returns models + routes."""
    import asyncio as _asyncio

    from minime.adapters.provider_adapter import OpenCodeProviderAdapter

    adapter = OpenCodeProviderAdapter(executable="/bin/opencode")
    monkeypatch.setattr("minime.adapters.provider_adapter.shutil.which", lambda _: "/bin/opencode")
    monkeypatch.setattr(
        adapter,
        "_get_configured_providers",
        lambda: {"deepseek", "openrouter", "opencode"},
    )

    async def fake_exec(*args, **kwargs):
        class _Proc:
            returncode = 0

            async def communicate(self):
                return (
                    b"deepseek/deepseek-flash\ndeepseek/deepseek-v4-pro\n"
                    b"openrouter/deepseek/deepseek-v4-pro\nopencode/beam-free\n",
                    b"",
                )

        return _Proc()

    monkeypatch.setattr(_asyncio, "create_subprocess_exec", fake_exec)
    caps = await adapter.discover_account_capabilities()
    assert set(caps["models"]) == {
        "deepseek/deepseek-flash",
        "deepseek/deepseek-v4-pro",
        "openrouter/deepseek/deepseek-v4-pro",
        "opencode/beam-free",
    }
    assert caps["model_routes"]["deepseek/deepseek-v4-pro"] == "deepseek_direct"
    assert caps["model_routes"]["openrouter/deepseek/deepseek-v4-pro"] == "openrouter"
    assert caps["model_routes"]["opencode/beam-free"] == "opencode_native"


@pytest.mark.asyncio
async def test_opencode_adapter_check_model_supported(monkeypatch):
    """check_model_supported validates against the discovered catalog."""
    from minime.adapters.provider_adapter import OpenCodeProviderAdapter

    adapter = OpenCodeProviderAdapter()
    adapter._cached_capabilities = {
        "models": {"deepseek/deepseek-v4-pro": None, "openrouter/deepseek/deepseek-v4-pro": None},
        "model_routes": {
            "deepseek/deepseek-v4-pro": "deepseek_direct",
            "openrouter/deepseek/deepseek-v4-pro": "openrouter",
        },
    }
    adapter._capabilities_expires_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ) + __import__("datetime").timedelta(seconds=60)

    ok, _ = await adapter.check_model_supported("deepseek/deepseek-v4-pro")
    assert ok is True
    ok2, reason = await adapter.check_model_supported("deepseek-reasoner")
    assert ok2 is False
    assert "absent" in reason
