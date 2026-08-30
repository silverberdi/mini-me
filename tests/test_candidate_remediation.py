"""Focused acceptance tests for immutable remediation contracts and generations."""

from pydantic import ValidationError

from minime.domain.models import RemediationContract


def test_remediation_contract_is_canonical_and_immutable():
    contract = RemediationContract(
        contract_version="1",
        run_id="run-1",
        source_candidate_generation=2,
        source_candidate_sha="a" * 40,
        source_candidate_base_sha="b" * 40,
        change_name="change",
        objective="fix the preserved candidate",
        allowed_paths=["src/fix.py"],
        protected_paths=["openspec"],
        required_outcomes=["tests pass"],
        verification_commands=["pytest"],
        stop_conditions=["out of scope"],
    )
    assert contract.canonical_json() == contract.canonical_json()
    assert len(contract.contract_hash()) == 64
    try:
        contract.objective = "changed"
    except (TypeError, ValidationError):
        pass
    else:
        raise AssertionError("remediation contract must be frozen")


def test_check_runner_unsafe_postgres_check_does_not_short_circuit(tmp_path):
    """Unsafe disposable checks fail closed while later checks still execute."""
    import asyncio

    from minime.services.checks_runner import ChecksRunner

    result = asyncio.run(
        ChecksRunner().run(
            "job",
            [
                {
                    "name": "unsafe-db",
                    "command": "true",
                    "disposable_postgres": True,
                    "expected_database": "disposable",
                },
                {"name": "later", "command": "true"},
            ],
            tmp_path,
            candidate_sha="c" * 40,
            candidate_generation=3,
        )
    )
    assert [item.check_name for item in result.results] == ["unsafe-db", "later"]
    assert result.results[0].exit_code != 0
    assert result.results[1].exit_code == 0
    assert all(item.candidate_generation == 3 for item in result.results)
