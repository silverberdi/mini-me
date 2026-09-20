# Corrective regression tests for the independent Codex review findings (F1-F4).

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from minime.adapters.provider_adapter import (
    AntigravityProviderAdapter,
    CodexProviderAdapter,
    FakeProviderAdapter,
    OpenRouterProviderAdapter,
)
from minime.config import AppConfig, ProbeConfig, ProviderConfig
from minime.domain.enums import (
    ProviderHealthStatus,
    ProviderResultClass,
    QueuePriority,
    ReadinessState,
)
from minime.domain.models import NormalizedProviderResult, Project, WorkQueueItem, utc_now
from minime.services.provider_health_service import ProviderHealthService


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds: int):
        self.now = self.now + timedelta(seconds=seconds)


class _ExpensiveFake(FakeProviderAdapter):
    @property
    def probe_is_expensive(self):
        return True


def _proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    proc = AsyncMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    return proc


# ---------------------------------------------------------------------------
# Finding 1: concurrent expensive probes must not burst past cooldown/backoff.
# ---------------------------------------------------------------------------
async def test_concurrent_expensive_probes_serialized_at_cooldown_boundary(
    in_memory_uow, monkeypatch
):
    clock = _Clock()
    monkeypatch.setattr("minime.services.provider_health_service.utc_now", clock)
    # Seed actionable READY work queue item so expensive probe is eligible under current governance contract
    p = Project(project_id="test-p", display_name="Test", repository="owner/repo", implementer="codex")
    in_memory_uow.projects.save(p)
    w = WorkQueueItem(
        project_id="test-p",
        change_name="test-c",
        priority=QueuePriority.NORMAL,
        readiness_state=ReadinessState.READY,
        discovered_at=utc_now(),
    )
    in_memory_uow.work_queue.save(w)
    cfg = ProbeConfig(
        cooldown_seconds=60,
        backoff_base_seconds=60,
        backoff_max_seconds=240,
        max_per_hour=100,  # high enough that the rate window is not the limiter
    )
    service = ProviderHealthService(in_memory_uow, probe_config=cfg)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex", role="implementer", result_class=ProviderResultClass.QUOTA_LIMIT
        )
    )
    adapter = _ExpensiveFake(name="codex", available=False)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: adapter
    )
    clock.advance(60)  # cross the cooldown boundary: first probe becomes eligible

    async def one_call() -> bool:
        return await service.check_and_probe_provider("codex")

    results = await asyncio.gather(*(one_call() for _ in range(20)))
    # Only ONE probe may dispatch at the cooldown boundary. Every queued caller
    # must observe the durably reserved dispatch time and fail the cooldown check.
    assert adapter.probe_call_count == 1
    assert results == [False] * 20


# ---------------------------------------------------------------------------
# Finding 2: a cheap auth/catalog readiness signal must NOT prove recovered
# inference capacity for an exhausted provider.
# ---------------------------------------------------------------------------
def test_probe_verifies_capacity_flags():
    assert CodexProviderAdapter(executable="codex").probe_verifies_capacity is True
    assert AntigravityProviderAdapter(executable="agy").probe_verifies_capacity is False
    assert OpenRouterProviderAdapter().probe_verifies_capacity is False
    assert FakeProviderAdapter(name="x").probe_verifies_capacity is True


async def test_exhausted_antigravity_models_success_stays_exhausted(in_memory_uow, monkeypatch):
    service = ProviderHealthService(
        in_memory_uow,
        probe_config=ProbeConfig(
            cooldown_seconds=0, backoff_base_seconds=0, backoff_max_seconds=0
        ),
    )
    service.record_outcome(
        NormalizedProviderResult(
            provider="antigravity",
            role="implementer",
            result_class=ProviderResultClass.QUOTA_LIMIT,
            summary="Quota exhausted",
        )
    )
    assert service.get_health("antigravity").status == ProviderHealthStatus.EXHAUSTED

    agy = AntigravityProviderAdapter(executable="agy")
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter", lambda p: agy
    )
    with patch("shutil.which", return_value="/usr/local/bin/agy"):
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_proc(stdout=b"Models: gemini-2.5-pro", returncode=0),
        ):
            ok = await service.check_and_probe_provider("antigravity")

    # `agy models` succeeded (auth/catalog reachable) but does NOT verify inference
    # capacity recovery, so the provider must remain exhausted.
    assert ok is False
    assert service.get_health("antigravity").status == ProviderHealthStatus.EXHAUSTED


# ---------------------------------------------------------------------------
# Finding 3: operator YAML probe config must reach the runtime service.
# ---------------------------------------------------------------------------
def test_service_derives_probe_configs_from_app_config(in_memory_uow, monkeypatch):
    app = AppConfig(
        providers={
            "codex": ProviderConfig(command="codex", probe=ProbeConfig(cooldown_seconds=123)),
            "antigravity": ProviderConfig(
                command="agy", probe=ProbeConfig(cooldown_seconds=456)
            ),
        }
    )
    monkeypatch.setattr("minime.services.provider_health_service.load_config", lambda: app)
    service = ProviderHealthService(in_memory_uow)
    assert service.probe_configs["codex"].cooldown_seconds == 123
    assert service.probe_configs["antigravity"].cooldown_seconds == 456
    assert service._probe_config("codex").cooldown_seconds == 123


def test_explicit_probe_config_suppresses_app_config_loading(in_memory_uow, monkeypatch):
    def boom():
        raise AssertionError("load_config must not be called when probe_config is explicit")

    monkeypatch.setattr("minime.services.provider_health_service.load_config", boom)
    service = ProviderHealthService(
        in_memory_uow, probe_config=ProbeConfig(cooldown_seconds=7)
    )
    assert service.probe_configs == {}
    assert service._probe_config("codex").cooldown_seconds == 7
