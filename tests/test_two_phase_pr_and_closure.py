from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import ExternalOutcome, ExternalReasonCode, OrchestrationStage, RetrySafety
from minime.domain.models import ExternalActionResult
from minime.services.agent_runner import CliAgentRunner
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.pr_preparer_service import PrPreparationInput, PrPreparerService
from minime.services.worktree_manager import WorktreeInfo, WorktreeManager


def test_pr_preparer_service_strict_exclusion_of_auto_closing_keywords():
    service = PrPreparerService()

    # Valid implementation PR input
    inp = PrPreparationInput(
        project_id="proj-1",
        repository="org/repo",
        pr_type="implementation",
        issue_number=171,
        issue_title="Native OpenSpec orchestration",
        base_branch="main",
        candidate_branch="request-171-native-openspec-orchestration",
        candidate_sha="abc1234",
        change_name="gacela-03-openspec-y-revision",
        change_summary="Implemented orchestration coordinator and workflows",
        test_evidence="100% tests passed in pytest.",
        complexity="high",
    )
    prepared = service.prepare_pull_request(inp)
    assert "Addresses #171" in prepared.title or "Addresses #171" in prepared.body
    assert "Fixes #" not in prepared.title and "Fixes #" not in prepared.body
    assert "Closes #" not in prepared.title and "Closes #" not in prepared.body
    assert "Resolves #" not in prepared.title and "Resolves #" not in prepared.body

    # Valid documentation PR input
    doc_inp = PrPreparationInput(
        project_id="proj-1",
        repository="org/repo",
        pr_type="documentation",
        issue_number=171,
        issue_title="Native OpenSpec orchestration",
        base_branch="main",
        candidate_branch="doc-close-171-native-openspec-orchestration",
        candidate_sha="def5678",
        change_name="gacela-03-openspec-y-revision",
        change_summary="Sync and archive specs",
        test_evidence="Sync and archive successful.",
    )
    doc_prepared = service.prepare_pull_request(doc_inp)
    assert "Ref #171" in doc_prepared.title or "Ref #171" in doc_prepared.body
    assert "Fixes #" not in doc_prepared.title and "Fixes #" not in doc_prepared.body

    # Test rejection if someone tries to inject auto-closing keyword
    with pytest.raises(ValueError, match="Security violation: PR content contains prohibited auto-closing directive"):
        service.validate_no_auto_closing_keywords("This PR Closes #171 automatically.")


@pytest.mark.asyncio
async def test_two_phase_pr_high_complexity_differentiated_merge(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    # Set up dummy workflows
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
                "number": 301,
                "title": "High complexity architectural change",
                "body": "Breaking change in system core",
                "labels": [],
                "created_at": "2026-10-22T10:00:00Z",
                "updated_at": "2026-10-22T10:00:00Z",
                "html_url": "https://github.com/org/proj-1/issues/301",
            }
        ],
    )
    github_mock.create_pull_request = AsyncMock(return_value={"number": 10, "html_url": "https://github.com/org/proj-1/pull/10"})
    github_mock.merge_pull_request = AsyncMock(return_value={"merged": True, "sha": "merged_sha_301"})
    github_mock.close_issue = AsyncMock(return_value={"closed": True})

    wt_manager = WorktreeManager(repo_dir, uow=uow)
    wt_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=repo_dir, branch_name="request-301-high-complexity", base_sha="sha1")
    )
    wt_manager.create_documentation_worktree = AsyncMock(
        return_value=WorktreeInfo(path=repo_dir, branch_name="doc-close-301-high-complexity", base_sha="sha2")
    )

    agent_runner = CliAgentRunner()
    openspec_mock = MagicMock()
    openspec_mock.planning_status = MagicMock(return_value={"status": "PASS", "pending": []})
    openspec_mock.validate_change_strict = MagicMock(return_value={"status": "PASS", "returncode": 0})

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=github_mock,
        worktree_manager=wt_manager,
        agent_runner=agent_runner,
        openspec_adapter=openspec_mock,
    )
    coordinator._push_branch = AsyncMock()
    coordinator._get_git_head_sha = AsyncMock(return_value="commit_head_301")
    coordinator._git_run = AsyncMock(return_value="")

    # Explore must fail closed before any proposal or merge gate when no evidenced
    # agent result is available.
    res1 = await coordinator.execute_project_request(
        "proj-1",
        operator_ack=False,
        thinker_provider="codex",
        implementer_provider="codex",
        reviewer_provider="codex",
    )
    assert res1.status == "PAUSED"
    assert res1.current_stage == OrchestrationStage.EXPLORING

    # Acknowledgement cannot bypass the failed Explore stage.
    res2 = await coordinator.execute_project_request(
        "proj-1",
        operator_ack=True,
        thinker_provider="codex",
        implementer_provider="codex",
        reviewer_provider="codex",
    )
    assert res2.status == "PAUSED"
    assert res2.current_stage == OrchestrationStage.EXPLORING
