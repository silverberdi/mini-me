from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import OrchestrationStage
from minime.domain.models import OrchestrationRun
from minime.services.agent_runner import AgentExecutionResult, CliAgentRunner
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeInfo, WorktreeManager


@pytest.fixture
def mock_env(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    # Create dummy workflow files in worktree
    agent_dir = repo_dir / ".agent" / "workflows"
    agent_dir.mkdir(parents=True)
    for op in ["opsx-explore.md", "opsx-propose.md", "opsx-apply.md", "opsx-verify.md", "opsx-sync.md", "opsx-archive.md"]:
        (agent_dir / op).write_text(f"# {op}")

    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow,
        "proj-1",
        repo_dir,
        managed_root,
        canonical_repository_identity="github.com/org/proj-1",
    )

    from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
    from minime.domain.models import ExternalActionResult

    github_mock = MagicMock()
    def mock_list_issues(repo, state="open", limit=None):
        return ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=[
                {
                    "number": 101,
                    "title": "Add caching layer",
                    "body": "We need redis caching layer",
                    "labels": [{"name": "backend"}],
                    "created_at": "2026-10-20T10:00:00Z",
                    "updated_at": "2026-10-20T10:00:00Z",
                    "html_url": "https://github.com/org/proj-1/issues/101",
                }
            ],
        )
    github_mock.list_issues.side_effect = mock_list_issues

    wt_manager = WorktreeManager(repo_dir, uow=uow)
    wt_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=repo_dir, branch_name="request-101-add-caching-layer", base_sha="abc1234")
    )
    wt_manager.create_documentation_worktree = AsyncMock(
        return_value=WorktreeInfo(path=repo_dir, branch_name="doc-close-101-add-caching-layer", base_sha="def5678")
    )

    agent_runner = CliAgentRunner()

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=github_mock,
        worktree_manager=wt_manager,
        agent_runner=agent_runner,
    )
    return coordinator, uow, github_mock, repo_dir


@pytest.mark.asyncio
async def test_propose_lifecycle_explore_and_propose(mock_env):
    coordinator, uow, github_mock, repo_dir = mock_env

    # Configure runner to create proposal artifacts on propose dispatch
    async def mock_agent_run(worktree_path, prompt_context, **kwargs):
        from minime.services.agent_runner import AgentExecutionResult
        if "Execute official OpenSpec Propose" in prompt_context:
            change_dir = worktree_path / "openspec" / "changes" / "req-101-add-caching-layer"
            change_dir.mkdir(parents=True, exist_ok=True)
            (change_dir / "proposal.md").write_text("# Proposal\nAdd caching layer")
            (change_dir / "tasks.md").write_text("## Tasks\n- [ ] 1.1 Add caching")
            specs_dir = change_dir / "specs" / "feature"
            specs_dir.mkdir(parents=True, exist_ok=True)
            (specs_dir / "spec.md").write_text("## Spec\nCaching spec")
        return AgentExecutionResult(
            exit_code=0,
            timed_out=False,
            stdout=["Done"],
            stderr=[],
            duration_ms=10,
        )

    coordinator.agent_runner.run = AsyncMock(side_effect=mock_agent_run)
    coordinator.openspec_adapter.validate_change_strict = MagicMock(return_value={"status": "PASS", "returncode": 0})

    # Test Explore & Propose execution
    result = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )

    assert result.status in ("COMPLETED", "HUMAN_REQUIRED", "PAUSED")
    # Verify change artifacts created
    change_dir = repo_dir / "openspec" / "changes" / "req-101-add-caching-layer"
    assert (change_dir / "proposal.md").exists() or (repo_dir / "openspec" / "archive" / "req-101-add-caching-layer").exists()


