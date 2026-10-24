import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture
from minime.domain.enums import OrchestrationStage, ExternalOutcome, ExternalReasonCode, RetrySafety
from minime.domain.models import OrchestrationRun, ExternalActionResult
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.agent_runner import CliAgentRunner, NativeOpenSpecWorkflowUnavailable
from minime.services.worktree_manager import WorktreeManager, WorktreeInfo


@pytest.fixture
def mock_apply_env(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    # Create dummy workflow files in worktree for codex implementer
    skill_dir = repo_dir / ".agents" / "skills"
    for skill in ["openspec-explore", "openspec-propose", "openspec-apply-change", "openspec-verify-change", "openspec-sync-specs", "openspec-archive-change"]:
        d = skill_dir / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\n---\n# {skill}")

    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow,
        "proj-1",
        repo_dir,
        managed_root,
        canonical_repository_identity="github.com/org/proj-1",
    )

    github_mock = MagicMock()
    github_mock.list_issues.side_effect = lambda repo, state="open", limit=None: ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=[
            {
                "number": 201,
                "title": "Add analytics tracking",
                "body": "Track user interactions",
                "labels": [],
                "created_at": "2026-10-21T10:00:00Z",
                "updated_at": "2026-10-21T10:00:00Z",
                "html_url": "https://github.com/org/proj-1/issues/201",
            }
        ],
    )
    github_mock.create_pull_request = AsyncMock(return_value={"number": 1, "html_url": "https://github.com/org/proj-1/pull/1"})
    github_mock.merge_pull_request = AsyncMock(return_value={"merged": True, "sha": "merged_sha_123"})
    github_mock.close_issue = AsyncMock(return_value={"closed": True})

    wt_manager = WorktreeManager(repo_dir, uow=uow)
    wt_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=repo_dir, branch_name="request-201-add-analytics-tracking", base_sha="abc1234")
    )
    wt_manager.create_documentation_worktree = AsyncMock(
        return_value=WorktreeInfo(path=repo_dir, branch_name="doc-close-201-add-analytics-tracking", base_sha="def5678")
    )

    agent_runner = CliAgentRunner()

    openspec_mock = MagicMock()
    openspec_mock.validate_change_strict = MagicMock(return_value={"status": "PASS", "returncode": 0})

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=github_mock,
        worktree_manager=wt_manager,
        agent_runner=agent_runner,
        openspec_adapter=openspec_mock,
    )
    coordinator._push_branch = AsyncMock()
    coordinator._get_git_head_sha = AsyncMock(return_value="commit_head_1234")
    coordinator._git_run = AsyncMock(return_value="git_output")

    return coordinator, uow, github_mock, repo_dir


@pytest.mark.asyncio
async def test_apply_and_verify_success(mock_apply_env):
    coordinator, uow, github_mock, repo_dir = mock_apply_env

    result = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="codex",
        implementer_provider="codex",
        reviewer_provider="codex",
    )

    assert result.status == "COMPLETED"
    assert result.current_stage == OrchestrationStage.COMPLETED
    assert result.pr1_url == "https://github.com/org/proj-1/pull/1"


@pytest.mark.asyncio
async def test_apply_fails_closed_when_verify_workflow_missing(mock_apply_env):
    coordinator, uow, github_mock, repo_dir = mock_apply_env

    # Remove the verify skill from the repo
    import shutil
    verify_skill = repo_dir / ".agents" / "skills" / "openspec-verify-change"
    if verify_skill.exists():
        shutil.rmtree(str(verify_skill))

    result = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="codex",
        implementer_provider="codex",
        reviewer_provider="codex",
    )

    assert result.status == "PAUSED"
    assert "Missing native OpenSpec Verify workflow" in result.message
