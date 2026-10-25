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
from minime.domain.enums import CapacitySignalSource, EventType, ProviderHealthStatus
from minime.domain.models import Event, utc_now
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


def test_codex_null_normal_model_requires_separate_capability_evidence():
    now = utc_now()
    payload = _codex_result()
    payload["rateLimitsByLimitId"]["codex"]["normalModelSlug"] = None
    unknown = CodexProviderAdapter.parse_rate_limits_result(
        payload,
        observed_at=now,
        expires_at=now + timedelta(seconds=60),
        selected_model="gpt-5.6-luna",
    )
    assert unknown.ordinary_usage_allowed is None

    verified = CodexProviderAdapter.parse_rate_limits_result(
        payload,
        observed_at=now,
        expires_at=now + timedelta(seconds=60),
        selected_model="gpt-5.6-luna",
        model_capability_verified=True,
    )
    assert verified.ordinary_usage_allowed is True
    assert verified.model == "gpt-5.6-luna"


@pytest.mark.asyncio
async def test_codex_capacity_reads_model_catalog_before_generic_bucket(monkeypatch):
    adapter = CodexProviderAdapter()
    payload = _codex_result()
    payload["rateLimitsByLimitId"]["codex"]["normalModelSlug"] = None

    async def app_server(method, params=None, timeout_seconds=10.0):
        del params, timeout_seconds
        if method == "model/list":
            return {
                "data": [
                    {
                        "id": "gpt-5.6-luna",
                        "supportedReasoningEfforts": [{"reasoningEffort": "medium"}],
                    }
                ]
            }
        assert method == "account/rateLimits/read"
        return payload

    monkeypatch.setattr(adapter, "_call_app_server_method", app_server)
    observation = await adapter.read_capacity_observation(
        selected_model="gpt-5.6-luna"
    )
    assert observation.ordinary_usage_allowed is True
    assert observation.model == "gpt-5.6-luna"


@pytest.mark.asyncio
async def test_codex_capacity_stays_unknown_when_selected_model_is_absent(monkeypatch):
    adapter = CodexProviderAdapter()

    async def app_server(method, params=None, timeout_seconds=10.0):
        del params, timeout_seconds
        if method == "model/list":
            return {"data": [{"id": "other-model"}]}
        raise AssertionError("rate limits must not be read after failed model preflight")

    monkeypatch.setattr(adapter, "_call_app_server_method", app_server)
    observation = await adapter.read_capacity_observation(
        selected_model="gpt-5.6-luna"
    )
    assert observation.ordinary_usage_allowed is None


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


@pytest.mark.asyncio
async def test_first_adapter_acquired_capacity_observation_upgrades_new_health_row(
    in_memory_uow, test_capacity_strategy
):
    test_capacity_strategy(("codex",))
    service = ProviderHealthService(in_memory_uow)
    assert await service.refresh_capacity_from_read_only_source("codex") is True
    assert service.get_admission_health("codex").status == ProviderHealthStatus.AVAILABLE
    assert service.has_fresh_capacity_evidence("codex", model="test-model:codex")


def test_plausible_caller_observation_cannot_authorize_capacity(in_memory_uow):
    service = ProviderHealthService(in_memory_uow)
    now = utc_now()
    plausible = CapacityObservation(
        provider="codex",
        ordinary_usage_allowed=True,
        observed_at=now,
        expires_at=now + timedelta(seconds=30),
        source_signal=CapacitySignalSource.CODEX_APP_SERVER,
        account_id="plausible-account",
        model="gpt-5.6-luna",
        quota_scope="codex",
    )

    assert service.record_capacity_observation("codex", plausible) is False
    assert service.get_admission_health("codex").status == ProviderHealthStatus.UNKNOWN
    assert not service.has_fresh_capacity_evidence("codex", model="gpt-5.6-luna")