@pytest.mark.asyncio
async def test_propose_lifecycle_human_required_ambiguity(mock_env):
    coordinator, uow, github_mock, repo_dir = mock_env
    from minime.services.agent_runner import AgentExecutionResult
    coordinator.agent_runner.run = AsyncMock(return_value=AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=["HUMAN REQUIRED\n- Opción A\n- Opción B"],
        stderr=[],
        duration_ms=1,
    ))

    from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety
    from minime.domain.models import ExternalActionResult

    github_mock.list_issues.side_effect = lambda repo, state="open", limit=None: ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=[
            {
                "number": 102,
                "title": "Unclear architectural requirement",
                "body": "Material ambiguity: HUMAN REQUIRED to choose architecture",
                "labels": [],
                "created_at": "2026-10-20T10:00:00Z",
                "updated_at": "2026-10-20T10:00:00Z",
                "html_url": "https://github.com/org/proj-1/issues/102",
            }
        ],
    )

    result = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )

    assert result.status == "HUMAN_REQUIRED"
    assert result.current_stage == OrchestrationStage.EXPLORING
    assert result.human_payload is not None
    assert "pregunta" in result.human_payload.get("question", "").lower() or "¿" in result.human_payload.get("question", "")


@pytest.mark.asyncio
async def test_complexity_evaluation_uses_structured_agent_result(mock_env):
    coordinator, _, _, _ = mock_env
    from minime.services.agent_runner import AgentExecutionResult
    coordinator.agent_runner.run = AsyncMock(return_value=AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=['{"complexity":"high","evidence":"cross-cutting architectural impact"}'],
        stderr=[],
        duration_ms=1,
    ))
    result = await coordinator._assess_complexity(
        _, "antigravity", "Small typo", "breaking migration words", "proj-1"
    )
    assert result.status == "VALID"
    assert result.complexity == "high"


@pytest.mark.asyncio
async def test_resume_validating_reuses_existing_proposal_without_propose(mock_env):
    coordinator, uow, _, repo_dir = mock_env
    change_name = "req-101-add-caching-layer"
    change_dir = repo_dir / "openspec" / "changes" / change_name
    (change_dir / "specs" / "feature").mkdir(parents=True)
    for name in ("proposal.md", "design.md", "tasks.md"):
        (change_dir / name).write_text("# existing")
    (change_dir / "specs" / "feature" / "spec.md").write_text("# existing")
    uow.orchestration_runs.save(
        OrchestrationRun(
            project_id="proj-1",
            change_name=change_name,
            base_sha="abc1234",
            current_stage=OrchestrationStage.VALIDATING,
            resumable_stage=OrchestrationStage.VALIDATING,
        )
    )
    coordinator.openspec_adapter.validate_change_strict = MagicMock(
        return_value={"status": "PASS", "returncode": 0}
    )
    coordinator._run_propose = AsyncMock(side_effect=AssertionError("propose must not repeat"))
    coordinator.agent_runner.run = AsyncMock(return_value=AgentExecutionResult(
        exit_code=0,
        timed_out=False,
        stdout=['{"complexity":"low","evidence":"one focused change"}'],
        stderr=[],
        duration_ms=1,
    ))
    coordinator._run_apply = AsyncMock(return_value=False)

    result = await coordinator.execute_project_request(
        "proj-1", thinker_provider="antigravity", implementer_provider="antigravity", reviewer_provider="antigravity"
    )

    assert result.status == "PAUSED"
    coordinator._run_propose.assert_not_awaited()
    assert uow.orchestration_runs.list_runs(project_id="proj-1")[0].run_id


@pytest.mark.asyncio
async def test_explore_failed_blocks_propose(mock_env):
    coordinator, _, _, _ = mock_env
    coordinator.agent_runner.run = AsyncMock(return_value=AgentExecutionResult(
        exit_code=2,
        timed_out=False,
        stdout=[],
        stderr=["explore failed"],
        duration_ms=1,
    ))
    coordinator._run_propose = AsyncMock(side_effect=AssertionError("failed Explore must block Propose"))

    result = await coordinator.execute_project_request(
        "proj-1", thinker_provider="antigravity", implementer_provider="antigravity", reviewer_provider="antigravity"
    )

    assert result.status == "PAUSED"
    assert result.current_stage == OrchestrationStage.EXPLORING
    coordinator._run_propose.assert_not_awaited()
