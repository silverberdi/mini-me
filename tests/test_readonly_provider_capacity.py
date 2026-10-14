import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

import minime.adapters.provider_adapter as provider_adapter
from minime.adapters.provider_adapter import (
    AntigravityProviderAdapter,
    CapacityObservation,
    CodexProviderAdapter,
    FakeProviderAdapter,
    ProviderAdapterInterface,
    get_provider_adapter,
)
from minime.domain.enums import CapacitySignalSource, ProviderHealthStatus
from minime.domain.models import utc_now
from minime.services.provider_health_service import ProviderHealthService


def _codex_result(allowed=True, account_id="test-account"):
    return {
        "accountId": account_id,
        "ordinaryUsageAllowed": allowed,
        "rateLimitsByLimitId": {
            "codex": {
                "limitId": "codex",
                "normalModelSlug": "codex-test-model",
                "primary": {"resetsAt": 1_900_000_000},
            }
        },
    }


@pytest.mark.parametrize(("allowed", "expected"), [(True, True), (False, False)])
def test_codex_app_server_capacity_permission_is_explicit(allowed, expected):
    now = utc_now()
    observation = CodexProviderAdapter.parse_rate_limits_result(
        _codex_result(allowed), observed_at=now, expires_at=now + timedelta(seconds=60)
    )
    assert observation.ordinary_usage_allowed is expected
    assert observation.account_id == "test-account"
    assert observation.model == "codex-test-model"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {**_codex_result(), "ordinaryUsageAllowed": None},
        {**_codex_result(), "accountId": ""},
        {**_codex_result(), "rateLimitsByLimitId": {"other": {"limitId": "other"}}},
    ],
)
def test_codex_capacity_missing_or_wrong_identity_is_unknown(payload):
    now = utc_now()
    observation = CodexProviderAdapter.parse_rate_limits_result(
        payload, observed_at=now, expires_at=now + timedelta(seconds=60)
    )
    assert observation.ordinary_usage_allowed is None
    assert observation.account_id is None


def test_stale_capacity_observation_is_rejected(in_memory_uow):
    service = ProviderHealthService(in_memory_uow)
    old = utc_now() - timedelta(minutes=2)
    observation = CapacityObservation(
        provider="codex",
        ordinary_usage_allowed=True,
        observed_at=old,
        expires_at=old + timedelta(seconds=60),
        source_signal=CapacitySignalSource.CODEX_APP_SERVER,
        account_id="account",
        model="codex-test-model",
    )
    assert service.record_capacity_observation("codex", observation) is False
    assert service.get_admission_health("codex").status == ProviderHealthStatus.UNKNOWN


def test_read_failure_records_unknown_not_permission(in_memory_uow):
    service = ProviderHealthService(in_memory_uow)
    assert service.record_capacity_observation("codex", None) is False
    assert service.get_admission_health("codex").status == ProviderHealthStatus.UNKNOWN


def test_first_valid_capacity_observation_upgrades_new_health_row(
    in_memory_uow, test_capacity_strategy
):
    test_capacity_strategy(("codex",))
    service = ProviderHealthService(in_memory_uow)
    now = utc_now()
    observation = CapacityObservation(
        provider="codex",
        ordinary_usage_allowed=True,
        observed_at=now,
        expires_at=now + timedelta(seconds=30),
        source_signal=CapacitySignalSource.PROVIDER_READ_ONLY_CAPACITY,
        account_id="test-account:codex",
        model="test-model:codex",
    )

    assert service.record_capacity_observation("codex", observation) is True
    assert service.get_admission_health("codex").status == ProviderHealthStatus.AVAILABLE


def test_capacity_identity_mismatch_records_unknown(in_memory_uow):
    service = ProviderHealthService(in_memory_uow)
    now = utc_now()
    observation = CapacityObservation(
        provider="antigravity",
        ordinary_usage_allowed=True,
        observed_at=now,
        expires_at=now + timedelta(seconds=60),
        source_signal=CapacitySignalSource.CODEX_APP_SERVER,
        account_id="account",
        model="codex-model",
    )
    assert service.record_capacity_observation("codex", observation) is False
    assert service.get_admission_health("codex").status == ProviderHealthStatus.UNKNOWN


