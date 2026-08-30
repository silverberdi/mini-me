"""PostgreSQL safety acceptance tests for deterministic checks."""

import asyncio

import pytest

from minime.services.checks_runner import ChecksRunner


@pytest.mark.parametrize("url", ["mysql://user@localhost/disposable", "sqlite:///disposable.db"])
def test_disposable_check_rejects_non_postgres_and_runs_later_check(monkeypatch, tmp_path, url):
    monkeypatch.setenv("MINIME_DATABASE_URL", url)
    result = asyncio.run(
        ChecksRunner().run(
            "job",
            [
                {"name": "db", "command": "true", "disposable_postgres": True, "expected_database": "disposable"},
                {"name": "later", "command": "true"},
            ],
            tmp_path,
            candidate_sha="a" * 40,
            candidate_generation=2,
        )
    )
    assert [item.check_name for item in result.results] == ["db", "later"]
    assert result.results[0].exit_code != 0
    assert result.results[1].exit_code == 0
