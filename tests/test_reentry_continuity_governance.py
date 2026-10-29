from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import ExternalOutcome, ExternalReasonCode, OrchestrationStage, RetrySafety
from minime.domain.models import ExternalActionResult, OrchestrationRun
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeInfo


@pytest.fixture
def base_setup(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    candidate_worktree = managed_root / "request-173-gacela-05-ui-self-hosted"
    candidate_worktree.mkdir(parents=True, exist_ok=True)
    change_dir = candidate_worktree / "openspec" / "changes" / "gacela-05-ui-self-hosted"
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text("# Proposal\nValid proposal")
    (change_dir / "design.md").write_text("# Design\nValid design")
    (change_dir / "tasks.md").write_text("# Tasks\n- [ ] Task 1")

    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow,
        "mini-me",
        repo_dir,
        managed_root,
        canonical_repository_identity="github.com/silverberdi/mini-me",
    )
    return uow, candidate_worktree, change_dir

def make_stop_details(extra=None):
    details = {
        "issue_number": 173,
        "issue_title": "UI self hosted",
        "request_normalization": {
            "normalized_body": "OpenSpec: `gacela-05-ui-self-hosted`\nDescription of F5 UI self hosted."
        },
        "complexity": "high",
    }
    if extra:
        details.update(extra)
    return details

def make_mock_execution(output: str, exit_code: int = 0):
    return MagicMock(
        exit_code=exit_code,
        timed_out=False,
        preflight_error=None,
        environment_error=False,
        structured_output_missing=False,
        structured_output_too_large=False,
        workflow_handoff_required=False,
        final_response_status="COMPLETE",
        response_output=output,
        error_message=None if exit_code == 0 else "Execution error",
    )

@pytest.mark.asyncio
async def test_reentry_proposal_review_no_approval_pauses(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-1",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details(),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123")
    )
    mock_res = make_mock_execution("", exit_code=1)
    mock_res.error_message = "Model quota exhausted"
    coordinator.agent_runner.run = AsyncMock(return_value=mock_res)

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.PROPOSAL_REVIEW
    assert "Independent proposal review provider failed: Model quota exhausted" in res.message

@pytest.mark.asyncio
async def test_reentry_proposal_review_valid_approval_advances(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    current_hashes = NativeOrchestrationCoordinator._compute_proposal_artifacts_hashes(
        candidate_worktree, "gacela-05-ui-self-hosted"
    )
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-2",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details({
            "proposal_review": {
                "status": "approved",
                "verdict": "READY_TO_MERGE",
                "artifact_hashes": current_hashes,
                "reviewer_provider": "antigravity",
                "reviewer_model": "gemini-3.8-flash-medium",
            },
        }),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123")
    )
    # Pause right after advancing to READY_TO_APPLY
    coordinator._run_apply = AsyncMock(return_value=False)

    await coordinator.execute_project_request("mini-me")
    # It must have advanced past PROPOSAL_REVIEW to IMPLEMENTING
    updated_run = uow.orchestration_runs.get_by_id("run-test-2")
    assert updated_run.current_stage == OrchestrationStage.IMPLEMENTING
    # Agent runner was NOT invoked for proposal review
    coordinator.agent_runner.run.assert_not_called()

@pytest.mark.asyncio
async def test_reentry_proposal_review_ambiguous_dispatch_requires_auth(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-3",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details({
            "proposal_review": {
                "status": "dispatched",
                "attempt_id": "prev-attempt-1",
            },
        }),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123")
    )

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.PROPOSAL_REVIEW
    assert "recovery authorization is required" in res.message
    coordinator.agent_runner.run.assert_not_called()

