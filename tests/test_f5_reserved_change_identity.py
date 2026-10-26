"""Contract-bound Change names for the self-hosted F5 bootstrap.

No CLI agent, inference or network request is dispatched by these tests.
"""

from pathlib import Path
import subprocess
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import ExternalOutcome, ExternalReasonCode, RetrySafety, OrchestrationStage
from minime.domain.models import ExternalActionResult, OrchestrationRun, WorktreeCreationState
from minime.services.agent_runner import CliAgentRunner
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeInfo, WorktreeManager


F5_BODY = (
    "## Alcance del único Change OpenSpec\n"
    "**Change reservado (no creado ni activado):** `gacela-05-ui-self-hosted` "
    "— puede contener varias specs.\n"
)


@pytest.mark.parametrize(
    ("number", "title", "body", "expected"),
    [
        (173, "Fase 5/6 — UI y primera ejecución autónoma de mini me", F5_BODY, "gacela-05-ui-self-hosted"),
        (174, "Fase 6/6", "**Change reservado (no creado ni activado):** `gacela-06-depuracion-final`", "gacela-06-depuracion-final"),
        (501, "Add caching layer", "Ordinary request", "req-501-add-caching-layer"),
    ],
)
def test_change_identity_comes_from_ticket_reservation_or_default(number, title, body, expected):
    assert WorktreeManager.resolve_request_change_name(number, title, body) == expected


@pytest.mark.parametrize(
    "body",
    [
        "**Change reservado (no creado ni activado):** `../../escape`",
        "**Change reservado (no creado ni activado):** `not_valid_name`",
        "**Change reservado (no creado ni activado):** `gacela-05-ui-self-hosted`\n"
        "**Change reservado (no creado ni activado):** `gacela-05-ui-self-hosted`",
        "**Change reservado (no creado ni activado):** missing-backticks",
    ],
)
def test_invalid_or_duplicate_change_reservations_fail_closed(body):
    with pytest.raises(ValueError, match="reservation"):
        WorktreeManager.resolve_request_change_name(173, "Fase 5/6", body)


def test_next_fifo_admission_uses_same_reservation():
    uow = InMemoryPersistenceUnitOfWork()
    admitted = NativeOrchestrationCoordinator._admit_next_fifo_request(
        uow=uow,
        project_id="mini-me",
        repository="silverberdi/mini-me",
        completed_run_id="completed-f4",
        next_request={
            "issue_number": 173,
            "title": "Fase 5/6 — UI y primera ejecución autónoma de mini me",
            "body": F5_BODY,
        },
    )
    assert admitted is not None
    assert admitted.change_name == "gacela-05-ui-self-hosted"
    assert admitted.stop_details["issue_number"] == 173
    assert admitted.stop_details["admission_only"] is True
    assert uow.orchestration_runs.get_active_run("mini-me", "gacela-05-ui-self-hosted") is not None
    assert [r.change_name for r in uow.orchestration_runs.list_runs(project_id="mini-me", is_active=True)] == ["gacela-05-ui-self-hosted"]


@pytest.mark.asyncio
async def test_request_initialization_uses_reserved_identity_without_dispatching_model(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    managed_root = tmp_path / "worktrees"
    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow, "mini-me", repo_dir, managed_root,
        canonical_repository_identity="github.com/silverberdi/mini-me",
    )

    github = MagicMock()
    github.list_issues.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=[{
            "number": 173,
            "title": "Fase 5/6 — UI y primera ejecución autónoma de mini me",
            "body": F5_BODY,
            "labels": [],
            "created_at": "2026-10-22T03:27:06Z",
        }],
    )
    worktrees = WorktreeManager(repo_dir, uow=uow)
    worktrees.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(
            path=repo_dir, branch_name="request-173-fase-56-ui", base_sha="testbase"
        )
    )
    runner = CliAgentRunner()
    runner.run = AsyncMock(side_effect=AssertionError("No model may be invoked"))
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow, github_adapter=github,
        worktree_manager=worktrees, agent_runner=runner,
    )
    coordinator._normalize_request_before_explore = AsyncMock(
        return_value=(None, "Stop before any inference")
    )

    result = await coordinator.execute_project_request(
        "mini-me", thinker_provider="codex",
        implementer_provider="codex", reviewer_provider="antigravity",
    )
    assert result.status == "PAUSED"
    active = uow.orchestration_runs.get_active_run("mini-me", "gacela-05-ui-self-hosted")
    assert active is not None
    assert active.stop_details["issue_number"] == 173
    assert worktrees.create_request_worktree.await_args.kwargs["change_name"] == "gacela-05-ui-self-hosted"
    runner.run.assert_not_awaited()