def test_antigravity_has_no_authorized_capacity_source_yet(in_memory_uow):
    service = ProviderHealthService(in_memory_uow)
    now = utc_now()
    observation = CapacityObservation(
        provider="antigravity",
        ordinary_usage_allowed=True,
        observed_at=now,
        expires_at=now + timedelta(seconds=60),
        source_signal=CapacitySignalSource.CODEX_APP_SERVER,
        account_id="wrong-provider-account",
        model="agy-model",
    )
    assert service.record_capacity_observation("antigravity", observation) is False
    assert service.get_admission_health("antigravity").status == ProviderHealthStatus.UNKNOWN


def _agy_payload(now, *, remaining=0.5, model="Gemini 3.8 Flash (High)", account="a" * 64):
    short_reset = now + timedelta(hours=3)
    week_reset = now + timedelta(days=6)
    return {
        "observed_at": now.isoformat(),
        "version": "1.3.5",
        "product": "antigravity",
        "session_id": "11111111-2222-4333-8444-555555555555",
        "conversation_id": "11111111-2222-4333-8444-555555555555",
        "account_fingerprint": account,
        "model": {"id": model},
        "agent_state": "idle",
        "quota": {
            "gemini-5h": {
                "remaining_fraction": remaining,
                "reset_time": short_reset.isoformat(),
                "reset_in_seconds": 3 * 3600,
            },
            "gemini-weekly": {
                "remaining_fraction": 0.8,
                "reset_time": week_reset.isoformat(),
                "reset_in_seconds": 6 * 24 * 3600,
            },
            # Other-model buckets must not be used for the active Gemini model.
            "3p-5h": {"remaining_fraction": 1},
        },
    }


@pytest.mark.parametrize(("remaining", "expected"), [(0.5, True), (0.0, False)])
def test_agy_statusline_capacity_valid_available_or_exhausted(remaining, expected):
    now = utc_now()
    observation = AntigravityProviderAdapter.parse_statusline_payload(
        _agy_payload(now, remaining=remaining)
    )
    assert observation.provider == "antigravity"
    assert observation.ordinary_usage_allowed is expected
    assert observation.model == "Gemini 3.8 Flash (High)"
    assert observation.source_signal == CapacitySignalSource.AGY_STATUSLINE


@pytest.mark.parametrize(
    "payload",
    [
        _agy_payload(utc_now() - timedelta(minutes=2)),
        _agy_payload(utc_now(), account="wrong"),
        _agy_payload(utc_now(), model="Claude 3.5"),
        {"product": "antigravity", "agent_state": "idle"},
        {**_agy_payload(utc_now()), "product": "other"},
    ],
)
def test_agy_statusline_stale_wrong_identity_or_absent_is_unknown(payload):
    observation = AntigravityProviderAdapter.parse_statusline_payload(payload)
    assert observation.ordinary_usage_allowed is None


def test_agy_statusline_requires_consistent_session_identity():
    now = utc_now()
    missing = _agy_payload(now)
    missing.pop("session_id")
    contradictory = _agy_payload(now)
    contradictory["conversation_id"] = "another-session"
    for payload in (missing, contradictory):
        observation = AntigravityProviderAdapter.parse_statusline_payload(payload)
        assert observation.ordinary_usage_allowed is None


