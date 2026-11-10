import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import (
    ExternalOutcome,
    ExternalReasonCode,
    HumanGate,
    OrchestrationStage,
    OrchestrationStopOutcome,
    RetrySafety,
)
from minime.domain.models import ExternalActionResult, OrchestrationRun, OrchestrationStageEvent
from minime.services.orchestration_coordinator import ApplyOutcome, NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeInfo


@pytest.fixture
def base_setup(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    candidate_worktree = managed_root / "request-173-gacela-05-ui-self-hosted"
    candidate_worktree.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(candidate_worktree)], check=True)
    subprocess.run(["git", "-C", str(candidate_worktree), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(candidate_worktree), "config", "user.name", "Test"], check=True)
    change_dir = candidate_worktree / "openspec" / "changes" / "gacela-05-ui-self-hosted"
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "proposal.md").write_text("# Proposal\nValid proposal")
    (change_dir / "design.md").write_text("# Design\nValid design")
    (change_dir / "tasks.md").write_text("# Tasks\n- [ ] Task 1")
    (change_dir / "tasks.md").write_text("# Tasks\n- [ ] Task 1")
    subprocess.run(["git", "-C", str(candidate_worktree), "add", "."], check=True)
    subprocess.run(["git", "-C", str(candidate_worktree), "commit", "-qm", "seed candidate"], check=True)

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
    current_hashes = NativeOrchestrationCoordinator._compute_proposal_artifacts_hashes(
        candidate_worktree, "gacela-05-ui-self-hosted"
    )
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-1",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "provider_error",
                    "error": "Model quota exhausted",
                    "artifact_hashes": current_hashes,
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)
    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.PROPOSAL_REVIEW
    assert "Independent proposal review provider failed: Model quota exhausted" in res.message
    # A technical failure must not silently re-dispatch without authorization.
    coordinator.agent_runner.run.assert_not_called()


