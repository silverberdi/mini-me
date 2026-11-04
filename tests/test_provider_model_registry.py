import asyncio
import json
import stat

import pytest

from minime.services.provider_registry import (
    CanonicalProfileResolver,
    CustomModelRequest,
    IntrospectionResult,
    ModelEnablementRequest,
    ProviderModelRepository,
    SafeCliHarness,
    _parse_model_output,
    classify_discovered_model,
    reject_secret_payload,
)


def test_custom_model_dto_is_allowlisted_and_secret_free():
    model = CustomModelRequest(
        provider_id="deepseek",
        harness_id="direct",
        canonical_model_id="deepseek-chat",
        capabilities={"workflow": True},
    )
    assert "api_key" not in json.dumps(model.model_dump()).lower()
    with pytest.raises(ValueError):
        reject_secret_payload({"canonical_model_id": "x", "token": "sk-secret"})
    with pytest.raises(ValueError):
        reject_secret_payload({"canonical_model_id": "x", "credential": "placeholder"})


def test_discovery_parser_accepts_single_model_and_rejects_unscoped_opencode_output():
    assert _parse_model_output("opencode", "deepseek/deepseek-flash\n") == (
        "deepseek/deepseek-flash",
    )
    assert _parse_model_output("ollama", "NAME ID\nqwen2.5:7b 123\n") == ("qwen2.5:7b",)
    assert _parse_model_output("opencode", "MODEL\nqwen2.5:7b\n") == ()


def test_discovered_opencode_namespaces_remain_distinct():
    assert classify_discovered_model("opencode", "deepseek/deepseek-chat") == (
        "deepseek", "opencode", "deepseek_direct"
    )
    assert classify_discovered_model("opencode", "openrouter/deepseek/deepseek-r1") == (
        "openrouter", "opencode", "openrouter"
    )


