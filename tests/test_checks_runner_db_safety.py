"""PostgreSQL safety and database-environment isolation tests."""

import shlex
import sys
from types import SimpleNamespace

import pytest

from minime.domain.enums import ExternalOutcome
from minime.services.agent_confinement import AgentProcessConfinement
from minime.services.checks_runner import ChecksRunner


class _Proc:
    returncode = 0

    async def communicate(self):
        return b"ok", b""


def test_candidate_test_environment_uses_runtime_allowlist():
    host_env = {
        "PATH": "/usr/bin",
        "HOME": "/home/tester",
        "LANG": "en_US.UTF-8",
        "LC_TIME": "en_US.UTF-8",
        "DOTNET_ROOT": "/opt/dotnet",
        "NODE_PATH": "/opt/node-modules",
        "PYTHONPATH": "/opt/python",
        "TMPDIR": "/tmp/tester",
        "AWS_ACCESS_KEY_ID": "host-aws-secret",
        "POSTGRES_PASSWORD": "host-postgres-secret",
        "GITHUB_TOKEN": "host-github-secret",
        "ANTHROPIC_AUTH_TOKEN": "host-anthropic-secret",
        "HOST_ONLY_SETTING": "not-for-candidate",
        "OPENAI_API_KEY": "host-openai-secret",
    }

    assert AgentProcessConfinement.prepare_candidate_test_environment(host_env) == {
        key: host_env[key]
        for key in (
            "PATH",
            "HOME",
            "LANG",
            "LC_TIME",
            "DOTNET_ROOT",
            "NODE_PATH",
            "PYTHONPATH",
            "TMPDIR",
        )
    }


@pytest.mark.asyncio
async def test_normal_checks_do_not_inherit_database_environment(monkeypatch, tmp_path):
    captured = {}

    async def spawn(*args, **kwargs):
        captured.update(kwargs.get("env", {}))
        return _Proc()

    monkeypatch.setenv("MINIME_DATABASE_URL", "postgresql://x/minime")
    monkeypatch.setenv("MINIME_EXPECTED_DATABASE", "minime")
    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_shell", spawn)
    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_exec", spawn)
    result = await ChecksRunner().run("job", [{"name": "check", "command": "true"}], tmp_path)
    assert result.passed
    assert "MINIME_DATABASE_URL" not in captured
    assert "MINIME_EXPECTED_DATABASE" not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "check",
    [
        {
            "disposable_postgres": True,
            "expected_database": "minime",
            "database_url": "postgresql://x/minime",
        },
        {
            "disposable_postgres": True,
            "expected_database": "other",
            "database_url": "mysql://x/other",
        },
        {
            "disposable_postgres": True,
            "expected_database": "other",
            "database_url": "postgresql://x/actual",
        },
    ],
)
async def test_invalid_disposable_database_fails_before_spawn(monkeypatch, tmp_path, check):
    spawned = []

    async def spawn(*args, **kwargs):
        cmd = args[-1] if args else ""
        spawned.append(cmd)
        return _Proc()

    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_shell", spawn)
    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_exec", spawn)
    result = await ChecksRunner().run(
        "job",
        [
            {"name": "pg", "command": "true", **check},
            {"name": "later", "command": "true"},
        ],
        tmp_path,
    )
    assert not result.passed
    assert result.results[0].exit_code == 126
    assert [item.check_name for item in result.results] == ["pg", "later"]
    assert len(spawned) == 1 and "true" in spawned[0]


@pytest.mark.asyncio
async def test_verified_disposable_database_receives_only_validated_environment(
    monkeypatch, tmp_path
):
    captured = {}

    async def spawn(*args, **kwargs):
        captured.update(kwargs.get("env", {}))
        return _Proc()

    monkeypatch.setenv("MINIME_DATABASE_URL", "postgresql://x/minime")
    monkeypatch.setenv("MINIME_EXPECTED_DATABASE", "minime")
    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_shell", spawn)
    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_exec", spawn)
    result = await ChecksRunner().run(
        "job",
        [
            {
                "name": "pg",
                "command": "true",
                "disposable_postgres": True,
                "expected_database": "disposable_011",
                "database_url": "postgresql://x/disposable_011",
            }
        ],
        tmp_path,
    )
    assert result.passed
    assert captured["MINIME_DATABASE_URL"] == "postgresql://x/disposable_011"
    assert captured["MINIME_EXPECTED_DATABASE"] == "disposable_011"


@pytest.mark.asyncio
async def test_configured_check_child_does_not_receive_host_provider_credentials(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OPENAI_API_KEY", "host-openai-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "host-deepseek-secret")
    monkeypatch.setenv("CUSTOM_SERVICE_API_KEY", "host-custom-secret")
    monkeypatch.setenv("CUSTOM_SERVICE_SECRET", "host-infra-secret")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "host-aws-secret")
    monkeypatch.setenv("POSTGRES_PASSWORD", "host-postgres-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "host-github-secret")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "host-anthropic-secret")
    monkeypatch.setenv("HOST_ONLY_SETTING", "not-for-candidate")
    monkeypatch.setenv("MINIME_DATABASE_URL", "postgresql://db/minime")
    monkeypatch.setenv("MINIME_EXPECTED_DATABASE", "minime")
    monkeypatch.setenv("LANG", "en_US.UTF-8")

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

    script = (
        "import os; "
        "assert all(key not in os.environ for key in ("
        "'OPENAI_API_KEY','DEEPSEEK_API_KEY','CUSTOM_SERVICE_API_KEY',"
        "'CUSTOM_SERVICE_SECRET','AWS_ACCESS_KEY_ID','POSTGRES_PASSWORD',"
        "'GITHUB_TOKEN','ANTHROPIC_AUTH_TOKEN','HOST_ONLY_SETTING')); "
        "assert os.environ.get('PATH'); "
        "assert os.environ['LANG'] == 'en_US.UTF-8'; "
        "assert os.environ['MINIME_DATABASE_URL'] == 'postgresql://db/disposable_455'; "
        "assert os.environ['MINIME_EXPECTED_DATABASE'] == 'disposable_455'"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
    result = await ChecksRunner().run(
        "job",
        [
            {
                "name": "isolated-check",
                "command": command,
                "disposable_postgres": True,
                "expected_database": "disposable_455",
                "database_url": "postgresql://db/disposable_455",
            }
        ],
        tmp_path,
    )

    assert result.passed, result.results[0].output_snippet


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

    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_shell", spawn)
    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_exec", spawn)
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
