# Corrective regression tests for the independent Codex review findings (F1-F4).

from __future__ import annotations

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
)
from minime.domain.models import NormalizedProviderResult
from minime.services.provider_health_service import ProviderHealthService


def _proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    proc = AsyncMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    return proc


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
        probe_config=ProbeConfig(cooldown_seconds=0, backoff_base_seconds=0, backoff_max_seconds=0),
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
            "antigravity": ProviderConfig(command="agy", probe=ProbeConfig(cooldown_seconds=456)),
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
    service = ProviderHealthService(in_memory_uow, probe_config=ProbeConfig(cooldown_seconds=7))
    assert service.probe_configs == {}
    assert service._probe_config("codex").cooldown_seconds == 7