@pytest.mark.asyncio
async def test_reentry_code_review_no_approval_pauses(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-4",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.CODE_REVIEW,
        stop_details=make_stop_details(),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123")
    )
    coordinator._get_git_head_sha = AsyncMock(return_value="sha123456")
    coordinator._git_run = AsyncMock(return_value=MagicMock(stdout="diff content"))
    mock_res = make_mock_execution(
        '```json\n{"verdict":"CHANGES_REQUIRED","summary":"Fix lints","findings":[{"severity":"MAJOR","location":"file.py","violated_requirement":"R1","expected_correction":"Fix it"}]}\n```'
    )
    coordinator.agent_runner.run = AsyncMock(return_value=mock_res)

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.CODE_REVIEW
    assert "Independent code review requested changes: Fix lints" in res.message

@pytest.mark.asyncio
async def test_pr1_entry_gate_rejects_premature_stage(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-5",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.IMPLEMENTING,
        stop_details=make_stop_details(),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123")
    )
    coordinator._run_apply = AsyncMock(return_value=False)

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "PAUSED"
    # Never jumped to PR1_PENDING
    assert res.current_stage == OrchestrationStage.IMPLEMENTING
    assert "Native Apply failed" in res.message

@pytest.mark.asyncio
async def test_pr1_reentry_with_existing_pr_skips_commit(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-6",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PR1_PENDING,
        stop_details=make_stop_details({"pr1_number": 195, "pr1_url": "https://github.com/org/repo/pull/195", "complexity": "high"}),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123")
    )
    coordinator._ensure_candidate_commit = AsyncMock()
    coordinator._get_git_head_sha = AsyncMock(return_value="sha999")
    coordinator._confirm_pr_merged = AsyncMock(return_value=False)
    coordinator._get_pr_merge_status = AsyncMock(return_value=False)
    coordinator._has_human_merge_approval = MagicMock(return_value=False)

    res = await coordinator.execute_project_request("mini-me")
    # In PR1_PENDING without human approval, it correctly reports HUMAN_REQUIRED for merge
    assert res.status == "HUMAN_REQUIRED"
    assert res.current_stage == OrchestrationStage.PR1_PENDING
    # ensure_candidate_commit was NOT called because PR already exists
    coordinator._ensure_candidate_commit.assert_not_called()

@pytest.mark.asyncio
async def test_doc_closing_reentry_with_existing_pr2_skips_worktree_recreation(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-7",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PR2_PENDING,
        stop_details=make_stop_details({
            "pr1_number": 195,
            "pr2_number": 196,
            "pr2_url": "https://github.com/org/repo/pull/196",
            "pr2_head_sha": "sha_doc_1",
        }),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123")
    )
    coordinator.worktree_manager.create_documentation_worktree = AsyncMock()
    coordinator.github_adapter.merge_pull_request = MagicMock(
        return_value=ExternalActionResult(
            outcome=ExternalOutcome.FAILURE,
            source_adapter="github",
            reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
            retry_safety=RetrySafety.UNSAFE,
            error_message="Protections blocked",
        )
    )
    coordinator._confirm_pr_merged = AsyncMock(return_value=False)

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.PR2_PENDING
    # create_documentation_worktree was NOT called because PR2 already exists
    coordinator.worktree_manager.create_documentation_worktree.assert_not_called()

@pytest.mark.asyncio
async def test_proposal_artifact_hash_change_invalidates_previous_approval(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    old_hashes = {"proposal.md": "oldhash123", "design.md": "oldhash456", "tasks.md": "oldhash789"}
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-8",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details({
            "proposal_review": {
                "status": "approved",
                "verdict": "READY_TO_MERGE",
                "artifact_hashes": old_hashes,
            },
        }),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123")
    )
    mock_res = make_mock_execution(
        '```json\n{"verdict":"CHANGES_REQUIRED","summary":"New specs have issues","findings":[{"severity":"MAJOR","location":"design.md","violated_requirement":"R2","expected_correction":"Revise"}]}\n```'
    )
    coordinator.agent_runner.run = AsyncMock(return_value=mock_res)

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.PROPOSAL_REVIEW
    assert "Independent proposal review requested changes: New specs have issues" in res.message
