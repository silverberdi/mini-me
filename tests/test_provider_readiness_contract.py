# Focused Task Group 2 tests for the readiness/capacity separation contract.
#
# A readiness check must never consume model inference quota. A capacity probe is a
# separate, explicit operation whose governance lands in Task Groups 3-4.

from unittest.mock import AsyncMock, patch

from minime.adapters.provider_adapter import (
    AntigravityProviderAdapter,
    CodexProviderAdapter,
    DeepSeekProviderAdapter,
    FakeProviderAdapter,
    OpenRouterProviderAdapter,
)
from minime.config import ProbeConfig
from minime.domain.enums import ProviderHealthStatus, ProviderResultClass
from minime.domain.models import NormalizedProviderResult
from minime.services.provider_health_service import ProviderHealthService


def _proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    proc = AsyncMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    return proc


async def test_codex_check_cli_present_false_when_executable_missing():
    adapter = CodexProviderAdapter(executable="codex")
    with patch("shutil.which", return_value=None):
        assert await adapter.check_cli_present() is False


async def test_codex_check_cli_present_true_when_executable_resolves():
    adapter = CodexProviderAdapter(executable="codex")
    with patch("shutil.which", return_value="/usr/local/bin/codex"):
        assert await adapter.check_cli_present() is True


async def test_codex_check_auth_ready_uses_login_status_not_exec():
    adapter = CodexProviderAdapter(executable="codex")
    spawned = []

    async def fake_exec(*args, **kwargs):
        spawned.append(args)
        return _proc(stdout=b"Logged in using ChatGPT", returncode=0)

    with patch("shutil.which", return_value="/usr/local/bin/codex"):
        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec) as exec_mock:
            assert await adapter.check_auth_ready() is True
            assert exec_mock.await_count == 1
            argv = spawned[0]
            assert argv[0] == "/usr/local/bin/codex"
            assert list(argv[1:3]) == ["login", "status"]
            assert "exec" not in argv


async def test_codex_check_auth_ready_false_when_not_logged_in():
    adapter = CodexProviderAdapter(executable="codex")
    with patch("shutil.which", return_value="/usr/local/bin/codex"):
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_proc(stderr=b"Error: not logged in. Run codex login.", returncode=1),
        ) as exec_mock:
            assert await adapter.check_auth_ready() is False
            assert exec_mock.await_count == 1


async def test_codex_check_auth_ready_false_when_executable_missing():
    adapter = CodexProviderAdapter(executable="codex")
    with patch("shutil.which", return_value=None):
        assert await adapter.check_auth_ready() is False


def test_codex_capacity_probe_is_classified_expensive():
    assert CodexProviderAdapter(executable="codex").probe_is_expensive is True


async def test_antigravity_check_cli_present_false_when_executable_missing():
    adapter = AntigravityProviderAdapter(executable="agy")
    with patch("shutil.which", return_value=None):
        assert await adapter.check_cli_present() is False


async def test_antigravity_auth_readiness_uses_models_not_inference():
    adapter = AntigravityProviderAdapter(executable="agy")
    spawned = []

    async def fake_exec(*args, **kwargs):
        spawned.append(args)
        return _proc(stdout=b"Models: gemini-2.5-pro", returncode=0)

    with patch("shutil.which", return_value="/usr/local/bin/agy"):
        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec) as exec_mock:
            assert await adapter.check_auth_ready() is True
            assert exec_mock.await_count == 1
            argv = spawned[0]
            assert argv[0] == "/usr/local/bin/agy"
            assert list(argv[1:]) == ["models"]


async def test_antigravity_auth_readiness_false_when_sign_in_required():
    adapter = AntigravityProviderAdapter(executable="agy")
    with patch("shutil.which", return_value="/usr/local/bin/agy"):
        with patch(
            "asyncio.create_subprocess_exec",
            return_value=_proc(
                stderr=b"Error: Please sign in to view available models.", returncode=1
            ),
        ):
            assert await adapter.check_auth_ready() is False


