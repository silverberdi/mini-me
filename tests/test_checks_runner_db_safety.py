"""PostgreSQL safety and database-environment isolation tests."""

import pytest

from minime.services.checks_runner import ChecksRunner


class _Proc:
    returncode = 0

    async def communicate(self):
        return b"ok", b""


@pytest.mark.asyncio
async def test_normal_checks_do_not_inherit_database_environment(monkeypatch, tmp_path):
    captured = {}

    async def spawn(*args, **kwargs):
        captured.update(kwargs["env"])
        return _Proc()

    monkeypatch.setenv("MINIME_DATABASE_URL", "postgresql://x/minime")
    monkeypatch.setenv("MINIME_EXPECTED_DATABASE", "minime")
    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_shell", spawn)
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
        spawned.append(args[0])
        return _Proc()

    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_shell", spawn)
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
    assert spawned == ["true"]


@pytest.mark.asyncio
async def test_verified_disposable_database_receives_only_validated_environment(
    monkeypatch, tmp_path
):
    captured = {}

    async def spawn(*args, **kwargs):
        captured.update(kwargs["env"])
        return _Proc()

    monkeypatch.setenv("MINIME_DATABASE_URL", "postgresql://x/minime")
    monkeypatch.setenv("MINIME_EXPECTED_DATABASE", "minime")
    monkeypatch.setattr("minime.services.checks_runner.asyncio.create_subprocess_shell", spawn)
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