def _prepare_offline_real_git(repo_dir: Path, uow: InMemoryPersistenceUnitOfWork) -> str:
    """Use a real disposable repository and local tracking ref; no network/model calls."""
    setup_managed_repository_fixture(
        uow, "mini-me", repo_dir, repo_dir.parent / "worktrees",
        canonical_repository_identity="github.com/silverberdi/mini-me",
        local_remote=False,
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir, text=True).strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", sha],
        cwd=repo_dir, check=True, capture_output=True,
    )
    return sha


@pytest.mark.asyncio
async def test_new_request_worktree_persists_authoritative_change_and_ownership(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    uow = InMemoryPersistenceUnitOfWork()
    initial_sha = _prepare_offline_real_git(repo_dir, uow)

    manager = WorktreeManager(repo_dir, uow=uow)
    real_git = manager._git

    async def offline_git(args, **kwargs):
        if args and args[0] == "fetch":
            return ""  # Never contact GitHub from a regression test.
        if args[:2] == ["worktree", "add"]:
            pending = uow.orchestration_worktree_ownerships.get_by_job_id("f5-run-173")
            assert pending is not None
            assert pending.creation_state is WorktreeCreationState.PENDING
            assert uow.committed is True
        return await real_git(args, **kwargs)

    manager._git = offline_git
    info = await manager.create_request_worktree(
        project_id="mini-me",
        issue_number=173,
        issue_title="Fase 5 UI",
        run_id="f5-run-173",
        change_name="gacela-05-ui-self-hosted",
    )

    ownership = uow.orchestration_worktree_ownerships.get_by_job_id("f5-run-173")
    assert ownership is not None
    assert ownership.change_name == "gacela-05-ui-self-hosted"
    assert ownership.run_id == "f5-run-173"
    assert ownership.canonical_worktree_path == str(info.path)
    assert ownership.source_repository_identity == "github.com/silverberdi/mini-me"
    assert ownership.source_base_sha == initial_sha
    assert ownership.branch == info.branch_name
    assert ownership.creation_state is WorktreeCreationState.CREATED
    assert (info.path / ".minime_worktree_ownership.json").exists()
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=info.path, text=True
    ).strip() == initial_sha


@pytest.mark.asyncio
async def test_request_worktree_resumes_after_main_advances_without_rebasing_run(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    uow = InMemoryPersistenceUnitOfWork()
    initial_sha = _prepare_offline_real_git(repo_dir, uow)
    manager = WorktreeManager(repo_dir, uow=uow)
    real_git = manager._git

    async def offline_git(args, **kwargs):
        if args and args[0] == "fetch":
            return ""
        return await real_git(args, **kwargs)

    manager._git = offline_git
    original = await manager.create_request_worktree(
        project_id="mini-me", issue_number=173, issue_title="Fase 5 UI",
        run_id="f5-run-173", change_name="gacela-05-ui-self-hosted",
    )

    (repo_dir / "later.md").write_text("main advanced", encoding="utf-8")
    subprocess.run(["git", "add", "later.md"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "advance main after request admission"],
        cwd=repo_dir, check=True, capture_output=True,
    )
    new_main_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, text=True
    ).strip()
    assert new_main_sha != initial_sha
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", new_main_sha],
        cwd=repo_dir, check=True, capture_output=True,
    )
    resumed = await manager.create_request_worktree(
        project_id="mini-me", issue_number=173, issue_title="Fase 5 UI",
        run_id="f5-run-173", change_name="gacela-05-ui-self-hosted",
    )
    assert resumed.path == original.path
    assert resumed.base_sha == initial_sha
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=resumed.path, text=True
    ).strip() == initial_sha
    ownership = uow.orchestration_worktree_ownerships.get_by_job_id("f5-run-173")
    assert ownership.creation_state is WorktreeCreationState.CREATED
    assert ownership.source_base_sha == initial_sha


