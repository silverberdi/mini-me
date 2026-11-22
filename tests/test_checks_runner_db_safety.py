"""PostgreSQL safety and database-environment isolation tests."""

import shlex
import sys
from types import SimpleNamespace

import pytest

from minime.domain.enums import ExternalOutcome
from minime.domain.models import ProjectTestDatabase
from minime.services.agent_confinement import AgentProcessConfinement
from minime.services.checks_runner import ChecksRunner


class _Proc:
    returncode = 0

    def __init__(self, stdout=b"ok", stderr=b""):
        self.stdout = stdout
        self.stderr = stderr

    async def communicate(self):
        return self.stdout, self.stderr


def _profile(**overrides):
    values = dict(
        host="192.168.0.194",
        port=5432,
        database_name="sample_test",
        production_database_names=["sample_prod"],
        url_env="SAMPLE_TEST_DATABASE_URL",
    )
    values.update(overrides)
    return ProjectTestDatabase(**values)


def _configure_spawn(monkeypatch, spawn):
    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_shell", spawn)
    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_exec", spawn)
    monkeypatch.setattr(AgentProcessConfinement, "is_confinement_available", lambda self: True)
    monkeypatch.setattr(
        AgentProcessConfinement,
        "validate_command_preflight",
        lambda self, cwd: SimpleNamespace(outcome=ExternalOutcome.SUCCESS, error_message=""),
    )
    monkeypatch.setattr(
        AgentProcessConfinement,
        "wrap_command",
        lambda self, command, **kwargs: shlex.split(command)
        if isinstance(command, str)
        else command,
    )


def test_test_database_profile_rejects_secret_fields_and_production_identity():
    with pytest.raises(ValueError):
        ProjectTestDatabase.model_validate(
            {
                **_profile().model_dump(),
                "password": "must-not-persist",
            }
        )
    with pytest.raises(ValueError):
        _profile(database_name="sample_prod")
    with pytest.raises(ValueError):
        _profile(database_name="minime")


@pytest.mark.asyncio
async def test_normal_checks_do_not_inherit_database_environment(monkeypatch, tmp_path):
    captured = {}

    async def spawn(*args, **kwargs):
        captured.update(kwargs.get("env", {}))
        return _Proc()

    _configure_spawn(monkeypatch, spawn)
    monkeypatch.setenv("MINIME_DATABASE_URL", "postgresql://host/minime")
    monkeypatch.setenv("SAMPLE_TEST_DATABASE_URL", "postgresql://host/sample_test")
    result = await ChecksRunner().run("job", [{"name": "check", "command": "true"}], tmp_path)
    assert result.passed
    assert "MINIME_DATABASE_URL" not in captured
    assert "SAMPLE_TEST_DATABASE_URL" not in captured
    assert "DATABASE_URL" not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "mysql://tester:secret@192.168.0.194:5432/sample_test",
        "postgresql://tester:secret@wrong-host:5432/sample_test",
        "postgresql://tester:secret@192.168.0.194:5433/sample_test",
        "postgresql://tester:secret@192.168.0.194:5432/sample_prod",
        "postgresql://tester:secret@192.168.0.194:5432/minime",
    ],
)
async def test_unsafe_database_target_fails_before_spawn(monkeypatch, tmp_path, url):
    spawned = []

    async def spawn(*args, **kwargs):
        spawned.append(args)
        return _Proc()

    _configure_spawn(monkeypatch, spawn)
    monkeypatch.setenv("SAMPLE_TEST_DATABASE_URL", url)
    result = await ChecksRunner().run(
        "job",
        [{"name": "pg", "command": "true", "uses_test_database": True}],
        tmp_path,
        test_database=_profile(),
    )
    assert not result.passed
    assert result.results[0].exit_code == 126
    assert not spawned
    assert "secret" not in result.results[0].output_snippet


@pytest.mark.asyncio
async def test_missing_profile_reference_or_inline_url_fails_before_spawn(monkeypatch, tmp_path):
    spawned = []

    async def spawn(*args, **kwargs):
        spawned.append(args)
        return _Proc()

    _configure_spawn(monkeypatch, spawn)
    monkeypatch.delenv("SAMPLE_TEST_DATABASE_URL", raising=False)
    cases = [
        (None, {"uses_test_database": True}),
        (_profile(), {"uses_test_database": True, "database_url": "postgresql://leak"}),
    ]
    for profile, config in cases:
        result = await ChecksRunner().run(
            "job", [{"name": "pg", "command": "true", **config}], tmp_path,
            test_database=profile,
        )
        assert not result.passed
        assert result.results[0].exit_code == 126
    assert not spawned


@pytest.mark.asyncio
async def test_inline_postgres_url_in_command_is_rejected_and_redacted(monkeypatch, tmp_path):
    spawned = []

    async def spawn(*args, **kwargs):
        spawned.append(args)
        return _Proc()

    _configure_spawn(monkeypatch, spawn)
    command = "psql 'postgresql://tester:secret@db.example.test/sample_prod' -c 'drop table data'"
    result = await ChecksRunner().run(
        "job", [{"name": "unsafe", "command": command}], tmp_path
    )
    assert not result.passed
    assert not spawned
    assert "secret" not in result.results[0].command
    assert "postgresql://tester:[REDACTED]@db.example.test/sample_prod" in result.results[0].command
    assert "secret" not in repr(result.diagnostics)