def test_fabricated_persisted_capacity_event_is_not_a_service_acquisition(in_memory_uow):
    service = ProviderHealthService(in_memory_uow)
    now = utc_now()
    in_memory_uow.events.save(
        Event(
            event_type=EventType.PROVIDER_CAPACITY_OBSERVED,
            payload={
                "provider": "codex",
                "source": CapacitySignalSource.CODEX_APP_SERVER.value,
                "state": "AVAILABLE",
                "ordinary_usage_allowed": True,
                "model": "gpt-5.6-luna",
                "quota_scope": "codex",
                "account_fingerprint": "a" * 64,
                "source_invocation_id": "fabricated-invocation",
                "observed_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=30)).isoformat(),
            },
            timestamp=now,
        )
    )
    in_memory_uow.commit()

    assert not service.has_fresh_capacity_evidence("codex", model="gpt-5.6-luna")


@pytest.mark.asyncio
async def test_capacity_evidence_is_bound_to_selected_model_and_scope(
    in_memory_uow, test_capacity_strategy
):
    test_capacity_strategy(("codex",))
    adapter = get_provider_adapter("codex")
    service = ProviderHealthService(in_memory_uow)

    assert await service.refresh_capacity_from_read_only_source("codex", model="selected-model")
    assert service.has_fresh_capacity_evidence("codex", model="selected-model", quota_scope="codex")
    restarted_service = ProviderHealthService(in_memory_uow)
    assert not restarted_service.has_fresh_capacity_evidence(
        "codex", model="selected-model", quota_scope="codex"
    )
    assert not service.has_fresh_capacity_evidence("codex", model="other-model")
    assert not service.has_fresh_capacity_evidence(
        "codex", model="selected-model", account_fingerprint="b" * 64
    )
    assert not service.has_fresh_capacity_evidence("codex", quota_scope="other-scope")

    persisted = in_memory_uow.events.list_events(limit=1)[0]
    persisted.payload["model"] = "other-model"
    in_memory_uow.events.save(persisted)
    in_memory_uow.commit()
    assert not service.has_fresh_capacity_evidence("codex", model="other-model")

    original_reader = adapter.read_capacity_observation

    async def mismatched_reader(timeout_seconds=10.0, selected_model=None):
        del timeout_seconds, selected_model
        return await original_reader()

    adapter.read_capacity_observation = mismatched_reader
    assert not await service.refresh_capacity_from_read_only_source(
        "codex", model="requested-model"
    )
    assert not service.has_fresh_capacity_evidence("codex", model="requested-model")


@pytest.mark.asyncio
async def test_capacity_reader_failure_cannot_reuse_previous_positive_evidence(
    in_memory_uow, test_capacity_strategy
):
    test_capacity_strategy(("codex",))
    adapter = get_provider_adapter("codex")
    service = ProviderHealthService(in_memory_uow)
    assert await service.refresh_capacity_from_read_only_source("codex", model="gpt-5.6-luna")

    async def timeout(*args, **kwargs):
        raise TimeoutError("read-only source timed out")

    adapter.read_capacity_observation = timeout
    assert not await service.refresh_capacity_from_read_only_source("codex", model="gpt-5.6-luna")
    assert service.get_admission_health("codex").status == ProviderHealthStatus.UNKNOWN
    assert not service.has_fresh_capacity_evidence("codex", model="gpt-5.6-luna")


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
    # statusLine is demoted to informative telemetry: cannot authorize dispatch
    assert not service.record_capacity_observation("antigravity", observation)
    event = in_memory_uow.events.list_events(limit=1)[0]
    assert event.payload["source_session_fingerprint"] is None
    assert "source_session_id" not in event.payload
    assert event.payload["state"] == "UNKNOWN"
    assert event.payload["source"] == CapacitySignalSource.UNKNOWN.value