async def test_reentry_proposal_review_absent_evidence_requires_auth(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-absent",
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
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.PROPOSAL_REVIEW
    assert "recovery authorization is required" in res.message
    coordinator.agent_runner.run.assert_not_called()


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
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "approved",
                    "verdict": "READY_TO_MERGE",
                    "artifact_hashes": current_hashes,
                    "reviewer_provider": "antigravity",
                    "reviewer_model": "gemini-3.8-flash-medium",
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
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
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "dispatched",
                    "attempt_id": "prev-attempt-1",
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
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
        stop_details=make_stop_details(
            {
                "code_review": {
                    "status": "changes_required",
                    "summary": "Fix lints",
                    "candidate_sha": "sha123456",
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    coordinator._get_git_head_sha = AsyncMock(return_value="sha123456")
    coordinator._git_run = AsyncMock(return_value=MagicMock(stdout="diff content"))

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.CODE_REVIEW
    assert "Independent code review requested changes: Fix lints" in res.message
    coordinator.agent_runner.run.assert_not_called()


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
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
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
        stop_details=make_stop_details(
            {
                "pr1_number": 195,
                "pr1_url": "https://github.com/org/repo/pull/195",
                "complexity": "high",
            }
        ),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
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
        stop_details=make_stop_details(
            {
                "pr1_number": 195,
                "pr2_number": 196,
                "pr2_url": "https://github.com/org/repo/pull/196",
                "pr2_head_sha": "sha_doc_1",
            }
        ),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
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
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "approved",
                    "verdict": "READY_TO_MERGE",
                    "artifact_hashes": old_hashes,
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    mock_res = make_mock_execution(
        '```json\n{"verdict":"CHANGES_REQUIRED","summary":"New specs have issues","findings":[{"severity":"MAJOR","location":"design.md","violated_requirement":"R2","expected_correction":"Revise"}]}\n```'
    )
    async def correct_proposal(*args, **kwargs):
        (change_dir / "design.md").write_text("# Design\nCorrected design")
        return mock_res

    coordinator.agent_runner.run = AsyncMock(side_effect=correct_proposal)

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "RUNNING"
    assert res.current_stage == OrchestrationStage.PROPOSAL_REVIEW
    assert "native OpenSpec correction completed" in res.message
    assert "second independent review is pending" in res.message
    assert coordinator.agent_runner.run.await_count == 2
    coordinator.agent_runner.resolve_workflow.assert_any_call(
        worktree_path=candidate_worktree,
        provider="antigravity",
        operation="update",
        change_name="gacela-05-ui-self-hosted",
    )


@pytest.mark.asyncio
async def test_proposal_changes_required_with_changed_hashes_triggers_new_review(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    old_hashes = {"proposal.md": "old_hash", "design.md": "old_hash", "tasks.md": "old_hash"}
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-hash-change",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "changes_required",
                    "verdict": "CHANGES_REQUIRED",
                    "summary": "Fix section 2",
                    "artifact_hashes": old_hashes,
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    # The new review approves after operator updated the proposal files
    mock_res = make_mock_execution(
        '```json\n{"verdict":"READY_TO_MERGE","summary":"Approved"}\n```'
    )
    coordinator.agent_runner.run = AsyncMock(return_value=mock_res)
    coordinator._run_apply = AsyncMock(return_value=False)

    await coordinator.execute_project_request("mini-me")
    updated_run = uow.orchestration_runs.get_by_id("run-test-hash-change")
    assert updated_run.current_stage == OrchestrationStage.IMPLEMENTING
    # Agent runner was invoked because hashes changed, superseding the old rejection
    coordinator.agent_runner.run.assert_called_once()


@pytest.mark.asyncio
async def test_proposal_changes_required_second_review_requires_human_without_third_attempt(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    current_hashes = NativeOrchestrationCoordinator._compute_proposal_artifacts_hashes(
        candidate_worktree, "gacela-05-ui-self-hosted"
    )
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-proposal-round-limit",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "changes_required",
                    "verdict": "CHANGES_REQUIRED",
                    "summary": "Still inconsistent",
                    "findings": [
                        {
                            "severity": "MAJOR",
                            "location": "design.md",
                            "violated_requirement": "scope",
                            "expected_correction": "remove stale behavior",
                        }
                    ],
                    "artifact_hashes": current_hashes,
                    "round": 1,
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)
    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "HUMAN_REQUIRED"
    assert "Maximum independent proposal-review attempts reached" in res.message
    coordinator.agent_runner.run.assert_not_called()


@pytest.mark.asyncio
async def test_proposal_review_e2e_correction_then_second_failure_stops_without_third_attempt(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    old_hashes = NativeOrchestrationCoordinator._compute_proposal_artifacts_hashes(
        candidate_worktree, "gacela-05-ui-self-hosted"
    )
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-proposal-e2e-rounds",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "changes_required",
                    "verdict": "CHANGES_REQUIRED",
                    "summary": "First finding",
                    "findings": [
                        {
                            "severity": "MAJOR",
                            "location": "design.md",
                            "violated_requirement": "scope",
                            "expected_correction": "clarify scope",
                        }
                    ],
                    "artifact_hashes": old_hashes,
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)
    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    second_review = make_mock_execution(
        '```json\n{"verdict":"CHANGES_REQUIRED","summary":"Second finding","findings":[{"severity":"MAJOR","location":"tasks.md","violated_requirement":"coverage","expected_correction":"add evidence"}]}\n```'
    )

    async def correction_or_review(*args, **kwargs):
        (change_dir / "design.md").write_text("# Design\nCorrected design")
        return make_mock_execution("updated")

    # The first call is a re-review after the first finding; the update must
    # happen before the second call is allowed to review again.
    coordinator.agent_runner.run = AsyncMock(side_effect=correction_or_review)
    first = await coordinator.execute_project_request("mini-me")
    assert first.status == "RUNNING"
    assert uow.orchestration_runs.get_by_id(run.run_id).stop_details["proposal_review"]["round"] == 1

    coordinator.agent_runner.run = AsyncMock(return_value=second_review)
    second = await coordinator.execute_project_request("mini-me")
    assert second.status == "HUMAN_REQUIRED"
    assert "Maximum independent proposal-review attempts reached" in second.message
    coordinator.agent_runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_proposal_review_escalation_operator_clarification_reproposes(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    current_hashes = NativeOrchestrationCoordinator._compute_proposal_artifacts_hashes(
        candidate_worktree, "gacela-05-ui-self-hosted"
    )
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-proposal-escalation-repropose",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "changes_required",
                    "verdict": "CHANGES_REQUIRED",
                    "summary": "Still inconsistent",
                    "findings": [
                        {
                            "severity": "MAJOR",
                            "location": "design.md",
                            "violated_requirement": "scope",
                            "expected_correction": "remove stale behavior",
                        }
                    ],
                    "artifact_hashes": current_hashes,
                    "round": 1,
                },
                "proposal_review_escalated": True,
            }
        ),
    )
    uow.orchestration_runs.save(run)
    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )

    res = await coordinator.execute_project_request(
        "mini-me", operator_clarification="Reduce scope to truly-dead code"
    )
    assert res.status == "RUNNING"
    stored = uow.orchestration_runs.get_by_id(run.run_id)
    assert stored.current_stage == OrchestrationStage.PROPOSING
    assert "proposal_review_escalated" not in (stored.stop_details or {})
    revision = (stored.stop_details or {}).get("pending_proposal_revision") or {}
    assert revision.get("clarification") == "Reduce scope to truly-dead code"
    assert revision.get("findings")


@pytest.mark.asyncio
async def test_proposal_review_escalation_without_clarification_awaits_human(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-proposal-escalation-await",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details({"proposal_review_escalated": True}),
    )
    uow.orchestration_runs.save(run)
    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "HUMAN_REQUIRED"
    coordinator.agent_runner.run.assert_not_called()


@pytest.mark.asyncio
async def test_corrupted_approved_verdict_pauses_fail_closed(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    current_hashes = NativeOrchestrationCoordinator._compute_proposal_artifacts_hashes(
        candidate_worktree, "gacela-05-ui-self-hosted"
    )
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-corrupted",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "approved",
                    "verdict": "CHANGES_REQUIRED",  # Corrupted: approved status but conflicting verdict
                    "artifact_hashes": current_hashes,
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.PROPOSAL_REVIEW
    assert "invalid approval verdict without READY_TO_MERGE" in res.message


@pytest.mark.asyncio
async def test_register_recovery_authorization_for_review_stages(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-auth",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details({"proposal_review": {"attempt_id": "att-123"}}),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )

    # 1. Valid proposal_review registration succeeds
    ok = coordinator.register_recovery_authorization(
        project_id="mini-me",
        run_id="run-test-auth",
        authorization_reference="auth-prop-1",
        actor_identity="operator@example.com",
        source_interface="test",
        issue_number=173,
        provider="antigravity",
        prior_attempt_id="att-123",
        stage="proposal_review",
    )
    assert ok is True

    # 2. Stage mismatch (registering code_review while in PROPOSAL_REVIEW) returns False
    ok_mismatch = coordinator.register_recovery_authorization(
        project_id="mini-me",
        run_id="run-test-auth",
        authorization_reference="auth-prop-2",
        actor_identity="operator@example.com",
        source_interface="test",
        issue_number=173,
        provider="antigravity",
        prior_attempt_id=None,
        stage="code_review",
    )
    assert ok_mismatch is False

    # 3. Code review in CODE_REVIEW stage succeeds
    run.current_stage = OrchestrationStage.CODE_REVIEW
    run.stop_details["code_review"] = {"attempt_id": "att-code-123"}
    uow.orchestration_runs.save(run)

    ok_code = coordinator.register_recovery_authorization(
        project_id="mini-me",
        run_id="run-test-auth",
        authorization_reference="auth-code-1",
        actor_identity="operator@example.com",
        source_interface="test",
        issue_number=173,
        provider="antigravity",
        prior_attempt_id="att-code-123",
        stage="code_review",
    )
    assert ok_code is True


@pytest.mark.asyncio
async def test_recovery_without_operator_actions_pauses_fail_closed(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    current_hashes = NativeOrchestrationCoordinator._compute_proposal_artifacts_hashes(
        candidate_worktree, "gacela-05-ui-self-hosted"
    )
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-no-ops",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "dispatched",
                    "artifact_hashes": current_hashes,
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)
    # Remove operator_actions to simulate broken/unsupported store
    del uow.operator_actions

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )

    res = await coordinator.execute_project_request(
        "mini-me", propose_recovery_authorization_id="some-token"
    )
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.PROPOSAL_REVIEW
    assert "Operator action store is unavailable" in res.message


def test_reconcile_f2_project_profiles_preserves_fallback(monkeypatch):
    import scripts.reconcile_f2_project_profiles as reconcile_module

    initial_profiles = {
        "thinking": {
            "agent_id": "codex",
            "model_id": "gpt-6.1-sol",
            "effort": "high",
            "workflows": ["/custom-think"],
            "skills": ["skill-a"],
        },
        "execution": {
            "agent_id": "codex",
            "model_id": "gpt-6.1-sol",
            "effort": "high",
            "workflows": ["/custom-exec"],
            "skills": ["skill-b"],
        },
        "independent_review": {
            "agent_id": "antigravity",
            "model_id": "claude-sonnet-5-5-medium",
            "effort": "medium",
            "workflows": ["/opsx-verify"],
            "skills": [],
        },
        "fallback": {
            "agent_id": "codex",
            "model_id": "gpt-5.6-sol",
            "effort": "custom_effort",
            "workflows": ["/custom-fallback"],
            "skills": ["skill-c"],
        },
    }
    mock_project = MagicMock(agent_profiles=initial_profiles)
    mock_service = MagicMock()
    mock_service.get_project.return_value = mock_project
    mock_session = MagicMock()

    monkeypatch.setattr(
        reconcile_module.db_manager,
        "session",
        MagicMock(
            return_value=MagicMock(
                __enter__=MagicMock(return_value=mock_session),
                __exit__=MagicMock(return_value=None),
            )
        ),
    )
    monkeypatch.setattr(reconcile_module, "PostgresPersistenceUnitOfWork", MagicMock())
    monkeypatch.setattr(reconcile_module, "ProjectService", MagicMock(return_value=mock_service))
    monkeypatch.setattr(
        reconcile_module,
        "ProjectCatalogService",
        MagicMock(return_value=MagicMock(validate_project_profiles=AsyncMock())),
    )

    ok = reconcile_module.reconcile()
    assert ok is True

    # Validate patch sent to update_configuration
    patch = mock_service.update_configuration.call_args[0][1]
    assert patch.agent_profiles is not None
    # 1. Independent review is antigravity + gemini-3.8-flash-medium
    rev = patch.agent_profiles["independent_review"]
    assert rev.agent_id == "antigravity"
    assert rev.model_id == "gemini-3.8-flash-medium"
    assert rev.effort == "medium"

    # 2. Thinking & execution are codex + gpt-5.6-luna with preserved workflows/skills
    th = patch.agent_profiles["thinking"]
    assert th.agent_id == "codex"
    assert th.model_id == "gpt-5.6-luna"
    assert th.workflows == ["/custom-think"]
    assert th.skills == ["skill-a"]

    ex = patch.agent_profiles["execution"]
    assert ex.agent_id == "codex"
    assert ex.model_id == "gpt-5.6-luna"
    assert ex.workflows == ["/custom-exec"]
    assert ex.skills == ["skill-b"]

    # 3. Fallback is 100% preserved
    fb = patch.agent_profiles["fallback"]
    assert fb.agent_id == "codex"
    assert fb.model_id == "gpt-5.6-sol"
    assert fb.effort == "custom_effort"
    assert fb.workflows == ["/custom-fallback"]
    assert fb.skills == ["skill-c"]


def test_role_resolution_maps_reviewer_to_independent_review():
    project = MagicMock(
        agent_profiles={
            "thinking": {"agent_id": "codex", "model_id": "gpt-5.6-luna"},
            "independent_review": {
                "agent_id": "antigravity",
                "model_id": "gemini-3.8-flash-medium",
            },
        }
    )

    provider = NativeOrchestrationCoordinator._configured_provider(project, "reviewer")
    assert provider == "antigravity"

    uow = MagicMock()
    uow.projects.get_by_id.return_value = project
    model = NativeOrchestrationCoordinator._configured_model(uow, "mini-me", "reviewer")
    assert model == "gemini-3.8-flash-medium"


@pytest.mark.asyncio
async def test_reentry_proposal_review_technical_failure_with_auth_redispatches(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    current_hashes = NativeOrchestrationCoordinator._compute_proposal_artifacts_hashes(
        candidate_worktree, "gacela-05-ui-self-hosted"
    )
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-retry",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "provider_error",
                    "error": "Model quota exhausted",
                    "artifact_hashes": current_hashes,
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)
    uow.operator_actions = MagicMock()
    uow.operator_actions.consume_single_use.return_value = MagicMock()

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    mock_res = make_mock_execution(
        '```json\n{"verdict":"READY_TO_MERGE","summary":"Approved"}\n```'
    )
    coordinator.agent_runner.run = AsyncMock(return_value=mock_res)
    coordinator._run_apply = AsyncMock(return_value=False)

    await coordinator.execute_project_request(
        "mini-me", proposal_review_recovery_authorization_id="auth-123"
    )
    coordinator.agent_runner.run.assert_called_once()
    updated_run = uow.orchestration_runs.get_by_id("run-test-retry")
    assert updated_run.current_stage == OrchestrationStage.IMPLEMENTING


@pytest.mark.asyncio
async def test_recovery_authorization_binds_prior_attempt_id(base_setup):
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-test-bind",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.PROPOSAL_REVIEW,
        stop_details=make_stop_details(
            {
                "proposal_review": {
                    "status": "dispatched",
                    "attempt_id": "prev-attempt-1",
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)
    uow.operator_actions = MagicMock()
    uow.operator_actions.consume_single_use.return_value = MagicMock()

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    mock_res = make_mock_execution(
        '```json\n{"verdict":"READY_TO_MERGE","summary":"Approved"}\n```'
    )
    coordinator.agent_runner.run = AsyncMock(return_value=mock_res)
    coordinator._run_apply = AsyncMock(return_value=False)

    await coordinator.execute_project_request(
        "mini-me", proposal_review_recovery_authorization_id="auth-bind"
    )
    _, kwargs = uow.operator_actions.consume_single_use.call_args
    assert kwargs["expected_parameters"]["prior_attempt_id"] == "prev-attempt-1"


@pytest.mark.asyncio
async def test_code_review_changes_required_with_findings_rewinds_to_apply(base_setup):
    """CHANGES_REQUIRED with actionable findings auto-dispatch to the implementer."""
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-corr-1",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.CODE_REVIEW,
        stop_details=make_stop_details(
            {
                "code_review": {
                    "status": "changes_required",
                    "summary": "Fix lints",
                    "candidate_sha": "sha123456",
                    "findings": [
                        {
                            "severity": "BLOCKER",
                            "location": "src/a.py",
                            "violated_requirement": "No tests",
                            "expected_correction": "Add unit tests",
                        }
                    ],
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    coordinator._get_git_head_sha = AsyncMock(return_value="sha123456")
    coordinator._git_run = AsyncMock(return_value=MagicMock(stdout="diff content"))
    coordinator._run_apply = AsyncMock(return_value=False)

    res = await coordinator.execute_project_request("mini-me")
    # Correction loop, not a human pause.
    assert res.status == "RUNNING"
    assert res.current_stage == OrchestrationStage.IMPLEMENTING
    assert "round 1" in res.message
    updated = uow.orchestration_runs.get_by_id("run-corr-1")
    assert updated.stop_details["code_review"]["round"] == 1
    assert updated.stop_details["pending_corrections"][0]["severity"] == "BLOCKER"


@pytest.mark.asyncio
async def test_code_review_changes_required_exhausts_rounds_then_pauses(base_setup):
    """After max_review_rounds the ladder escalates to the operator."""
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-corr-2",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.CODE_REVIEW,
        stop_details=make_stop_details(
            {
                "code_review": {
                    "status": "changes_required",
                    "summary": "Still failing",
                    "candidate_sha": "sha123456",
                    "round": 3,
                    "findings": [
                        {
                            "severity": "MAJOR",
                            "location": "src/b.py",
                            "violated_requirement": "Security gap",
                            "expected_correction": "Fix auth",
                        }
                    ],
                },
            }
        ),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    coordinator._get_git_head_sha = AsyncMock(return_value="sha123456")
    coordinator._git_run = AsyncMock(return_value=MagicMock(stdout="diff content"))

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "PAUSED"
    assert res.current_stage == OrchestrationStage.CODE_REVIEW
    coordinator.agent_runner.run.assert_not_called()


@pytest.mark.asyncio
async def test_apply_injects_pending_corrections(base_setup):
    """The implementer Apply prompt carries the reviewer findings as correction context."""
    uow, candidate_worktree, change_dir = base_setup
    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.agent_runner.resolve_workflow = MagicMock(
        return_value=MagicMock(dispatch_command="$openspec-apply-change")
    )
    coordinator.agent_runner.run = AsyncMock(
        return_value=make_mock_execution("applied", exit_code=0)
    )
    corrections = [
        {
            "severity": "BLOCKER",
            "location": "src/x.py",
            "violated_requirement": "Missing tests",
            "expected_correction": "Add tests",
        }
    ]
    await coordinator._run_apply(
        candidate_worktree, "codex", "gacela-05-ui-self-hosted", corrections=corrections
    )
    # _run_apply will attempt the agent; verify the prompt reached the runner.
    call = coordinator.agent_runner.run.call_args
    assert call is not None
    prompt = call.kwargs["prompt_context"]
    assert "CHANGES_REQUIRED" in prompt
    assert "Missing tests" in prompt
    assert "Add tests" in prompt
    assert "[BLOCKER] src/x.py" in prompt


@pytest.mark.asyncio
async def test_apply_failure_escalates_after_ceiling(base_setup):
    """A repeatedly-failing Apply must escalate at the unchanged hard ceiling."""
    uow, candidate_worktree, change_dir = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-apply-loop",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.IMPLEMENTING,
        stop_details=make_stop_details({"apply_failure_count": 2}),
    )
    uow.orchestration_runs.save(run)

    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    coordinator._run_apply = AsyncMock(return_value=False)

    res = await coordinator.execute_project_request("mini-me")
    assert res.status == "HUMAN_REQUIRED"
    assert res.current_stage == OrchestrationStage.IMPLEMENTING
    assert "ceiling" in res.message
    updated = uow.orchestration_runs.get_by_id("run-apply-loop")
    assert updated.stop_details["apply_total_attempts"] == 3
    assert updated.stop_details["apply_escalated"] is True


@pytest.mark.asyncio
async def test_simulated_accepted_apply_gate_response_starts_new_cycle_on_same_candidate(base_setup):
    uow, candidate_worktree, _ = base_setup
    action_id = "accepted-apply-gate-action-375"
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-apply-cycle-reset",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.IMPLEMENTING,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        stop_details=make_stop_details({
            "apply_total_attempts": 3,
            "apply_no_progress": 2,
            "apply_limits": {"max_attempts": 3, "max_no_progress": 2},
            "apply_snapshot": {"sha": "candidate-before-human", "pending": ["Task 1"]},
            "human_payload": {
                "gate_id": "gate-apply-cycle-reset",
                "gate": "apply_escalation",
                "stage": "IMPLEMENTING",
                "attempts": 3,
                "hard_limit": 3,
                "no_progress": 2,
                "question": "Continue Apply recovery?",
                "options": [{"id": "retry", "label": "Continue"}],
            },
        }),
    )
    uow.orchestration_runs.save(run)
    historical_candidate = {"run_id": run.run_id, "candidate_sha": "historical-sha"}
    historical_start = OrchestrationStageEvent(
        run_id=run.run_id,
        from_stage=OrchestrationStage.IMPLEMENTING,
        to_stage=OrchestrationStage.IMPLEMENTING,
        event_type="STAGE_INVOCATION_STARTED",
        evidence_references={
            "attempt_id": "historical-apply-attempt",
            "claim_key": f"stage-invocation:{run.run_id}:APPLY:historical-candidate",
            "candidate": historical_candidate,
        },
    )
    historical_finish = OrchestrationStageEvent(
        run_id=run.run_id,
        from_stage=OrchestrationStage.IMPLEMENTING,
        to_stage=OrchestrationStage.IMPLEMENTING,
        event_type="STAGE_INVOCATION_FAILED",
        evidence_references={
            "attempt_id": "historical-apply-attempt",
            "claim_key": f"stage-invocation:{run.run_id}:APPLY:historical-candidate",
            "candidate": historical_candidate,
            "status": "FAILED",
        },
    )
    uow.orchestration_stage_events.save(historical_start)
    uow.orchestration_stage_events.save(historical_finish)
    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
        uow_factory=lambda: uow,
    )
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    candidate_sha = subprocess.check_output(
        ["git", "-C", str(candidate_worktree), "rev-parse", "HEAD"], text=True
    ).strip()
    stage_order = []
    async def apply_after_update(*args, **kwargs):
        stage_order.append("APPLY")
        return ApplyOutcome(
        status="FAILED", completed_tasks=(), pending_tasks=("Task 1",),
        candidate_sha=candidate_sha, changed_files=(), diff_fingerprint=None,
        tests_passed=None, test_evidence="", error="simulated failure",
        )

    async def update_before_apply(**kwargs):
        stage_order.append("UPDATE")
        return {"status": "VALIDATED"}

    coordinator._run_apply = AsyncMock(side_effect=apply_after_update)
    coordinator._run_apply_gate_update = AsyncMock(side_effect=update_before_apply)

    result = await coordinator.execute_project_request(
        "mini-me",
        target_run_id=run.run_id,
        operator_clarification="Continue Apply recovery",
        operator_action_id=action_id,
    )

    updated = uow.orchestration_runs.get_by_id(run.run_id)
    assert result.status == "HUMAN_REQUIRED"
    assert result.run_id == run.run_id
    coordinator._run_apply_gate_update.assert_awaited_once()
    assert coordinator._run_apply_gate_update.await_args.kwargs["operator_response"] == "Continue Apply recovery"
    assert stage_order == ["UPDATE", "APPLY"]
    assert coordinator._run_apply.await_count == 1
    assert coordinator._run_apply.await_args.kwargs["operator_response"] == "Continue Apply recovery"
    assert updated.stop_details["apply_total_attempts"] == 1
    assert updated.stop_details["apply_cycle_started_by_action_id"] == action_id
    assert updated.stop_details["apply_no_progress"] == 1
    assert updated.stop_details["apply_snapshot"]["sha"] == candidate_sha
    resolved = updated.stop_details["resolved_human_gates"]
    assert any(item["gate_id"] == "gate-apply-cycle-reset" for item in resolved)
    events = uow.orchestration_stage_events.list_by_run(run.run_id)
    assert historical_start in events
    assert historical_finish in events
    started = [
        event for event in events
        if event.event_type == "STAGE_INVOCATION_STARTED"
        and event.evidence_references.get("operator_action_id") == action_id
    ]
    assert len(started) == 1
    assert started[0].evidence_references["operator_action_id"] == action_id
    candidate_identity = started[0].evidence_references["candidate"]
    assert candidate_identity["run_id"] == run.run_id
    assert candidate_identity["worktree"] == str(candidate_worktree.resolve())
    assert candidate_identity["branch"] == "master" or candidate_identity["branch"] == "main"
    assert candidate_identity["candidate_sha"] == candidate_sha


@pytest.mark.asyncio
async def test_unrelated_human_gate_does_not_reset_apply_cycle(base_setup):
    uow, candidate_worktree, _ = base_setup
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-unrelated-gate-no-reset",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.IMPLEMENTING,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        stop_details=make_stop_details({
            "apply_total_attempts": 3,
            "apply_no_progress": 2,
            "apply_limits": {"max_attempts": 3, "max_no_progress": 2},
            "human_payload": {
                "gate_id": "gate-physical-validation",
                "gate": "physical_validation",
                "stage": "IMPLEMENTING",
                "attempts": 3,
                "hard_limit": 3,
                "question": "Validate on device?",
                "options": [],
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
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    coordinator._run_apply = AsyncMock(return_value=False)

    await coordinator.execute_project_request(
        "mini-me",
        target_run_id=run.run_id,
        operator_clarification="I will validate on device",
        operator_action_id="accepted-physical-gate-action",
    )

    updated = uow.orchestration_runs.get_by_id(run.run_id)
    assert updated.stop_details["apply_total_attempts"] == 3
    assert updated.stop_details["apply_no_progress"] == 2
    assert "apply_cycle_started_by_action_id" not in updated.stop_details
    coordinator._run_apply.assert_not_awaited()


@pytest.mark.asyncio
async def test_simulated_apply_gate_update_uses_native_workflow_and_strict_validation(base_setup):
    uow, candidate_worktree, _ = base_setup
    run = OrchestrationRun(
        project_id="mini-me", run_id="run-native-update", change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123", current_stage=OrchestrationStage.IMPLEMENTING,
        stop_details=make_stop_details(),
    )
    uow.orchestration_runs.save(run)
    runner = MagicMock()
    runner.resolve_workflow.return_value = MagicMock(name="native-update-workflow")
    runner.run = AsyncMock(return_value=make_mock_execution("Updated and validated"))
    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(), worktree_manager=MagicMock(), agent_runner=runner,
        uow_factory=lambda: uow,
    )
    before = {
        "run_id": run.run_id, "worktree": str(candidate_worktree.resolve()), "branch": "main",
        "generation": 0, "candidate_sha": "sha-before", "candidate_fingerprint": "fp-before",
    }
    after = {**before, "candidate_sha": "sha-after", "candidate_fingerprint": "fp-after"}
    coordinator._stage_candidate_identity = AsyncMock(side_effect=[before, after])
    coordinator._begin_stage_invocation = AsyncMock(return_value=MagicMock(claim=MagicMock()))
    async def run_claimed(_uow, _claim, operation):
        return await operation()

    coordinator._run_claimed = AsyncMock(side_effect=run_claimed)
    coordinator._finish_stage_invocation = AsyncMock()
    coordinator.openspec_adapter.validate_change_strict = MagicMock(return_value={
        "status": "PASS", "returncode": 0, "stdout": "validated", "stderr": "",
    })

    result = await coordinator._run_apply_gate_update(
        uow=uow, run=run, worktree_path=candidate_worktree, provider="codex",
        change_name=run.change_name, project_id="mini-me", operator_action_id="action-378",
        operator_response="Defer the iPhone audio validation until the TTS issue.",
        gate_payload={"gate": "apply_escalation", "question": "Which checks can be deferred?"},
    )

    assert result["status"] == "VALIDATED", run.stop_details["apply_gate_update"].get("error")
    runner.resolve_workflow.assert_called_once_with(
        worktree_path=candidate_worktree, provider="codex", operation="update",
        change_name=run.change_name,
    )
    assert runner.run.await_args.kwargs["role"] == "thinker"
    assert "Defer the iPhone audio validation" in runner.run.await_args.kwargs["prompt_context"]
    assert coordinator.openspec_adapter.validate_change_strict.call_count == 1
    assert run.stop_details["apply_gate_update"]["before"]["candidate_sha"] == "sha-before"
    assert run.stop_details["apply_gate_update"]["after"]["candidate_sha"] == "sha-after"


@pytest.mark.asyncio
async def test_simulated_apply_gate_update_fails_closed_when_strict_validation_fails(base_setup):
    uow, candidate_worktree, _ = base_setup
    run = OrchestrationRun(
        project_id="mini-me", run_id="run-invalid-update", change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123", current_stage=OrchestrationStage.IMPLEMENTING,
        stop_details=make_stop_details(),
    )
    uow.orchestration_runs.save(run)
    runner = MagicMock()
    runner.resolve_workflow.return_value = MagicMock(name="native-update-workflow")
    runner.run = AsyncMock(return_value=make_mock_execution("Updated artifacts"))
    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(), worktree_manager=MagicMock(), agent_runner=runner,
        uow_factory=lambda: uow,
    )
    identity = {
        "run_id": run.run_id, "worktree": str(candidate_worktree.resolve()), "branch": "main",
        "generation": 0, "candidate_sha": "sha", "candidate_fingerprint": "fp",
    }
    coordinator._stage_candidate_identity = AsyncMock(side_effect=[identity, identity])
    coordinator._begin_stage_invocation = AsyncMock(return_value=MagicMock(claim=MagicMock()))
    async def run_claimed(_uow, _claim, operation):
        return await operation()

    coordinator._run_claimed = AsyncMock(side_effect=run_claimed)
    coordinator._finish_stage_invocation = AsyncMock()
    coordinator.openspec_adapter.validate_change_strict = MagicMock(return_value={
        "status": "FAIL", "returncode": 1, "stdout": "invalid", "stderr": "bad artifact",
    })

    result = await coordinator._run_apply_gate_update(
        uow=uow, run=run, worktree_path=candidate_worktree, provider="codex",
        change_name=run.change_name, project_id="mini-me", operator_action_id="action-invalid",
        operator_response="Defer mobile validation.",
        gate_payload={"gate": "apply_escalation", "question": "Which checks can be deferred?"},
    )

    assert result["status"] == "INVALID"
    assert "strict validation" in result["question"]
    assert coordinator.openspec_adapter.validate_change_strict.call_count == 1


@pytest.mark.asyncio
async def test_simulated_ambiguous_update_returns_current_human_question(base_setup):
    uow, candidate_worktree, _ = base_setup
    run = OrchestrationRun(
        project_id="mini-me", run_id="run-ambiguous-update", change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123", current_stage=OrchestrationStage.IMPLEMENTING,
        stop_details=make_stop_details(),
    )
    uow.orchestration_runs.save(run)
    handoff = MagicMock(
        status="HUMAN_REQUIRED", summary="Need the exact criterion disposition.",
        pending=("Which validation should be deferred, and what evidence remains required?",),
    )
    runner = MagicMock()
    runner.resolve_workflow.return_value = MagicMock(name="native-update-workflow")
    runner.run = AsyncMock(return_value=MagicMock(workflow_handoff=handoff))
    coordinator = NativeOrchestrationCoordinator(
        github_adapter=MagicMock(), worktree_manager=MagicMock(), agent_runner=runner,
        uow_factory=lambda: uow,
    )
    identity = {
        "run_id": run.run_id, "worktree": str(candidate_worktree.resolve()), "branch": "main",
        "generation": 0, "candidate_sha": "sha", "candidate_fingerprint": "fp",
    }
    coordinator._stage_candidate_identity = AsyncMock(side_effect=[identity, identity])
    coordinator._begin_stage_invocation = AsyncMock(return_value=MagicMock(claim=MagicMock()))

    async def run_claimed(_uow, _claim, operation):
        return await operation()

    coordinator._run_claimed = AsyncMock(side_effect=run_claimed)
    coordinator._finish_stage_invocation = AsyncMock()
    coordinator.openspec_adapter.validate_change_strict = MagicMock()

    result = await coordinator._run_apply_gate_update(
        uow=uow, run=run, worktree_path=candidate_worktree, provider="codex",
        change_name=run.change_name, project_id="mini-me", operator_action_id="action-ambiguous",
        operator_response="Handle mobile later, maybe.",
        gate_payload={"gate": "physical_validation", "question": "What should be deferred?"},
    )

    assert result["status"] == "HUMAN_REQUIRED"
    assert result["question"] == handoff.pending[0]
    assert run.stop_details["apply_gate_update"]["status"] == "HUMAN_REQUIRED"
    coordinator.openspec_adapter.validate_change_strict.assert_not_called()


def test_same_accepted_response_cannot_replay_an_unvalidated_update():
    blocked = {"operator_action_id": "same-action", "status": "UPDATE_STARTED"}
    validated = {"operator_action_id": "same-action", "status": "VALIDATED"}
    other_action = {"operator_action_id": "previous-action", "status": "UPDATE_STARTED"}

    assert NativeOrchestrationCoordinator._same_apply_gate_response_has_unvalidated_update(
        blocked, "same-action"
    )
    assert not NativeOrchestrationCoordinator._same_apply_gate_response_has_unvalidated_update(
        validated, "same-action"
    )
    assert not NativeOrchestrationCoordinator._same_apply_gate_response_has_unvalidated_update(
        other_action, "same-action"
    )


@pytest.mark.asyncio
async def test_apply_no_progress_limit_still_stops_current_cycle(base_setup):
    uow, candidate_worktree, _ = base_setup
    project = uow.projects.get_by_id("mini-me")
    project.execution_policy = {"apply_max_no_progress": 1}
    uow.projects.save(project)
    candidate_sha = subprocess.check_output(
        ["git", "-C", str(candidate_worktree), "rev-parse", "HEAD"], text=True
    ).strip()
    run = OrchestrationRun(
        project_id="mini-me",
        run_id="run-apply-no-progress-limit",
        change_name="gacela-05-ui-self-hosted",
        base_sha="base_sha_123",
        current_stage=OrchestrationStage.IMPLEMENTING,
        stop_details=make_stop_details({
            "apply_total_attempts": 0,
            "apply_no_progress": 0,
            "apply_snapshot": {
                "pending": ["Task 1"], "completed": [], "sha": candidate_sha,
                "files": [], "fingerprint": "unchanged",
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
        return_value=WorktreeInfo(
            path=candidate_worktree, branch_name="feature/f5", base_sha="base_sha_123"
        )
    )
    coordinator._run_apply = AsyncMock(return_value=ApplyOutcome(
        status="PARTIAL", completed_tasks=(), pending_tasks=("Task 1",),
        candidate_sha=candidate_sha, changed_files=(), diff_fingerprint="unchanged",
        tests_passed=None, test_evidence="", run_id=run.run_id,
    ))

    result = await coordinator.execute_project_request("mini-me")

    updated = uow.orchestration_runs.get_by_id(run.run_id)
    assert result.status == "HUMAN_REQUIRED"
    assert coordinator._run_apply.await_count == 1
    assert updated.stop_details["apply_total_attempts"] == 1
    assert updated.stop_details["apply_no_progress"] == 1