@pytest.mark.parametrize(
    "argv",
    [("run", "dangerous"), ("sh", "-c", "echo bad"), ("models", "--json"), ("--version", "|", "cat")],
)
def test_safe_harness_rejects_unlisted_argv_before_process(monkeypatch, argv):
    harness = SafeCliHarness("opencode", "opencode")
    called = False

    async def fail(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("process must not be created")

    monkeypatch.setattr("minime.services.provider_registry.asyncio.create_subprocess_exec", fail)
    with pytest.raises(ValueError):
        asyncio.run(harness._run(argv))
    assert not called


def test_safe_harness_uses_real_read_only_process(tmp_path, monkeypatch):
    executable = tmp_path / "opencode"
    executable.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'opencode 1.0'; exit 0; fi\n"
        "if [ \"$1\" = \"models\" ]; then echo 'MODEL'; echo 'deepseek/deepseek-flash'; exit 0; fi\n"
        "exit 9\n"
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr("minime.services.provider_registry.shutil.which", lambda _: str(executable))
    result = asyncio.run(SafeCliHarness("opencode", "opencode").inspect())
    assert result.status == "available"
    assert result.models == ("deepseek/deepseek-flash",)


def test_safe_harness_times_out_without_marking_discovery_available(monkeypatch):
    class HangingProcess:
        async def communicate(self):
            await asyncio.sleep(1)
            return b"", b""

        def kill(self):
            return None

    async def create_process(*args, **kwargs):
        return HangingProcess()

    monkeypatch.setattr(
        "minime.services.provider_registry.asyncio.create_subprocess_exec", create_process
    )
    result = asyncio.run(SafeCliHarness("ollama", "ollama", timeout_seconds=0.001).inspect())
    assert result.status == "blocked"
    assert result.code == "timeout"


def test_canonical_resolver_requires_exact_identity_and_capabilities():
    class Row:
        provider_id = "deepseek"
        harness_id = "direct"
        canonical_model_id = "deepseek-chat"
        discovery_status = "available"
        is_enabled = True
        diagnostic_code = "ok"
        diagnostic_summary = "verified"
        last_observed_at = None
        capabilities = {"workflow": True, "file_edit": True, "read_only_review": True}

    class Repo:
        def get(self, provider, harness, model):
            return Row() if (provider, harness, model) == ("deepseek", "direct", "deepseek-chat") else None

    resolved = CanonicalProfileResolver(Repo()).resolve(
        "implementer",
        {"provider_id": "deepseek", "harness_id": "direct", "canonical_model_id": "deepseek-chat", "route": "direct"},
    )
    assert resolved["provider_id"] == "deepseek"
    assert resolved["route"] == "direct"
    with pytest.raises(ValueError, match="absent"):
        CanonicalProfileResolver(Repo()).resolve(
            "implementer", {"provider_id": "deepseek", "harness_id": "direct", "canonical_model_id": "deepseek-garbage"}
        )


def test_canonical_resolver_rejects_route_drift():
    class Row:
        provider_id = "deepseek"
        harness_id = "opencode"
        canonical_model_id = "deepseek/deepseek-flash"
        discovery_status = "available"
        is_enabled = True
        diagnostic_code = "ok"
        last_observed_at = None
        capabilities = {
            "workflow": True,
            "file_edit": True,
            "model_route": "deepseek_direct",
        }

    class Repo:
        def get(self, *_args, **_kwargs):
            return Row()

    with pytest.raises(ValueError, match="route"):
        CanonicalProfileResolver(Repo()).resolve(
            "implementer",
            {
                "provider_id": "deepseek",
                "harness_id": "opencode",
                "canonical_model_id": "deepseek/deepseek-flash",
                "route": "openrouter",
            },
        )


def test_failed_harness_observation_blocks_existing_non_custom_rows():
    class Row:
        harness_id = "opencode"
        origin = "discovered"
        discovery_status = "available"
        diagnostic_code = "ok"
        diagnostic_summary = "old"
        observed_cli_version = "old"
        last_observed_at = None
        version = 2
        is_enabled = True
        updated_at = None

    row = Row()

    class Session:
        def scalars(self, _statement):
            return iter([row])

        def flush(self):
            return None

    ProviderModelRepository(Session()).record_harness_diagnostic(
        "opencode",
        IntrospectionResult("opencode", "blocked", "timeout", "probe timed out"),
    )
    assert row.discovery_status == "blocked"
    assert row.diagnostic_code == "timeout"
    assert row.version == 3


def test_provider_model_toggle_is_persisted_without_changing_discovery_or_diagnostic():
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from minime.db.models import ProviderModelRegistryModel

    engine = create_engine("sqlite+pysqlite:///:memory:")
    ProviderModelRegistryModel.__table__.create(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        row = ProviderModelRegistryModel(
            id="model-1", provider_id="deepseek", harness_id="opencode",
            canonical_model_id="deepseek/deepseek-flash", origin="discovered",
            capabilities={"model_route": "deepseek_direct"}, discovery_status="available",
            diagnostic_code="ok", diagnostic_summary="observed", version=1,
            created_at=now, updated_at=now,
        )
        session.add(row)
        session.flush()
        assert row.is_enabled is True
        session.expire(row)
        session.refresh(row)
        original_updated_at = row.updated_at

        disabled = ProviderModelRepository(session).set_enabled(
            "model-1", ModelEnablementRequest(is_enabled=False, version=1)
        )
        assert disabled.is_enabled is False
        assert disabled.version == 2
        assert disabled.updated_at == original_updated_at
        assert disabled.discovery_status == "available"
        assert disabled.diagnostic_code == "ok"

        with pytest.raises(ValueError, match="stale"):
            ProviderModelRepository(session).set_enabled(
                "model-1", ModelEnablementRequest(is_enabled=True, version=1)
            )

        ProviderModelRepository(session).record_harness_diagnostic(
            "opencode", IntrospectionResult("opencode", "blocked", "cli_missing", "not installed")
        )
        refreshed = ProviderModelRepository(session).get(
            "deepseek", "opencode", "deepseek/deepseek-flash"
        )
        assert refreshed.is_enabled is False
        assert refreshed.discovery_status == "blocked"
        assert refreshed.diagnostic_code == "cli_missing"

        ProviderModelRepository(session).upsert_observation({
            "provider_id": "deepseek",
            "harness_id": "opencode",
            "canonical_model_id": "deepseek/deepseek-flash",
            "origin": "discovered",
            "capabilities": {"model_route": "deepseek_direct"},
            "discovery_status": "available",
            "diagnostic_code": "ok",
            "diagnostic_summary": "observed again",
        })
        refreshed = ProviderModelRepository(session).get(
            "deepseek", "opencode", "deepseek/deepseek-flash"
        )
        assert refreshed.is_enabled is False
        assert refreshed.discovery_status == "available"
        assert refreshed.diagnostic_summary == "observed again"


def test_enablement_migration_adds_enabled_default_and_downgrades():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    migration_path = Path(__file__).parents[1] / "alembic/versions/f14_provider_model_enablement.py"
    spec = importlib.util.spec_from_file_location("f14_provider_model_enablement", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(migration)
    assert migration.down_revision == "f13_provider_model_registry"

    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE provider_model_registry (id VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO provider_model_registry (id) VALUES ('existing')"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        assert bool(connection.execute(
            text("SELECT is_enabled FROM provider_model_registry WHERE id='existing'")
        ).scalar_one()) is True
        with Operations.context(context):
            migration.downgrade()
        assert "is_enabled" not in {column["name"] for column in inspect(connection).get_columns("provider_model_registry")}


def test_run_invocation_preserves_canonical_route():
    from minime.config import AppConfig, CliInvocationConfig, ProviderConfig
    from minime.services.agent_runner import CliAgentRunner

    config = AppConfig(providers={
        "opencode": ProviderConfig(
            command="opencode",
            roles=["implementer", "reviewer"],
            invocation={
                "implementer": CliInvocationConfig(args=["run"]),
                "reviewer": CliInvocationConfig(args=["run"]),
            },
        )
    })
    profiles = {
        name: {
            "agent_id": "opencode",
            "provider_id": "deepseek",
            "harness_id": "opencode",
            "model_id": "deepseek/deepseek-flash",
            "route": "deepseek_direct",
            "effort": "medium",
        }
        for name in ("thinking", "execution", "independent_review", "fallback")
    }
    runner = CliAgentRunner.for_project_profiles(profiles, config=config)
    invocation = runner.profiles[("execution", "opencode")]
    assert invocation.canonical_provider_id == "deepseek"
    assert invocation.harness_id == "opencode"
    assert invocation.model == "deepseek/deepseek-flash"
    assert invocation.route == "deepseek_direct"
