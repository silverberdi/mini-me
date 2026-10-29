"""Deterministic negative regression tests for fail-closed orchestration behavior."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import ExternalOutcome, ExternalReasonCode, OrchestrationStage, RetrySafety
from minime.domain.models import ExternalActionResult
from minime.services.agent_runner import (
    AgentExecutionResult,
    CliAgentRunner,
)
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeInfo, WorktreeManager


@pytest.fixture
def base_coordinator_env(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    # Install workflows for both codex (.agents/skills) and antigravity (.agent/workflows)
    skill_dir = repo_dir / ".agents" / "skills"
    for skill in [
        "openspec-explore",
        "openspec-propose",
        "openspec-apply-change",
        "openspec-verify-change",
        "openspec-sync-specs",
        "openspec-archive-change",
    ]:
        d = skill_dir / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\n---\n# {skill}")

    wf_dir = repo_dir / ".agent" / "workflows"
    wf_dir.mkdir(parents=True)
    for op in [
        "opsx-explore.md",
        "opsx-propose.md",
        "opsx-apply.md",
        "opsx-verify.md",
        "opsx-sync.md",
        "opsx-archive.md",
    ]:
        (wf_dir / op).write_text(f"---\nname: {op}\n---\n# {op}")

    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow,
        "proj-test",
        repo_dir,
        managed_root,
        canonical_repository_identity="github.com/org/proj-test",
    )

    github_mock = MagicMock()
    github_mock.list_issues.side_effect = lambda repo, state="open", limit=None: (
        ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=[
                {
                    "number": 901,
                    "title": "Negative test feature",
                    "body": "Testing negative regression cases",
                    "labels": [],
                    "created_at": "2026-10-24T10:00:00Z",
                    "updated_at": "2026-10-24T10:00:00Z",
                    "html_url": "https://github.com/org/proj-test/issues/901",
                }
            ],
        )
    )
    github_mock.create_pull_request = AsyncMock(
        return_value=ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data={"number": 1, "html_url": "https://github.com/org/proj-test/pull/1"},
        )
    )
    github_mock.get_pull_request_details = lambda repository, pr_number: ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data={
            "number": pr_number,
            "state": "open",
            "head_sha": "a" * 40,
            "head_branch": "request-901-negative-test-feature",
            "base_branch": "main",
            "is_merged": False,
        },
    )
    github_mock.merge_pull_request = AsyncMock(
        return_value={"merged": True, "sha": "sha_pr_merged"}
    )
    github_mock.close_issue = AsyncMock(return_value={"closed": True})

    candidate_wt = managed_root / "request-901-negative-test-feature"
    candidate_wt.mkdir(parents=True, exist_ok=True)
    c_skills = candidate_wt / ".agents" / "skills"
    for skill in [
        "openspec-explore",
        "openspec-propose",
        "openspec-apply-change",
        "openspec-verify-change",
        "openspec-sync-specs",
        "openspec-archive-change",
    ]:
        d = c_skills / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\n---\n# {skill}")

    c_wf = candidate_wt / ".agent" / "workflows"
    c_wf.mkdir(parents=True)
    for op in [
        "opsx-explore.md",
        "opsx-propose.md",
        "opsx-apply.md",
        "opsx-verify.md",
        "opsx-sync.md",
        "opsx-archive.md",
    ]:
        (c_wf / op).write_text(f"---\nname: {op}\n---\n# {op}")

    wt_manager = WorktreeManager(repo_dir, uow=uow)
    wt_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_wt, branch_name="request-901-negative-test-feature", base_sha="sha_base"
        )
    )
    wt_manager.create_documentation_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_wt, branch_name="doc-close-901-negative-test-feature", base_sha="sha_doc"
        )
    )

    for ch_name in ("req-901-negative-test-feature", "req-901-breaking-overhaul"):
        ch_dir = candidate_wt / "openspec" / "changes" / ch_name
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / "proposal.md").write_text("# Proposal")
        (ch_dir / "design.md").write_text("# Design")
        (ch_dir / "tasks.md").write_text("- [x] 1.1 Complete task")
        (ch_dir / "specs" / "feature").mkdir(parents=True, exist_ok=True)
        (ch_dir / "specs" / "feature" / "spec.md").write_text("# Spec")

    agent_runner = CliAgentRunner()

    async def successful_agent_run(*, prompt_context, **kwargs):
        output = "READY_TO_PROPOSE\nnative workflow evidence"
        if "Assess this Request's implementation complexity" in prompt_context:
            level = "high" if "breaking" in prompt_context.lower() else "low"
            output = f'{{"complexity":"{level}","evidence":"scope assessed by thinking agent"}}'
        elif "review" in prompt_context.lower() or "Verify" in prompt_context:
            output = '{"verdict":"READY_TO_MERGE","summary":"verified","findings":[]}'
        return AgentExecutionResult(
            exit_code=0, timed_out=False, stdout=[output], stderr=[], duration_ms=1
        )

    agent_runner.run = successful_agent_run
    openspec_mock = MagicMock()
    openspec_mock.planning_status = MagicMock(return_value={"status": "PASS", "pending": []})
    openspec_mock.validate_change_strict = MagicMock(
        return_value={"status": "PASS", "returncode": 0}
    )

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=github_mock,
        worktree_manager=wt_manager,
        agent_runner=agent_runner,
        openspec_adapter=openspec_mock,
    )
    coordinator._push_branch = AsyncMock()
    coordinator._get_git_head_sha = AsyncMock(return_value="a" * 40)
    coordinator._git_run = AsyncMock(return_value="")

    return coordinator, uow, github_mock, candidate_wt, agent_runner, openspec_mock


@pytest.mark.asyncio
async def test_negative_missing_verify_workflow_fails_closed(base_coordinator_env):
    """Case 1: Missing verify workflow halts before Apply."""
    coordinator, uow, github_mock, candidate_wt, agent_runner, openspec_mock = base_coordinator_env
    # Remove verify skill
    import shutil

    shutil.rmtree(
        candidate_wt / ".agents" / "skills" / "openspec-verify-change", ignore_errors=True
    )
    shutil.rmtree(candidate_wt / ".agent" / "workflows" / "opsx-verify.md", ignore_errors=True)

    res = await coordinator.execute_project_request(
        "proj-test",
        thinker_provider="codex",
        implementer_provider="codex",
        reviewer_provider="codex",
    )
    assert res.status == "PAUSED"
    assert "Missing native OpenSpec Verify workflow" in res.message


@pytest.mark.asyncio
async def test_negative_automated_tests_failure_fails_closed(base_coordinator_env):
    """Case 2: Automated tests failure halts before PR1."""
    coordinator, uow, github_mock, candidate_wt, agent_runner, openspec_mock = base_coordinator_env
    coordinator._run_automated_tests = AsyncMock(
        return_value=(False, "FAILED tests/test_core.py::test_fail - AssertionError")
    )

    res = await coordinator.execute_project_request(
        "proj-test",
        thinker_provider="codex",
        implementer_provider="codex",
        reviewer_provider="codex",
    )
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.RUNNING_TESTS
    assert "Automated tests failed during Apply" in res.message
    assert github_mock.create_pull_request.call_count == 0


@pytest.mark.asyncio
async def test_negative_verify_discrepancy_fails_closed(base_coordinator_env):
    """Case 3: Verify reporting discrepancies fails closed before PR1."""
    coordinator, uow, github_mock, candidate_wt, agent_runner, openspec_mock = base_coordinator_env
    coordinator._run_automated_tests = AsyncMock(return_value=(True, "Tests passed"))
    coordinator._run_verify = AsyncMock(return_value=False)

    res = await coordinator.execute_project_request(
        "proj-test",
        thinker_provider="codex",
        implementer_provider="codex",
        reviewer_provider="codex",
    )
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.VERIFYING
    assert "OpenSpec verify reported discrepancies" in res.message
    assert github_mock.create_pull_request.call_count == 0


@pytest.mark.asyncio
async def test_negative_code_review_rejection_fails_closed(base_coordinator_env):
    """Case 4: Code review rejection on high complexity halts before PR1."""
    coordinator, uow, github_mock, candidate_wt, agent_runner, openspec_mock = base_coordinator_env
    coordinator._run_automated_tests = AsyncMock(return_value=(True, "Tests passed"))
    coordinator._run_verify = AsyncMock(return_value=True)
    coordinator._run_code_review = AsyncMock(return_value=False)

    github_mock.list_issues.side_effect = lambda repo, state="open", limit=None: (
        ExternalActionResult(
            outcome=ExternalOutcome.SUCCESS,
            source_adapter="github",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.SAFE,
            data=[
                {
                    "number": 901,
                    "title": "Breaking overhaul",
                    "body": "High complexity architectural breaking change overhaul",
                    "labels": [{"name": "breaking"}],
                    "created_at": "2026-10-24T10:00:00Z",
                    "updated_at": "2026-10-24T10:00:00Z",
                    "html_url": "https://github.com/org/proj-test/issues/901",
                }
            ],
        )
    )

    res = await coordinator.execute_project_request(
        "proj-test",
        thinker_provider="codex",
        implementer_provider="codex",
        reviewer_provider="codex",
    )
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.CODE_REVIEW
    assert "Independent code review requested changes" in res.message
    assert github_mock.create_pull_request.call_count == 0


@pytest.mark.asyncio
async def test_negative_pr1_merge_failure_pauses(base_coordinator_env):
    """Case 5: PR1 merge failure pauses in PR1_PENDING preserving worktree."""
    coordinator, uow, github_mock, candidate_wt, agent_runner, openspec_mock = base_coordinator_env
    coordinator._run_automated_tests = AsyncMock(return_value=(True, "Tests passed"))
    coordinator._run_verify = AsyncMock(return_value=True)
    github_mock.merge_pull_request = AsyncMock(
        return_value={"merged": False, "message": "Required check missing"}
    )

    res = await coordinator.execute_project_request(
        "proj-test",
        thinker_provider="codex",
        implementer_provider="codex",
        reviewer_provider="codex",
    )
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.PR1_PENDING
    assert "Failed to merge PR1" in res.message
    assert candidate_wt.exists()
