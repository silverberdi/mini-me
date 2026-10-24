import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture
from minime.domain.enums import OrchestrationStage
from minime.domain.models import OrchestrationRun
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.agent_runner import CliAgentRunner, NativeOpenSpecWorkflowUnavailable
from minime.services.worktree_manager import WorktreeManager, WorktreeInfo


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

    from minime.domain.models import ExternalActionResult
    from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety

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

    from minime.domain.models import ExternalActionResult
    from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety

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
async def test_complexity_evaluation(mock_env):
    coordinator, _, _, _ = mock_env
    assert coordinator._evaluate_complexity("Small fix in typo", "Fix typo") == "low"
    assert coordinator._evaluate_complexity("Breaking change in auth migration", "Refactor Auth") == "high"
    assert coordinator._evaluate_complexity("Add standard endpoint", "Add endpoint") == "moderate"
