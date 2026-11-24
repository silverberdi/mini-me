from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import ExternalOutcome, ExternalReasonCode, OrchestrationStage, RetrySafety
from minime.domain.models import ExternalActionResult
from minime.services.agent_runner import CliAgentRunner
from minime.services.orchestration_coordinator import (
    GitCommandResult,
    NativeOrchestrationCoordinator,
)
from minime.services.worktree_manager import WorktreeInfo, WorktreeManager


def _stage_event(event_type: str, evidence: dict) -> SimpleNamespace:
    return SimpleNamespace(event_type=event_type, evidence_references=evidence)


def test_doc_archive_reset_requires_verified_sync_replay(tmp_path: Path):
    path = tmp_path / "doc-worktree"
    run_id = "run-517"
    archive_key = f"stage-invocation:{run_id}:ARCHIVE:archive-fingerprint"
    sync_key = f"stage-invocation:{run_id}:SYNC:sync-fingerprint"
    reset = _stage_event("STAGE_INVOCATION_ABANDONED", {
        "claim_key": archive_key,
        "worktree_reset": True,
        "candidate": {"run_id": run_id, "worktree": str(path.resolve())},
    })

    assert NativeOrchestrationCoordinator._doc_archive_reset_requires_sync_replay(
        [reset], run_id, path
    )

    replay_start = _stage_event("STAGE_INVOCATION_STARTED", {
        "attempt_id": "sync-replay",
        "claim_key": sync_key,
        "doc_archive_sync_replay": True,
        "candidate": {"run_id": run_id, "worktree": str(path.resolve())},
    })
    replay_complete = _stage_event("STAGE_INVOCATION_COMPLETED", {
        "attempt_id": "sync-replay",
        "claim_key": sync_key,
        "result": {"effect_verified": True},
    })
    assert not NativeOrchestrationCoordinator._doc_archive_reset_requires_sync_replay(
        [reset, replay_start, replay_complete], run_id, path
    )

    old_sync = _stage_event("STAGE_INVOCATION_COMPLETED", {
        "attempt_id": "old-sync",
        "claim_key": sync_key,
        "result": {"effect_verified": True},
    })
    assert NativeOrchestrationCoordinator._doc_archive_reset_requires_sync_replay(
        [old_sync, reset], run_id, path
    )


@pytest.mark.asyncio
async def test_doc_archive_recovery_dispatches_sync_before_archive(tmp_path: Path):
    from minime.domain.enums import OrchestrationStage
    from minime.domain.models import OrchestrationRun, OrchestrationStageEvent
    from minime.services.agent_runner import ResolvedWorkflow

    uow = InMemoryPersistenceUnitOfWork()
    run_id = "run-517-sync-replay"
    run = OrchestrationRun(
        run_id=run_id,
        project_id="project-517-sync-replay",
        change_name="issue-517-worktree-recovery-test-isolation",
        base_sha="main",
        current_stage=OrchestrationStage.DOC_CLOSING,
    )
    doc_path = tmp_path / "doc-worktree"
    uow.orchestration_stage_events.save(OrchestrationStageEvent(
        run_id=run_id,
        from_stage=OrchestrationStage.DOC_CLOSING,
        to_stage=OrchestrationStage.DOC_CLOSING,
        event_type="STAGE_INVOCATION_ABANDONED",
        evidence_references={
            "claim_key": f"stage-invocation:{run_id}:ARCHIVE:old-fingerprint",
            "worktree_reset": True,
            "candidate": {"run_id": run_id, "worktree": str(doc_path.resolve())},
        },
    ))
    workflows = {}

    def resolve_workflow(**kwargs):
        operation = kwargs["operation"]
        workflow = ResolvedWorkflow(
            provider="codex",
            operation=operation,
            workflow_name=operation,
            workflow_path=f".agents/skills/openspec-{operation}/SKILL.md",
            workflow_sha256=f"{operation}-sha",
            change_name=run.change_name,
            dispatch_command=f"openspec {operation} {run.change_name}",
        )
        workflows[operation] = workflow
        return workflow

    agent_runner = SimpleNamespace(resolve_workflow=MagicMock(side_effect=resolve_workflow))
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=object(),
        worktree_manager=object(),
        agent_runner=agent_runner,
    )
    coordinator._begin_stage_invocation = AsyncMock(
        side_effect=lambda *_args, **_kwargs: SimpleNamespace(claim=object())
    )
    coordinator._run_claimed = AsyncMock(
        return_value=SimpleNamespace(exit_code=0, timed_out=False, workflow_handoff=None)
    )
    coordinator._finish_stage_invocation = AsyncMock()
    coordinator._doc_closing_changed_spec_paths = AsyncMock(return_value=set())
    coordinator._observe_doc_closing_change = MagicMock(return_value=("archived_complete", ""))

    completed = await coordinator._run_sync_and_archive(
        doc_path,
        provider="codex",
        change_name=run.change_name,
        project_id=run.project_id,
        uow=uow,
        run=run,
    )

    assert completed
    assert [call.args[3] for call in coordinator._begin_stage_invocation.await_args_list] == [
        "SYNC", "ARCHIVE"
    ]
    assert coordinator._begin_stage_invocation.await_args_list[0].kwargs[
        "allow_doc_sync_replay"
    ] is True
    assert [call.kwargs["operation"] for call in agent_runner.resolve_workflow.call_args_list] == [
        "sync", "archive"
    ]
    assert coordinator._run_claimed.await_count == 2