@pytest.mark.asyncio
async def test_pending_ownership_commit_failure_prevents_git_worktree_add(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    uow = InMemoryPersistenceUnitOfWork()
    _prepare_offline_real_git(repo_dir, uow)
    manager = WorktreeManager(repo_dir, uow=uow)
    real_git = manager._git
    calls = []

    async def offline_git(args, **kwargs):
        calls.append(tuple(args))
        if args and args[0] == "fetch":
            return ""
        return await real_git(args, **kwargs)

    manager._git = offline_git

    def reject_commit():
        raise RuntimeError("durable commit denied")

    uow.commit = reject_commit
    with pytest.raises(RuntimeError, match="durable commit denied"):
        await manager.create_request_worktree(
            project_id="mini-me", issue_number=173, issue_title="Fase 5 UI",
            run_id="f5-run-commit-fail", change_name="gacela-05-ui-self-hosted",
        )
    assert not any(parts[:2] == ("worktree", "add") for parts in calls)
    assert not (repo_dir.parent / "worktrees" / "request-173-fase-5-ui").exists()


@pytest.mark.asyncio
async def test_worktree_ownership_failure_blocks_request_instead_of_silent_success(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    managed_root = tmp_path / "worktrees"
    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow, "mini-me", repo_dir, managed_root,
        canonical_repository_identity="github.com/silverberdi/mini-me",
    )
    manager = WorktreeManager(repo_dir, uow=uow)
    manager._git = AsyncMock(side_effect=lambda args, project_id=None: (
        (_ for _ in ()).throw(RuntimeError("new branch"))
        if args[:2] == ["rev-parse", "--verify"] else "b" * 40
    ))
    manager._write_ownership_marker = MagicMock(side_effect=RuntimeError("marker denied"))
    with pytest.raises(RuntimeError, match="marker denied"):
        await manager.create_request_worktree(
            project_id="mini-me", issue_number=173, issue_title="Fase 5 UI",
            run_id="f5-run-denied", change_name="gacela-05-ui-self-hosted",
        )


@pytest.mark.asyncio
async def test_reenter_proposing_uses_durable_normalized_body_without_model_calls(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow, "mini-me", repo_dir, tmp_path / "worktrees",
        canonical_repository_identity="github.com/silverberdi/mini-me",
    )
    original_body = "Feature: F5 UI\\n  Scenario: Render dashboard\\n    Given an authorized user\\n    When dashboard opens\\n    Then progress is visible"
    run = OrchestrationRun(
        project_id="mini-me", change_name="gacela-05-ui-self-hosted",
        base_sha="main", current_stage=OrchestrationStage.PROPOSING,
        resumable_stage=OrchestrationStage.PROPOSING,
        stop_details={
            "issue_number": 173, "issue_title": "F5 interface",
            "request_normalization": {"normalized_body": original_body},
        },
    )
    uow.orchestration_runs.save(run)
    worktrees = WorktreeManager(repo_dir, uow=uow)
    worktrees.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=repo_dir, branch_name="request-173-f5-interface", base_sha="a" * 40)
    )
    runner = CliAgentRunner()
    runner.run = AsyncMock(side_effect=AssertionError("No paid model calls"))
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow, github_adapter=MagicMock(),
        worktree_manager=worktrees, agent_runner=runner,
    )
    coordinator._normalize_request_before_explore = AsyncMock(
        side_effect=AssertionError("Do not repeat normalization")
    )
    coordinator._run_propose = AsyncMock(
        return_value={"status": "FAILED", "message": "Intentional no-model test stop"}
    )

    result = await coordinator.execute_project_request("mini-me")
    assert result.status == "PAUSED"
    assert coordinator._run_propose.await_args.kwargs["issue_body"] == original_body
    assert coordinator._run_propose.await_args.kwargs["change_name"] == "gacela-05-ui-self-hosted"
    coordinator._normalize_request_before_explore.assert_not_awaited()
    runner.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_reenter_proposing_without_durable_body_stops_before_dispatch(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow, "mini-me", repo_dir, tmp_path / "worktrees",
        canonical_repository_identity="github.com/silverberdi/mini-me",
    )
    run = OrchestrationRun(
        project_id="mini-me", change_name="gacela-05-ui-self-hosted",
        base_sha="main", current_stage=OrchestrationStage.PROPOSING,
        stop_details={"issue_number": 173, "issue_title": "F5 interface"},
    )
    uow.orchestration_runs.save(run)
    worktrees = WorktreeManager(repo_dir, uow=uow)
    worktrees.create_request_worktree = AsyncMock()
    runner = CliAgentRunner()
    runner.run = AsyncMock(side_effect=AssertionError("No paid model calls"))
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow, github_adapter=MagicMock(),
        worktree_manager=worktrees, agent_runner=runner,
    )

    result = await coordinator.execute_project_request("mini-me")
    assert result.status == "PAUSED"
    assert "normalized body" in result.message
    worktrees.create_request_worktree.assert_not_awaited()
    runner.run.assert_not_awaited()


def test_reentry_recovers_immutable_reserved_change_from_durable_run():
    from minime.domain.models import OrchestrationRun
    from minime.services.remote_request_intake import RemoteRequestIntakeService

    uow = InMemoryPersistenceUnitOfWork()
    run = OrchestrationRun(
        project_id="mini-me",
        change_name="gacela-05-ui-self-hosted",
        base_sha="main",
        stop_details={
            "issue_number": 173,
            "issue_title": "Fase 5/6 — UI y primera ejecución autónoma de mini me",
        },
    )
    uow.orchestration_runs.save(run)
    github = MagicMock()
    selected = RemoteRequestIntakeService(github, uow).select_next_request(
        "mini-me", "silverberdi/mini-me"
    )

    assert selected is not None and selected["re_entrant"] is True
    assert selected["run_id"] == run.run_id
    assert selected["issue_number"] == 173
    assert selected["change_name"] == "gacela-05-ui-self-hosted"
    assert selected["title"] == run.stop_details["issue_title"]
    github.list_issues.assert_not_called()