@pytest.mark.asyncio
async def test_configured_test_url_is_injected_only_into_database_check(monkeypatch, tmp_path):
    environments = []

    async def spawn(*args, **kwargs):
        environments.append(dict(kwargs.get("env", {})))
        return _Proc()

    _configure_spawn(monkeypatch, spawn)
    secret_url = "postgresql://tester:secret@192.168.0.194:5432/sample_test"
    monkeypatch.setenv("SAMPLE_TEST_DATABASE_URL", secret_url)
    monkeypatch.setenv("MINIME_DATABASE_URL", "postgresql://host/minime")
    result = await ChecksRunner().run(
        "job",
        [
            {"name": "database", "command": "true", "uses_test_database": True},
            {"name": "ordinary", "command": "true"},
        ],
        tmp_path,
        candidate_sha="a" * 40,
        test_database=_profile(),
    )
    assert result.passed
    assert environments[0]["SAMPLE_TEST_DATABASE_URL"] == secret_url
    assert environments[0]["DATABASE_URL"] == secret_url
    assert "MINIME_DATABASE_URL" not in environments[0]
    assert "SAMPLE_TEST_DATABASE_URL" not in environments[1]
    assert "DATABASE_URL" not in environments[1]
    assert all(secret_url not in repr(item) for item in result.results + result.diagnostics)


@pytest.mark.asyncio
async def test_database_url_is_redacted_from_check_output(monkeypatch, tmp_path):
    secret_url = "postgresql://tester:secret@192.168.0.194:5432/sample_test"

    async def spawn(*args, **kwargs):
        return _Proc(stdout=secret_url.encode())

    _configure_spawn(monkeypatch, spawn)
    monkeypatch.setenv("SAMPLE_TEST_DATABASE_URL", secret_url)
    result = await ChecksRunner().run(
        "job",
        [{"name": "database", "command": "true", "uses_test_database": True}],
        tmp_path,
        test_database=_profile(),
    )
    assert result.passed
    assert secret_url not in result.results[0].output_snippet
    assert "[REDACTED]" in result.results[0].output_snippet


@pytest.mark.asyncio
async def test_environment_unavailable_check_defers_only_with_named_ci_mapping(
    monkeypatch, tmp_path
):
    class MissingRunner:
        returncode = 1

        async def communicate(self):
            return b"", b"browserType.launch: Executable doesn't exist at the configured Chromium path"

    async def spawn(*args, **kwargs):
        return MissingRunner()

    _configure_spawn(monkeypatch, spawn)
    result = await ChecksRunner().run(
        "job",
        [
            {
                "name": "browser-test",
                "command": "npm run test:e2e",
                "pr_ci_check_name": "PR Validation / E2E browser validation",
            }
        ],
        tmp_path,
        candidate_sha="a" * 40,
        allow_ci_deferral=True,
    )
    assert result.passed
    assert result.results == []
    assert result.pending_ci_checks == [
        {
            "check_name": "browser-test",
            "pr_ci_check_name": "PR Validation / E2E browser validation",
            "candidate_sha": "a" * 40,
        }
    ]
    assert result.diagnostics[0].diagnostic_status.value == "ENVIRONMENT_UNAVAILABLE"
    assert result.diagnostics[0].evidence_reference["status"] == "PENDING"


@pytest.mark.asyncio
async def test_environment_unavailable_check_without_ci_mapping_stays_failed(
    monkeypatch, tmp_path
):
    class MissingRunner:
        returncode = 1

        async def communicate(self):
            return b"", b"browserType.launch: Executable doesn't exist at the configured Chromium path"

    async def spawn(*args, **kwargs):
        return MissingRunner()

    _configure_spawn(monkeypatch, spawn)
    result = await ChecksRunner().run(
        "job", [{"name": "browser-test", "command": "npm run test:e2e"}], tmp_path,
        candidate_sha="a" * 40,
        allow_ci_deferral=True,
    )
    assert not result.passed
    assert result.pending_ci_checks == []
    assert result.results[0].exit_code == 1


@pytest.mark.asyncio
async def test_missing_playwright_browser_is_classified_as_environment_unavailable(
    monkeypatch, tmp_path
):
    class MissingBrowser:
        returncode = 1

        async def communicate(self):
            return b"", b"browserType.launch: Executable doesn't exist at the configured Chromium path"

    async def spawn(*args, **kwargs):
        return MissingBrowser()

    _configure_spawn(monkeypatch, spawn)
    result = await ChecksRunner().run(
        "job",
        [{"name": "playwright", "command": "npm run test:e2e"}],
        tmp_path,
        candidate_sha="f" * 40,
    )
    assert not result.passed
    assert result.results[0].candidate_sha == "f" * 40
    assert result.diagnostics[0].diagnostic_status.value == "ENVIRONMENT_UNAVAILABLE"
    assert "Executable doesn't exist" in result.diagnostics[0].reason