@pytest.mark.asyncio
async def test_orchestration_continuity_worktree_preserved_on_failure(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    candidate_worktree = managed_root / "request-401-database-connection-pooling"
    candidate_worktree.mkdir(parents=True, exist_ok=True)

    # Dummy workflows inside candidate worktree
    skill_dir = candidate_worktree / ".agents" / "skills"
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
                "number": 401,
                "title": "Database connection pooling",
                "body": "Add pooling",
                "labels": [],
                "created_at": "2026-10-23T10:00:00Z",
                "updated_at": "2026-10-23T10:00:00Z",
                "html_url": "https://github.com/org/proj-1/issues/401",
            }
        ],
    )
    github_mock.create_pull_request = AsyncMock(return_value={"number": 20, "html_url": "https://github.com/org/proj-1/pull/20"})
    github_mock.merge_pull_request = AsyncMock(return_value={"merged": False, "message": "Branch protection required review"})

    wt_manager = WorktreeManager(repo_dir, uow=uow)
    candidate_worktree = managed_root / "request-401-database-connection-pooling"
    candidate_worktree.mkdir(parents=True, exist_ok=True)
    wt_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=candidate_worktree, branch_name="request-401-database-connection-pooling", base_sha="sha1")
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
    coordinator._get_git_head_sha = AsyncMock(return_value="head_sha_401")
    async def git_result(_cwd, args):
        output = "candidate-sha\n" if args[:2] == ["rev-parse", "HEAD"] else "request-401-database-connection-pooling\n"
        return GitCommandResult(tuple(args), 0, output, "")

    coordinator._git_run = AsyncMock(side_effect=git_result)

    # Run should encounter PR1 merge failure due to branch protection
    result = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="codex",
        implementer_provider="codex",
        reviewer_provider="codex",
    )

    assert result.status == "PAUSED"
    assert result.current_stage == OrchestrationStage.EXPLORING
    assert "Explore" in result.message
    # Critical requirement: Worktree MUST be preserved, not deleted!
    assert candidate_worktree.exists()

    # Active run record MUST remain active in PostgreSQL (not abandoned or unlocked)
    active_runs = uow.orchestration_runs.list_runs(project_id="proj-1", is_active=True)
    assert len(active_runs) == 1
    assert active_runs[0].current_stage == OrchestrationStage.EXPLORING



