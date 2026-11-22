from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from minime.domain.enums import OrchestrationStage
from minime.domain.models import OrchestrationRun
from minime.services.agent_runner import AgentExecutionResult
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture


@pytest.fixture
def test_setup(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow,
        "proj-1",
        repo_dir,
        managed_root,
        canonical_repository_identity="github.com/org/proj-1",
    )

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        worktree_manager=MagicMock(),
        github_adapter=MagicMock(),
        agent_runner=MagicMock(),
        openspec_adapter=MagicMock(),
        max_correction_attempts=2,
    )
    return uow, coordinator, tmp_path


@pytest.mark.asyncio
async def test_run_propose_returns_ready_to_validate_when_artifacts_present_despite_error(test_setup):
    uow, coordinator, tmp_path = test_setup
    worktree = tmp_path / "worktree"
    change_dir = worktree / "openspec" / "changes" / "my-change"
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text("# Proposal")
    (change_dir / "design.md").write_text("# Design")
    (change_dir / "tasks.md").write_text("# Tasks")
    specs_dir = change_dir / "specs"
    specs_dir.mkdir()
    (specs_dir / "spec.md").write_text("# Spec")

    # Mock agent execution returning exit_code 1 (e.g. strict validate failed inside agent)
    failed_result = AgentExecutionResult(
        stdout=["Validation failed"],
        stderr=["Scenario missing"],
        exit_code=1,
        timed_out=False,
        duration_ms=10,
    )
    coordinator.agent_runner.run = AsyncMock(return_value=failed_result)
    coordinator.agent_runner.resolve_workflow = MagicMock(return_value=MagicMock(dispatch_command="opsx propose"))

    res = await coordinator._run_propose(
        worktree_path=worktree,
        provider="codex",
        change_name="my-change",
        issue_number=14,
        issue_title="Test Issue",
        issue_body="Test Body",
    )

    assert res["status"] == "READY_TO_VALIDATE"
    assert res["execution"] == failed_result


@pytest.mark.asyncio
async def test_validation_failure_triggers_correction_loop(test_setup):
    uow, coordinator, tmp_path = test_setup
    worktree = tmp_path / "worktree"
    change_name = "req-101-test-issue"
    change_dir = worktree / "openspec" / "changes" / change_name
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text("# Proposal")
    (change_dir / "design.md").write_text("# Design")
    (change_dir / "tasks.md").write_text("# Tasks")
    specs_dir = change_dir / "specs"
    specs_dir.mkdir()
    (specs_dir / "spec.md").write_text("# Spec")

    run = OrchestrationRun(
        project_id="proj-1",
        change_name=change_name,
        base_sha="base123",
        current_stage=OrchestrationStage.VALIDATING,
        resumable_stage=OrchestrationStage.VALIDATING,
        stop_details={
            "issue_number": 101,
            "issue_title": "Test Issue",
            "request_normalization": {"normalized_body": "Test request body"},
        },
    )
    uow.orchestration_runs.save(run)

    coordinator.openspec_adapter.planning_status = MagicMock(return_value={"status": "PASS"})
    # First validation attempt fails, second passes
    coordinator.openspec_adapter.validate_change_strict = MagicMock(
        side_effect=[
            {"status": "FAIL", "stderr": "Scenario missing"},
            {"status": "PASS", "stderr": ""},
        ]
    )
    coordinator.worktree_manager.get_active_worktree = MagicMock(return_value=MagicMock(path=worktree))
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=MagicMock(path=worktree, branch="feature/req-101")
    )

    correction_called = False
    async def mock_correction(*args, **kwargs):
        nonlocal correction_called
        correction_called = True
        return True

    coordinator._run_propose_correction = AsyncMock(side_effect=mock_correction)
    coordinator._classify_complexity_with_fallback = AsyncMock(
        return_value=MagicMock(complexity="LOW", rationale="Straightforward")
    )
    coordinator.agent_runner.run = AsyncMock(
        return_value=AgentExecutionResult(
            stdout=['{"complexity": "low", "evidence": "Simple fix"}'],
            stderr=[],
            exit_code=0,
            timed_out=False,
            duration_ms=10,
        )
    )
    coordinator.agent_runner.resolve_workflow = MagicMock(return_value=MagicMock(dispatch_command="opsx propose"))
    coordinator._get_git_head_sha = AsyncMock(return_value="candidate_sha_123")
    coordinator._git_run = AsyncMock(return_value=MagicMock(exit_code=0, stdout="clean"))

    result = await coordinator.execute_project_request(
        "proj-1",
    )

    assert correction_called is True
    assert coordinator.openspec_adapter.validate_change_strict.call_count == 2