def test_agy_callback_must_be_correlated_to_observer_process():
    base = _agy_payload(utc_now())
    base["callback_pid"] = 9010
    base["callback_parent_pid"] = 9001
    base["cwd"] = "/tmp/observer-unique"
    base["workspace"] = {
        "current_dir": "/tmp/observer-unique",
        "project_dir": "/tmp/observer-unique",
    }
    assert AntigravityProviderAdapter._statusline_callback_matches_observer(
        base, 9001, "/tmp/observer-unique"
    )
    assert not AntigravityProviderAdapter._statusline_callback_matches_observer(
        base, 6774, "/tmp/other-observer"
    )
    base["conversation_id"] = "other-session"
    assert not AntigravityProviderAdapter._statusline_callback_matches_observer(
        base, 9001, "/tmp/observer-unique"
    )


@pytest.mark.asyncio
async def test_registered_third_provider_capacity_strategy_needs_no_scheduler_change(monkeypatch):
    class ThirdPartyCapacityAdapter(ProviderAdapterInterface):
        @property
        def provider_name(self):
            return "r01-third-party"

        @property
        def supported_roles(self):
            return {"implementer"}

        @property
        def supports_read_only_capacity_observation(self):
            return True

        @property
        def capacity_source_signal(self):
            return CapacitySignalSource.PROVIDER_READ_ONLY_CAPACITY

        @property
        def requires_account_identity_for_capacity(self):
            return True

        async def check_cli_present(self):
            return True

        async def check_auth_ready(self, timeout_seconds=10.0):
            del timeout_seconds
            return True

        async def probe_availability(self, timeout_seconds=30.0):
            del timeout_seconds
            raise AssertionError("capacity must not be inferred by a provider turn")

        async def read_capacity_observation(self, timeout_seconds=10.0):
            del timeout_seconds
            now = utc_now()
            return CapacityObservation(
                provider=self.provider_name,
                ordinary_usage_allowed=True,
                observed_at=now,
                expires_at=now + timedelta(seconds=30),
                source_signal=self.capacity_source_signal,
                account_id="third-party-account",
                model="third-party-model",
            )

    adapter = ThirdPartyCapacityAdapter()
    monkeypatch.setitem(provider_adapter._ADAPTER_REGISTRY, adapter.provider_name, adapter)
    assert get_provider_adapter(adapter.provider_name) is adapter
    observation = await adapter.read_capacity_observation()
    assert observation.provider == adapter.provider_name
    assert observation.ordinary_usage_allowed is True
    assert observation.source_signal == CapacitySignalSource.PROVIDER_READ_ONLY_CAPACITY


def test_unknown_provider_has_no_fake_operational_fallback():
    with pytest.raises(ValueError, match="No operational provider adapter registered"):
        get_provider_adapter("r01-unregistered-provider")


def test_fake_adapter_registration_is_restricted_to_test_processes(monkeypatch):
    adapter = FakeProviderAdapter(name="r01-test-only-provider", available=True)
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    with pytest.raises(RuntimeError, match="restricted to test processes"):
        provider_adapter.register_provider_adapter(adapter)


