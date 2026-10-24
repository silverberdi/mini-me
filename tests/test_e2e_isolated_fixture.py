import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture
from minime.domain.enums import OrchestrationStage, ExternalOutcome, ExternalReasonCode, RetrySafety
from minime.domain.models import OrchestrationRun, ExternalActionResult
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.agent_runner import CliAgentRunner
from minime.services.worktree_manager import WorktreeManager, WorktreeInfo


@pytest.fixture
def isolated_fixture_repo(tmp_path: Path):
    fixture_repo = tmp_path / "mini-me-fixture"
    fixture_repo.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    # Install workflows in fixture repo
    agent_dir = fixture_repo / ".agent" / "workflows"
    agent_dir.mkdir(parents=True)
    for op in ["opsx-explore.md", "opsx-propose.md", "opsx-apply.md", "opsx-verify.md", "opsx-sync.md", "opsx-archive.md"]:
        (agent_dir / op).write_text(f"---\nname: {op}\n---\n# {op}")

    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow,
        "fixture-project",
        fixture_repo,
        managed_root,
        canonical_repository_identity="github.com/silverberdi/mini-me-fixture",
    )

    github_mock = MagicMock()
    github_mock.create_pull_request = AsyncMock(side_effect=[
        {"number": 51, "html_url": "https://github.com/silverberdi/mini-me-fixture/pull/51"},
        {"number": 52, "html_url": "https://github.com/silverberdi/mini-me-fixture/pull/52"},
    ])
    github_mock.merge_pull_request = AsyncMock(return_value={"merged": True, "sha": "merged_sha_fixture"})
    github_mock.close_issue = AsyncMock(return_value={"closed": True})

    wt_manager = WorktreeManager(fixture_repo, uow=uow)
    candidate_wt = managed_root / "request-501-moderate-feature"
    candidate_wt.mkdir(parents=True, exist_ok=True)
    wt_agent_dir = candidate_wt / ".agent" / "workflows"
    wt_agent_dir.mkdir(parents=True, exist_ok=True)
    for op in ["opsx-explore.md", "opsx-propose.md", "opsx-apply.md", "opsx-verify.md", "opsx-sync.md", "opsx-archive.md"]:
        (wt_agent_dir / op).write_text(f"---\nname: {op}\n---\n# {op}")

    doc_wt = managed_root / "doc-close-501-moderate-feature"
    doc_wt.mkdir(parents=True, exist_ok=True)
    doc_agent_dir = doc_wt / ".agent" / "workflows"
    doc_agent_dir.mkdir(parents=True, exist_ok=True)
    for op in ["opsx-explore.md", "opsx-propose.md", "opsx-apply.md", "opsx-verify.md", "opsx-sync.md", "opsx-archive.md"]:
        (doc_agent_dir / op).write_text(f"---\nname: {op}\n---\n# {op}")

    wt_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=candidate_wt, branch_name="request-501-moderate-feature", base_sha="sha_base")
    )
    wt_manager.create_documentation_worktree = AsyncMock(
        return_value=WorktreeInfo(path=doc_wt, branch_name="doc-close-501-moderate-feature", base_sha="sha_merged")
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
    coordinator._get_git_head_sha = AsyncMock(return_value="commit_sha_fixture_123")
    coordinator._git_run = AsyncMock(return_value="")

    return coordinator, uow, github_mock, candidate_wt, doc_wt


@pytest.mark.asyncio
async def test_e2e_moderate_complexity_full_cycle(isolated_fixture_repo):
    """E2E Test 6.3: Low/Moderate complexity full cycle in isolated repository."""
    coordinator, uow, github_mock, candidate_wt, doc_wt = isolated_fixture_repo

    github_mock.list_issues.side_effect = lambda repo, state="open", limit=None: ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=[
            {
                "number": 501,
                "title": "Add telemetry exporter",
                "body": "Standard telemetry exporter for metrics",
                "labels": [{"name": "enhancement"}],
                "created_at": "2026-10-24T10:00:00Z",
                "updated_at": "2026-10-24T10:00:00Z",
                "html_url": "https://github.com/silverberdi/mini-me-fixture/issues/501",
            }
        ],
    )

    result = await coordinator.execute_project_request(
        "fixture-project",
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )

    assert result.status == "COMPLETED"
    assert result.current_stage == OrchestrationStage.COMPLETED
    assert result.pr1_url == "https://github.com/silverberdi/mini-me-fixture/pull/51"
    assert result.pr2_url == "https://github.com/silverberdi/mini-me-fixture/pull/52"

    # Verify both PRs created, PR1 auto-merged without human intervention, and issue closed
    assert github_mock.create_pull_request.call_count == 2
    assert github_mock.merge_pull_request.call_count == 2
    from unittest.mock import ANY
    github_mock.close_issue.assert_called_once_with(
        repository=ANY,
        issue_number=501,
        comment=ANY,
    )


@pytest.mark.asyncio
async def test_e2e_high_complexity_full_cycle_with_ack(isolated_fixture_repo):
    """E2E Test 6.4: High complexity full cycle requiring operator ack."""
    coordinator, uow, github_mock, candidate_wt, doc_wt = isolated_fixture_repo

    github_mock.list_issues.side_effect = lambda repo, state="open", limit=None: ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=[
            {
                "number": 502,
                "title": "Breaking change in architecture",
                "body": "High complexity architectural overhaul",
                "labels": [{"name": "breaking"}],
                "created_at": "2026-10-24T11:00:00Z",
                "updated_at": "2026-10-24T11:00:00Z",
                "html_url": "https://github.com/silverberdi/mini-me-fixture/issues/502",
            }
        ],
    )

    # First pass without ack -> HUMAN_REQUIRED
    res1 = await coordinator.execute_project_request(
        "fixture-project",
        operator_ack=False,
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )
    assert res1.status == "HUMAN_REQUIRED"
    assert res1.current_stage == OrchestrationStage.PR1_PENDING
    assert "Estoy enterado" in res1.human_payload.get("prompt", "")

    # Second pass with ack -> continues, merges PR1, doc close, merges PR2, closes issue
    res2 = await coordinator.execute_project_request(
        "fixture-project",
        operator_ack=True,
        thinker_provider="antigravity",
        implementer_provider="antigravity",
        reviewer_provider="antigravity",
    )
    assert res2.status == "COMPLETED"
    assert res2.current_stage == OrchestrationStage.COMPLETED