def test_antigravity_capacity_probe_is_not_classified_expensive():
    assert AntigravityProviderAdapter(executable="agy").probe_is_expensive is False


async def test_openrouter_auth_ready_reflects_api_key_without_request(monkeypatch):
    adapter = OpenRouterProviderAdapter(
        base_url="https://openrouter.example.test", api_key_env="MINIME_TEST_OR_KEY"
    )
    monkeypatch.delenv("MINIME_TEST_OR_KEY", raising=False)
    assert await adapter.check_auth_ready() is False
    monkeypatch.setenv("MINIME_TEST_OR_KEY", "sk-test")
    assert await adapter.check_auth_ready() is True


async def test_deepseek_auth_ready_reflects_api_key_without_request(monkeypatch):
    adapter = DeepSeekProviderAdapter(
        base_url="https://api.deepseek.test", api_key_env="MINIME_TEST_DS_KEY"
    )
    monkeypatch.delenv("MINIME_TEST_DS_KEY", raising=False)
    assert await adapter.check_auth_ready() is False
    monkeypatch.setenv("MINIME_TEST_DS_KEY", "ds-test")
    assert await adapter.check_auth_ready() is True


async def test_fake_provider_retains_default_ready_readiness():
    adapter = FakeProviderAdapter(name="cursor", available=True)
    assert await adapter.check_cli_present() is True
    assert await adapter.check_auth_ready() is True
    assert adapter.probe_is_expensive is False



async def test_health_gate_missing_cli_marks_misconfigured_without_probe(in_memory_uow, monkeypatch):
    service = ProviderHealthService(in_memory_uow)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex",
            role="implementer",
            result_class=ProviderResultClass.QUOTA_LIMIT,
            summary="Quota exhausted; reset unknown",
        )
    )
    codex_adapter = CodexProviderAdapter(executable="codex")
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter",
        lambda provider: codex_adapter,
    )
    with patch("shutil.which", return_value=None):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as exec_mock:
            result = await service.check_and_probe_provider("codex")
    assert result is False
    assert service.get_health("codex").status == ProviderHealthStatus.MISCONFIGURED
    exec_mock.assert_not_awaited()


async def test_health_gate_auth_failure_marks_auth_required_without_probe(in_memory_uow, monkeypatch):
    service = ProviderHealthService(in_memory_uow)
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex",
            role="implementer",
            result_class=ProviderResultClass.RATE_LIMIT,
            summary="Rate limited",
        )
    )
    codex_adapter = CodexProviderAdapter(executable="codex")
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter",
        lambda provider: codex_adapter,
    )
    spawned = []

    async def fake_exec(*args, **kwargs):
        spawned.append(args)
        return _proc(stderr=b"Not logged in", returncode=1)

    with patch("shutil.which", return_value="/usr/local/bin/codex"):
        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await service.check_and_probe_provider("codex")
    assert result is False
    assert service.get_health("codex").status == ProviderHealthStatus.AUTH_REQUIRED
    assert len(spawned) == 1
    assert list(spawned[0][1:3]) == ["login", "status"]
    assert "exec" not in spawned[0]


async def test_health_gate_passes_and_capacity_probe_remains_separate_operation(
    in_memory_uow, monkeypatch
):
    service = ProviderHealthService(
        in_memory_uow,
        probe_config=ProbeConfig(
            cooldown_seconds=0, backoff_base_seconds=0, backoff_max_seconds=0
        ),
    )
    service.record_outcome(
        NormalizedProviderResult(
            provider="codex",
            role="implementer",
            result_class=ProviderResultClass.RATE_LIMIT,
            summary="Rate limited",
        )
    )
    fake = FakeProviderAdapter(name="codex", available=True)
    monkeypatch.setattr(
        "minime.services.provider_health_service.get_provider_adapter",
        lambda provider: fake,
    )
    ok = await service.check_and_probe_provider("codex")
    assert ok is True
    assert fake.probe_call_count == 1
    assert service.get_health("codex").status == ProviderHealthStatus.AVAILABLE