@pytest.mark.asyncio
async def test_agy_statusline_timeout_returns_unknown_and_restores_settings(tmp_path, monkeypatch):
    settings_dir = tmp_path / ".gemini" / "antigravity-cli"
    settings_dir.mkdir(parents=True)
    settings_path = settings_dir / "settings.json"
    original = b'{"model":"Gemini 3.8 Flash (High)"}\n'
    settings_path.write_bytes(original)
    settings_path.chmod(0o600)
    settings_dir.chmod(0o700)
    gemini_dir = settings_dir.parent
    gemini_dir.chmod(0o700)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    class HangingTui:
        def __init__(self):
            self.returncode = None
            self.pid = 54321

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    async def fake_create_subprocess_exec(*args, **kwargs):
        del args, kwargs
        return HangingTui()

    adapter = AntigravityProviderAdapter()
    monkeypatch.setattr(adapter, "_resolve_executable", lambda: "/usr/bin/agy")
    monkeypatch.setattr(
        "minime.adapters.provider_adapter.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    observation = await adapter.read_capacity_observation(timeout_seconds=0.05)
    assert observation.ordinary_usage_allowed is None
    assert settings_path.read_bytes() == original
    assert json.loads(settings_path.read_text()) == {"model": "Gemini 3.8 Flash (High)"}


@pytest.mark.asyncio
async def test_agy_statusline_accepts_only_its_own_callback_with_other_sessions_present(
    tmp_path, monkeypatch
):
    settings_dir = tmp_path / ".gemini" / "antigravity-cli"
    settings_dir.mkdir(parents=True)
    settings_path = settings_dir / "settings.json"
    original = b'{"model":"Gemini 3.8 Flash (High)"}\n'
    settings_path.write_bytes(original)
    settings_path.chmod(0o600)
    settings_dir.chmod(0o700)
    settings_dir.parent.chmod(0o700)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    now = utc_now()

    class ControlledObserver:
        returncode = None
        pid = 54321

        def terminate(self):
            self.returncode = -15

        async def wait(self):
            return self.returncode

    async def fake_create_subprocess_exec(*args, **kwargs):
        assert args == ("/usr/bin/agy",)
        observer_cwd = kwargs["cwd"]
        assert Path(observer_cwd).name.startswith("minime-agy-capacity-")
        assert Path(observer_cwd).stat().st_mode & 0o777 == 0o700
        # Simulate a callback from an unrelated pre-existing AGY session first.
        config = json.loads(settings_path.read_text())
        command = Path(config["statusLine"]["command"])
        snapshot = command.parent / "snapshot.json"
        foreign = _agy_payload(now)
        foreign.update(
            callback_pid=6775,
            callback_parent_pid=6774,
            cwd="/Users/operator/project",
            workspace={
                "current_dir": "/Users/operator/project",
                "project_dir": "/Users/operator/project",
            },
        )
        (command.parent / "snapshot.json-6775").write_text(json.dumps(foreign))
        # Then the controlled TUI emits its own callback. The adapter must select
        # this process-correlated payload without a global pgrep exclusion.
        own = _agy_payload(now)
        own.update(
            callback_pid=54322,
            callback_parent_pid=54321,
            cwd=observer_cwd,
            workspace={"current_dir": observer_cwd, "project_dir": observer_cwd},
        )
        (command.parent / "snapshot.json-54322").write_text(json.dumps(own))
        assert snapshot.parent == command.parent
        return ControlledObserver()

    adapter = AntigravityProviderAdapter()
    monkeypatch.setattr(adapter, "_resolve_executable", lambda: "/usr/bin/agy")
    monkeypatch.setattr(
        "minime.adapters.provider_adapter.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    observation = await adapter._read_statusline_snapshot("/usr/bin/agy", timeout_seconds=0.2)
    assert observation.ordinary_usage_allowed is True
    assert observation.source_session_id == "11111111-2222-4333-8444-555555555555"
    assert settings_path.read_bytes() == original


def test_capacity_event_persists_only_session_fingerprint(in_memory_uow):
    service = ProviderHealthService(in_memory_uow)
    now = utc_now()
    observation = CapacityObservation(
        provider="antigravity",
        ordinary_usage_allowed=True,
        observed_at=now,
        expires_at=now + timedelta(seconds=30),
        source_signal=CapacitySignalSource.AGY_STATUSLINE,
        account_id="account-fingerprint",
        model="Gemini test model",
        source_session_id="controlled-session-id",
    )
    assert service.record_capacity_observation("antigravity", observation)
    event = in_memory_uow.events.list_events(limit=1)[0]
    assert (
        event.payload["source_session_fingerprint"]
        == hashlib.sha256(b"controlled-session-id").hexdigest()
    )
    assert "source_session_id" not in event.payload


def _print_usage_data(remaining_5h=0.9, remaining_weekly=0.98, status="SUCCESS", num_turns=0):
    return {
        "status": status,
        "num_turns": num_turns,
        "usage": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0},
        "command": {
            "name": "usage",
            "data": {
                "groups": [
                    {
                        "name": "Gemini Models",
                        "buckets": [
                            {
                                "id": "gemini-5h",
                                "name": "Five Hour Limit Remaining",
                                "remaining_fraction": remaining_5h,
                                "reset_time": "2026-10-14T20:18:26Z",
                            },
                            {
                                "id": "gemini-weekly",
                                "name": "Weekly Limit Remaining",
                                "remaining_fraction": remaining_weekly,
                                "reset_time": "2026-10-21T15:06:49Z",
                            },
                        ],
                    }
                ]
            },
        },
    }


@pytest.mark.parametrize(
    ("r5h", "r_week", "expected"),
    [
        (0.9, 0.98, True),
        (0.0, 0.98, False),
        (0.5, 0.0, False),
    ],
)
def test_parse_print_usage_payload_available_and_exhausted(r5h, r_week, expected):
    account = "f" * 64
    payload = _print_usage_data(remaining_5h=r5h, remaining_weekly=r_week)
    obs = AntigravityProviderAdapter.parse_print_usage_payload(payload, account_fingerprint=account)
    assert obs.ordinary_usage_allowed is expected
    assert obs.source_signal == CapacitySignalSource.AGY_PRINT_USAGE
    assert obs.account_id == account
    assert obs.model == "Gemini Models"


@pytest.mark.parametrize(
    "bad_payload",
    [
        _print_usage_data(status="FAILURE"),
        _print_usage_data(num_turns=1),
        {**_print_usage_data(), "command": {"name": "other"}},
        {**_print_usage_data(), "usage": {"total_tokens": 50}},
        {"status": "SUCCESS"},
        {},
    ],
)
def test_parse_print_usage_payload_malformed_or_inferential_is_unknown(bad_payload):
    account = "f" * 64
    obs = AntigravityProviderAdapter.parse_print_usage_payload(
        bad_payload, account_fingerprint=account
    )
    assert obs.ordinary_usage_allowed is None


def test_parse_print_usage_payload_requires_valid_account_fingerprint():
    payload = _print_usage_data()
    for bad_account in (None, "", "not-64-chars", "z" * 64):
        obs = AntigravityProviderAdapter.parse_print_usage_payload(
            payload, account_fingerprint=bad_account
        )
        assert obs.ordinary_usage_allowed is None


@pytest.mark.asyncio
async def test_read_print_usage_snapshot_mocked_success(monkeypatch):
    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (
                json.dumps(_print_usage_data(0.8, 0.95)).encode(),
                b"",
            )

    async def fake_exec(*args, **kwargs):
        # Write mock log to log-file path
        for i, a in enumerate(args):
            if a == "--log-file" and i + 1 < len(args):
                Path(args[i + 1]).write_text(
                    "I1014 14:20:00 server_oauth.go:204] applyAuthResult: email=tester@example.com\n"
                )
        return FakeProc()

    adapter = AntigravityProviderAdapter()
    monkeypatch.setattr(
        "minime.adapters.provider_adapter.asyncio.create_subprocess_exec", fake_exec
    )
    obs = await adapter._read_print_usage_snapshot("/usr/bin/agy", timeout_seconds=2.0)
    assert obs.ordinary_usage_allowed is True
    assert obs.source_signal == CapacitySignalSource.AGY_PRINT_USAGE
    expected_hash = hashlib.sha256(b"tester@example.com").hexdigest()
    assert obs.account_id == expected_hash


@pytest.mark.asyncio
async def test_read_print_usage_snapshot_nonzero_exit_returns_unknown(monkeypatch):
    class FakeProc:
        returncode = 1

        async def communicate(self):
            return b"", b"CLI error"

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    adapter = AntigravityProviderAdapter()
    monkeypatch.setattr(
        "minime.adapters.provider_adapter.asyncio.create_subprocess_exec", fake_exec
    )
    obs = await adapter._read_print_usage_snapshot("/usr/bin/agy", timeout_seconds=2.0)
    assert obs.ordinary_usage_allowed is None
