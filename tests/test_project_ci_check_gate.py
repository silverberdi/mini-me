from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
from minime.domain.models import ExternalActionResult
from minime.domain.models import ProjectTestDatabase
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.proposal_feasibility import ProposalFeasibilityEvaluator


def _result(sha, status="completed", conclusion="success", name="Backend / PostgreSQL"):
    return ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github_rest",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data={
            "head_sha": sha,
            "check_name": name,
            "status": status,
            "conclusion": conclusion,
        },
    )


def _coordinator(result):
    project = SimpleNamespace(
        checks=[
            {
                "name": "postgres-tests",
                "command": "pytest tests/db",
                "uses_test_database": True,
                "pr_ci_check_name": "Backend / PostgreSQL",
            }
        ],
        test_database=object(),
    )
    uow = SimpleNamespace(projects=SimpleNamespace(get_by_id=lambda _: project))
    github = SimpleNamespace(get_check_run_status=MagicMock(return_value=result))
    return NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=github,
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
    ), uow


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        _result("a" * 40, status="queued", conclusion=None),
        _result("a" * 40, status="completed", conclusion="failure"),
        _result("b" * 40),
    ],
)
async def test_pr_merge_waits_for_missing_pending_failed_or_stale_ci(result):
    coordinator, uow = _coordinator(result)
    run = SimpleNamespace(run_id="run-1", project_id="boxio", stop_details={"pr1_url": "https://github.com/boxio/pull/1"})

    waiting = await coordinator._required_project_ci_before_merge(
        uow,
        run,
        repository="silverberdi/boxio",
        candidate_sha="a" * 40,
    )

    assert waiting is not None
    assert waiting.current_stage.value == "PR1_PENDING"
    assert "Backend / PostgreSQL" in waiting.message
    assert coordinator.github_adapter.get_check_run_status.call_args.kwargs == {
        "repository": "silverberdi/boxio",
        "head_sha": "a" * 40,
        "check_name": "Backend / PostgreSQL",
    }


@pytest.mark.asyncio
async def test_pr_merge_advances_only_after_exact_sha_check_success():
    coordinator, uow = _coordinator(_result("a" * 40))
    run = SimpleNamespace(run_id="run-1", project_id="boxio", stop_details={})

    waiting = await coordinator._required_project_ci_before_merge(
        uow,
        run,
        repository="silverberdi/boxio",
        candidate_sha="a" * 40,
    )

    assert waiting is None


def test_proposal_feasibility_receives_safe_project_test_and_ci_configuration(tmp_path: Path):
    change = tmp_path / "openspec" / "changes" / "db-check"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text("## Tasks\n- [ ] 1.1 Run the DB test\n", encoding="utf-8")
    adapter = SimpleNamespace(
        show_change=lambda *_: {
            "deltas": [
                {
                    "spec": "db-check",
                    "requirements": [
                        {"id": "1", "scenarios": [{"rawText": "Scenario: database test is feasible"}]}
                    ],
                }
            ]
        },
        planning_status=lambda *_: {"status": "PASS"},
        validate_change_strict=lambda *_: {"status": "PASS"},
    )
    profile = ProjectTestDatabase(
        host="db.example.test",
        port=5432,
        database_name="boxio_test",
        production_database_names=["boxio_prod"],
        url_env="BOXIO_TEST_DATABASE_URL",
    )
    project = SimpleNamespace(
        project_id="boxio",
        openspec_path="openspec",
        checks=[
            {
                "name": "db-tests",
                "command": "npm test",
                "uses_test_database": True,
                "pr_ci_check_name": "Backend / PostgreSQL",
            }
        ],
        test_database=profile,
        agent_profiles={
            "thinking": {"agent_id": "codex", "provider_id": "codex"},
            "execution": {"agent_id": "codex", "provider_id": "codex"},
        },
    )
    evaluator = ProposalFeasibilityEvaluator(
        adapter, SimpleNamespace(resolve_workflow=lambda **_: object())
    )

    inputs = evaluator.collect_inputs(
        worktree_path=tmp_path,
        change_name="db-check",
        project=project,
        candidate_sha="a" * 40,
        candidate_clean=True,
        preview_sessions=None,
        thinker_provider="codex",
        implementer_provider="codex",
    )

    tooling = inputs["test_tooling"]
    assert tooling["project_test_database"] == profile.model_dump(mode="json")
    assert tooling["configured_checks"][0]["pr_ci_check_name"] == "Backend / PostgreSQL"
    assert "project:ci_check:Backend / PostgreSQL" in {
        item["ref"] for item in inputs["capabilities"]
    }
    assert "password" not in str(tooling)


def test_ci_deferral_requires_existing_workflow_and_exact_mapped_check(tmp_path):
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\n", encoding="utf-8")
    inputs = {
        "status": "READY",
        "candidate_sha": "a" * 40,
        "change_name": "req-466",
        "openspec_path": "openspec",
        "tasks": [{"task_id": "1.1", "text": "Run database integration test"}],
        "scenarios": [],
        "capabilities": [
            {"ref": "profile:execution", "available": True},
            {"ref": "project:test_database", "available": True},
            {"ref": "project:ci_check:Backend / PostgreSQL", "available": True},
            {"ref": "path:.github/workflows/ci.yml", "available": True},
        ],
    }
    report = {
        "tasks": [
            {
                "task_id": "1.1",
                "actor": "project_ci_cd",
                "execution_stage": "pre_pr",
                "capability_evidence_refs": [
                    "project:test_database",
                    "project:ci_check:Backend / PostgreSQL",
                    "path:.github/workflows/ci.yml",
                ],
                "depends_on_task_ids": [],
                "preconditions": [],
                "completion_evidence": "Exact GitHub check conclusion for the candidate head SHA",
            }
        ],
        "scenario_coverage": [],
        "blockers": [],
        "resolution_options": [],
    }

    status, _, _, blockers, _ = ProposalFeasibilityEvaluator.validate_report(
        report, inputs, tmp_path
    )

    assert status == "EXECUTABLE"
    assert blockers == ()

    unmapped = dict(report)
    unmapped["tasks"] = [dict(report["tasks"][0], capability_evidence_refs=["path:.github/workflows/ci.yml"])]
    status, _, _, blockers, _ = ProposalFeasibilityEvaluator.validate_report(
        unmapped, inputs, tmp_path
    )
    assert status == "BLOCKED"
    assert any("exact project CI check mapping" in blocker for blocker in blockers)