def _print_usage_data(
    remaining_5h=0.9,
    remaining_weekly=0.98,
    status="SUCCESS",
    num_turns=0,
    reset_5h=None,
    reset_weekly=None,
):
    now = utc_now()
    r_5h_text = reset_5h or (now + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r_week_text = reset_weekly or (now + timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
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
                                "reset_time": r_5h_text,
                            },
                            {
                                "id": "gemini-weekly",
                                "name": "Weekly Limit Remaining",
                                "remaining_fraction": remaining_weekly,
                                "reset_time": r_week_text,
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
                    "I1014 14:20:00 server_oauth.go:204] applyAuthResult: email=tester@example.com, authMethod=consumer\n"
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


# ==============================================================================
# Mandatory 7-Vector Regressions for Antigravity Capacity and Bounded Dispatch
# Vectors:
#   1. incomplete_payload
#   2. forged_or_contradictory_payload
#   3. stale_payload
#   4. unknown_provenance
#   5. identity_and_scope_mismatch
#   6. acquisition_to_dispatch
#   7. valid_signal
# ==============================================================================


def test_agy_regression_vector_1_incomplete_payload():
    """Vector 1: Absent or incomplete data never equates to zero consumption or capacity.

    Without sufficient positive proof of non-inferential capacity, result must be UNKNOWN.
    """
    account = "a" * 64

    # 1.1 Missing num_turns completely
    p1 = _print_usage_data()
    del p1["num_turns"]
    obs1 = AntigravityProviderAdapter.parse_print_usage_payload(p1, account_fingerprint=account)
    assert obs1.ordinary_usage_allowed is None

    # 1.2 None num_turns
    p2 = _print_usage_data()
    p2["num_turns"] = None
    obs2 = AntigravityProviderAdapter.parse_print_usage_payload(p2, account_fingerprint=account)
    assert obs2.ordinary_usage_allowed is None

    # 1.3 Missing usage dict completely
    p3 = _print_usage_data()
    del p3["usage"]
    obs3 = AntigravityProviderAdapter.parse_print_usage_payload(p3, account_fingerprint=account)
    assert obs3.ordinary_usage_allowed is None

    # 1.4 Missing total_tokens in usage
    p4 = _print_usage_data()
    del p4["usage"]["total_tokens"]
    obs4 = AntigravityProviderAdapter.parse_print_usage_payload(p4, account_fingerprint=account)
    assert obs4.ordinary_usage_allowed is None

    # 1.5 Missing input_tokens in usage
    p5 = _print_usage_data()
    del p5["usage"]["input_tokens"]
    obs5 = AntigravityProviderAdapter.parse_print_usage_payload(p5, account_fingerprint=account)
    assert obs5.ordinary_usage_allowed is None

    # 1.6 Missing output_tokens in usage (mandatory non-defaulted field)
    p6 = _print_usage_data()
    del p6["usage"]["output_tokens"]
    obs6 = AntigravityProviderAdapter.parse_print_usage_payload(p6, account_fingerprint=account)
    assert obs6.ordinary_usage_allowed is None

    # 1.7 None output_tokens
    p7 = _print_usage_data()
    p7["usage"]["output_tokens"] = None
    obs7 = AntigravityProviderAdapter.parse_print_usage_payload(p7, account_fingerprint=account)
    assert obs7.ordinary_usage_allowed is None

    # 1.8 Missing command entirely
    p8 = _print_usage_data()
    del p8["command"]
    obs8 = AntigravityProviderAdapter.parse_print_usage_payload(p8, account_fingerprint=account)
    assert obs8.ordinary_usage_allowed is None

    # 1.9 Empty groups
    p9 = _print_usage_data()
    p9["command"]["data"]["groups"] = []
    obs9 = AntigravityProviderAdapter.parse_print_usage_payload(p9, account_fingerprint=account)
    assert obs9.ordinary_usage_allowed is None

    # 1.10 Missing gemini-weekly bucket
    p10 = _print_usage_data()
    p10["command"]["data"]["groups"][0]["buckets"] = [
        b for b in p10["command"]["data"]["groups"][0]["buckets"] if b["id"] == "gemini-5h"
    ]
    obs10 = AntigravityProviderAdapter.parse_print_usage_payload(p10, account_fingerprint=account)
    assert obs10.ordinary_usage_allowed is None

    # 1.11 Missing remaining_fraction in bucket
    p11 = _print_usage_data()
    del p11["command"]["data"]["groups"][0]["buckets"][0]["remaining_fraction"]
    obs11 = AntigravityProviderAdapter.parse_print_usage_payload(p11, account_fingerprint=account)
    assert obs11.ordinary_usage_allowed is None

    # 1.12 Missing reset_time in bucket
    p12 = _print_usage_data()
    del p12["command"]["data"]["groups"][0]["buckets"][0]["reset_time"]
    obs12 = AntigravityProviderAdapter.parse_print_usage_payload(p12, account_fingerprint=account)
    assert obs12.ordinary_usage_allowed is None


def test_agy_regression_vector_2_forged_or_contradictory_payload():
    """Vector 2: Forged, contradictory, or non-zero inferential payloads fail closed."""
    account = "b" * 64

    # 2.1 Non-zero turns (inferential run)
    p1 = _print_usage_data(num_turns=1)
    obs1 = AntigravityProviderAdapter.parse_print_usage_payload(p1, account_fingerprint=account)
    assert obs1.ordinary_usage_allowed is None

    # 2.2 Boolean num_turns (True/False should not be accepted as integer 0/1)
    p2 = _print_usage_data()
    p2["num_turns"] = False
    obs2 = AntigravityProviderAdapter.parse_print_usage_payload(p2, account_fingerprint=account)
    assert obs2.ordinary_usage_allowed is None

    # 2.3 Non-zero total_tokens
    p3 = _print_usage_data()
    p3["usage"]["total_tokens"] = 100
    obs3 = AntigravityProviderAdapter.parse_print_usage_payload(p3, account_fingerprint=account)
    assert obs3.ordinary_usage_allowed is None

    # 2.4 Non-zero input_tokens
    p4 = _print_usage_data()
    p4["usage"]["input_tokens"] = 50
    obs4 = AntigravityProviderAdapter.parse_print_usage_payload(p4, account_fingerprint=account)
    assert obs4.ordinary_usage_allowed is None

    # 2.5 Non-zero output_tokens
    p5 = _print_usage_data()
    p5["usage"]["output_tokens"] = 25
    obs5 = AntigravityProviderAdapter.parse_print_usage_payload(p5, account_fingerprint=account)
    assert obs5.ordinary_usage_allowed is None

    # 2.6 Boolean output_tokens
    p6 = _print_usage_data()
    p6["usage"]["output_tokens"] = False
    obs6 = AntigravityProviderAdapter.parse_print_usage_payload(p6, account_fingerprint=account)
    assert obs6.ordinary_usage_allowed is None

    # 2.7 Non-zero optional thinking_tokens
    p7 = _print_usage_data()
    p7["usage"]["thinking_tokens"] = 10
    obs7 = AntigravityProviderAdapter.parse_print_usage_payload(p7, account_fingerprint=account)
    assert obs7.ordinary_usage_allowed is None

    # 2.8 Non-zero optional cache_read_tokens
    p8 = _print_usage_data()
    p8["usage"]["cache_read_tokens"] = 5
    obs8 = AntigravityProviderAdapter.parse_print_usage_payload(p8, account_fingerprint=account)
    assert obs8.ordinary_usage_allowed is None

    # 2.9 Out-of-bounds quota fraction (< 0)
    p9 = _print_usage_data(remaining_5h=-0.5)
    obs9 = AntigravityProviderAdapter.parse_print_usage_payload(p9, account_fingerprint=account)
    assert obs9.ordinary_usage_allowed is None

    # 2.10 Out-of-bounds quota fraction (> 1)
    p10 = _print_usage_data(remaining_weekly=1.2)
    obs10 = AntigravityProviderAdapter.parse_print_usage_payload(p10, account_fingerprint=account)
    assert obs10.ordinary_usage_allowed is None

    # 2.11 Boolean fraction (True evaluates to 1 in Python without strict type check)
    p11 = _print_usage_data()
    p11["command"]["data"]["groups"][0]["buckets"][0]["remaining_fraction"] = True
    obs11 = AntigravityProviderAdapter.parse_print_usage_payload(p11, account_fingerprint=account)
    assert obs11.ordinary_usage_allowed is None

    # 2.12 Corrupted reset timestamp
    p12 = _print_usage_data()
    p12["command"]["data"]["groups"][0]["buckets"][0]["reset_time"] = "not-iso-8601"
    obs12 = AntigravityProviderAdapter.parse_print_usage_payload(p12, account_fingerprint=account)
    assert obs12.ordinary_usage_allowed is None

    # 2.13 Duplicate bucket IDs in gemini group
    p13 = _print_usage_data()
    p13["command"]["data"]["groups"][0]["buckets"].append(
        {
            "id": "gemini-5h",
            "name": "Duplicate Five Hour Limit",
            "remaining_fraction": 0.5,
            "reset_time": (utc_now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    obs13 = AntigravityProviderAdapter.parse_print_usage_payload(p13, account_fingerprint=account)
    assert obs13.ordinary_usage_allowed is None

    # 2.14 Conflicting duplicate quota groups
    p14 = _print_usage_data()
    p14["command"]["data"]["groups"].append(
        {
            "name": "Gemini Models Conflicting",
            "buckets": [],
        }
    )
    obs14 = AntigravityProviderAdapter.parse_print_usage_payload(p14, account_fingerprint=account)
    assert obs14.ordinary_usage_allowed is None


def test_agy_regression_vector_3_stale_payload(in_memory_uow):
    """Vector 3: Observation older than bounded TTL (>60s) or expired/past reset fails closed."""
    service = ProviderHealthService(in_memory_uow)
    now = utc_now()
    account = "c" * 64

    # 3.1 Observation already expired
    stale_obs = CapacityObservation(
        provider="antigravity",
        ordinary_usage_allowed=True,
        observed_at=now - timedelta(seconds=120),
        expires_at=now - timedelta(seconds=60),
        source_signal=CapacitySignalSource.AGY_PRINT_USAGE,
        account_id=account,
        model="Gemini Models",
    )
    assert not service.record_capacity_observation("antigravity", stale_obs)
    health = service.get_admission_health("antigravity")
    assert health.status == ProviderHealthStatus.UNKNOWN
    assert not service.has_fresh_capacity_evidence("antigravity")

    # 3.2 Observation lifetime exceeds max TTL (> 60s)
    long_obs = CapacityObservation(
        provider="antigravity",
        ordinary_usage_allowed=True,
        observed_at=now,
        expires_at=now + timedelta(seconds=300),  # 5 min > 60s
        source_signal=CapacitySignalSource.AGY_PRINT_USAGE,
        account_id=account,
        model="Gemini Models",
    )
    assert not service.record_capacity_observation("antigravity", long_obs)
    assert service.get_admission_health("antigravity").status == ProviderHealthStatus.UNKNOWN

    # 3.3 Reset time in the past relative to observation time
    past_reset = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    p_past = _print_usage_data(reset_5h=past_reset)
    obs_past = AntigravityProviderAdapter.parse_print_usage_payload(
        p_past, observed_at=now, account_fingerprint=account
    )
    assert obs_past.ordinary_usage_allowed is None

    # 3.4 Reset time equal to observation time
    eq_reset = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    p_eq = _print_usage_data(reset_5h=eq_reset)
    obs_eq = AntigravityProviderAdapter.parse_print_usage_payload(
        p_eq, observed_at=now, account_fingerprint=account
    )
    assert obs_eq.ordinary_usage_allowed is None

    # 3.5 Reset time missing timezone
    naive_reset = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    p_naive = _print_usage_data(reset_5h=naive_reset)
    obs_naive = AntigravityProviderAdapter.parse_print_usage_payload(
        p_naive, observed_at=now, account_fingerprint=account
    )
    assert obs_naive.ordinary_usage_allowed is None


@pytest.mark.asyncio
async def test_agy_regression_vector_4_unknown_provenance(in_memory_uow, monkeypatch):
    """Vector 4: Unverified account identity, missing/contradictory auth, or statusLine cannot authorize dispatch."""
    service = ProviderHealthService(in_memory_uow)
    now = utc_now()
    valid_payload = _print_usage_data()

    # 4.1 Missing account fingerprint in /usage
    obs_no_acc = AntigravityProviderAdapter.parse_print_usage_payload(
        valid_payload, account_fingerprint=None
    )
    assert obs_no_acc.ordinary_usage_allowed is None

    # 4.2 Malformed non-hex or wrong-length account fingerprint
    for bad_fp in ("", "short", "z" * 64, "12345"):
        obs_bad = AntigravityProviderAdapter.parse_print_usage_payload(
            valid_payload, account_fingerprint=bad_fp
        )
        assert obs_bad.ordinary_usage_allowed is None

    # 4.3 statusLine cannot authorize dispatch: demoted to informative telemetry
    statusline_obs = CapacityObservation(
        provider="antigravity",
        ordinary_usage_allowed=True,
        observed_at=now,
        expires_at=now + timedelta(seconds=30),
        source_signal=CapacitySignalSource.AGY_STATUSLINE,
        account_id="d" * 64,
        model="Gemini Models",
        source_session_id="unverified-session-xyz",
    )
    assert not service.record_capacity_observation("antigravity", statusline_obs)
    admission_health = service.get_admission_health("antigravity")
    assert admission_health.status == ProviderHealthStatus.UNKNOWN
    assert not service.has_fresh_capacity_evidence("antigravity")

    # Informative telemetry event is recorded with state UNKNOWN and source agy_statusline_quota
    events = [
        e
        for e in in_memory_uow.events.list_events()
        if e.event_type == EventType.PROVIDER_CAPACITY_OBSERVED
    ]
    assert len(events) >= 1
    latest = events[-1]
    assert latest.payload["state"] == "UNKNOWN"
    assert latest.payload["source"] == CapacitySignalSource.UNKNOWN.value

    # 4.4 Subprocess: log file missing applyAuthResult event
    class FakeProc:
        returncode = 0

        async def communicate(self):
            return json.dumps(_print_usage_data()).encode(), b""

    async def fake_exec_no_auth(*args, **kwargs):
        for i, a in enumerate(args):
            if a == "--log-file" and i + 1 < len(args):
                Path(args[i + 1]).write_text("I1014 14:20:00 server.go:100] startup info\n")
        return FakeProc()

    adapter = AntigravityProviderAdapter()
    monkeypatch.setattr(
        "minime.adapters.provider_adapter.asyncio.create_subprocess_exec", fake_exec_no_auth
    )
    obs_no_auth = await adapter._read_print_usage_snapshot("/usr/bin/agy", timeout_seconds=2.0)
    assert obs_no_auth.ordinary_usage_allowed is None

    # 4.5 Subprocess: log file has conflicting emails
    async def fake_exec_conflict(*args, **kwargs):
        for i, a in enumerate(args):
            if a == "--log-file" and i + 1 < len(args):
                Path(args[i + 1]).write_text(
                    "applyAuthResult: email=alice@example.com, authMethod=consumer\n"
                    "applyAuthResult: email=bob@example.com, authMethod=consumer\n"
                )
        return FakeProc()

    monkeypatch.setattr(
        "minime.adapters.provider_adapter.asyncio.create_subprocess_exec", fake_exec_conflict
    )
    obs_conflict = await adapter._read_print_usage_snapshot("/usr/bin/agy", timeout_seconds=2.0)
    assert obs_conflict.ordinary_usage_allowed is None

    # 4.6 Subprocess: log file has non-consumer authMethod
    async def fake_exec_wrong_method(*args, **kwargs):
        for i, a in enumerate(args):
            if a == "--log-file" and i + 1 < len(args):
                Path(args[i + 1]).write_text(
                    "applyAuthResult: email=alice@example.com, authMethod=service_account\n"
                )
        return FakeProc()

    monkeypatch.setattr(
        "minime.adapters.provider_adapter.asyncio.create_subprocess_exec", fake_exec_wrong_method
    )
    obs_wrong_method = await adapter._read_print_usage_snapshot("/usr/bin/agy", timeout_seconds=2.0)
    assert obs_wrong_method.ordinary_usage_allowed is None

    # 4.7 Subprocess: unsupported executable fails closed
    obs_bad_exe = await adapter._read_print_usage_snapshot("/bin/sh", timeout_seconds=2.0)
    assert obs_bad_exe.ordinary_usage_allowed is None


def test_agy_regression_vector_5_identity_and_scope_mismatch():
    """Vector 5: Unsupported selected model fails closed; supported models map to quota scope."""
    account = "e" * 64
    payload = _print_usage_data()

    # 5.1 Unsupported selected model fails closed
    for unsupported in ("claude-3-5-sonnet", "gpt-4o", "meta/llama-3", "unknown-model"):
        obs = AntigravityProviderAdapter.parse_print_usage_payload(
            payload, account_fingerprint=account, selected_model=unsupported
        )
        assert obs.ordinary_usage_allowed is None

    # 5.2 Supported models map to Gemini Models quota scope and succeed
    for supported in (
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini 3.8 flash (high)",
        "google/gemini-1.5-pro",
        "Gemini Models",
    ):
        obs = AntigravityProviderAdapter.parse_print_usage_payload(
            payload, account_fingerprint=account, selected_model=supported
        )
        assert obs.ordinary_usage_allowed is True
        assert obs.model == supported


def test_agy_regression_vector_6_acquisition_to_dispatch(in_memory_uow):
    """Vector 6: Persistence rejects direct/forged observations; JIT admission gate prevents dispatch."""
    service = ProviderHealthService(in_memory_uow)
    now = utc_now()
    account = "f" * 64

    # 6.1 Direct caller-created observation with invalid account format is rejected
    forged_obs = CapacityObservation(
        provider="antigravity",
        ordinary_usage_allowed=True,
        observed_at=now,
        expires_at=now + timedelta(seconds=30),
        source_signal=CapacitySignalSource.AGY_PRINT_USAGE,
        account_id="not-a-valid-sha256-fingerprint",
        model="Gemini Models",
    )
    assert not service.record_capacity_observation("antigravity", forged_obs)
    assert service.get_admission_health("antigravity").status == ProviderHealthStatus.UNKNOWN

    # 6.2 Observation with capacity_reset_at <= observed_at is rejected
    past_reset_obs = CapacityObservation(
        provider="antigravity",
        ordinary_usage_allowed=True,
        observed_at=now,
        expires_at=now + timedelta(seconds=30),
        source_signal=CapacitySignalSource.AGY_PRINT_USAGE,
        account_id=account,
        model="Gemini Models",
        capacity_reset_at=now - timedelta(seconds=10),
    )
    assert not service.record_capacity_observation("antigravity", past_reset_obs)
    assert service.get_admission_health("antigravity").status == ProviderHealthStatus.UNKNOWN

    # 6.3 Admission health fails closed when capacity evidence is absent or UNKNOWN
    assert not service.has_fresh_capacity_evidence("antigravity")
    health = service.get_admission_health("antigravity")
    assert health.status == ProviderHealthStatus.UNKNOWN


@pytest.mark.asyncio
async def test_agy_regression_vector_7_valid_signal(in_memory_uow, test_capacity_strategy):
    """Vector 7: Clean non-inferential /usage signal produces AVAILABLE; zero fraction produces EXHAUSTED."""
    test_capacity_strategy(("antigravity",))
    adapter = get_provider_adapter("antigravity")
    service = ProviderHealthService(in_memory_uow)
    account = "7" * 64
    valid_payload = _print_usage_data(remaining_5h=0.75, remaining_weekly=0.92)

    # 7.1 Clean available signal
    obs = AntigravityProviderAdapter.parse_print_usage_payload(
        valid_payload, account_fingerprint=account
    )
    assert obs.ordinary_usage_allowed is True
    assert obs.source_signal == CapacitySignalSource.AGY_PRINT_USAGE
    assert obs.account_id == account
    assert obs.model == "Gemini Models"
    assert obs.capacity_reset_at is not None
    assert obs.capacity_reset_at > obs.observed_at

    # Authoritative recording in ProviderHealthService
    assert await service.refresh_capacity_from_read_only_source("antigravity")
    admission_health = service.get_admission_health("antigravity")
    assert admission_health.status == ProviderHealthStatus.AVAILABLE
    assert service.has_fresh_capacity_evidence("antigravity")

    # 7.2 Zero fraction produces EXHAUSTED with valid future reset
    exhausted_payload = _print_usage_data(remaining_5h=0.0, remaining_weekly=0.92)
    obs_ex = AntigravityProviderAdapter.parse_print_usage_payload(
        exhausted_payload, account_fingerprint=account
    )
    assert obs_ex.ordinary_usage_allowed is False
    adapter.allowed = False
    assert not await service.refresh_capacity_from_read_only_source("antigravity")
    ex_health = service.get_admission_health("antigravity")
    assert ex_health.status == ProviderHealthStatus.EXHAUSTED
