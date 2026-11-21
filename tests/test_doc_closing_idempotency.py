from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import ExternalOutcome, OrchestrationStage
from minime.domain.models import ExternalActionResult, OrchestrationRun, Project
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeInfo


def _archived_change(doc_path: Path, change_name: str = "issue-263-doc-closing-idempotency") -> Path:
    archived = (
        doc_path
        / "openspec"
        / "changes"
        / "archive"
        / f"2026-11-04-{change_name}"
    )
    (archived / "specs" / "two-phase-pr-and-closure").mkdir(parents=True)
    for name in ("proposal.md", "design.md", "tasks.md"):
        (archived / name).write_text("archived artifact\n", encoding="utf-8")
    (archived / "specs" / "two-phase-pr-and-closure" / "spec.md").write_text(
        "## MODIFIED Requirements\n", encoding="utf-8"
    )
    (doc_path / "openspec" / "specs" / "two-phase-pr-and-closure").mkdir(parents=True)
    (doc_path / "openspec" / "specs" / "two-phase-pr-and-closure" / "spec.md").write_text(
        "## Requirements\n", encoding="utf-8"
    )
    return archived


def _init_git_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test User"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-m", "test base"],
        check=True,
        capture_output=True,
        text=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_doc_closing_probe_keeps_active_change_on_native_workflow_path(tmp_path: Path):
    change_name = "issue-263-doc-closing-idempotency"
    (tmp_path / "openspec" / "changes" / change_name).mkdir(parents=True)

    state, detail = NativeOrchestrationCoordinator._observe_doc_closing_change(
        tmp_path, change_name
    )

    assert state == "active"
    assert "active Change" in detail


def test_doc_closing_probe_recognizes_complete_date_prefixed_archive(tmp_path: Path):
    change_name = "issue-263-doc-closing-idempotency"
    _archived_change(tmp_path, change_name)

    state, detail = NativeOrchestrationCoordinator._observe_doc_closing_change(
        tmp_path, change_name
    )

    assert state == "archived_complete"
    assert "corresponding main specs" in detail


@pytest.mark.asyncio
async def test_doc_closing_dispatches_native_workflows_only_for_active_change(
    tmp_path: Path,
):
    change_name = "issue-263-doc-closing-idempotency"
    active = tmp_path / "active"
    (active / "openspec" / "changes" / change_name).mkdir(parents=True)
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=SimpleNamespace(),
        worktree_manager=SimpleNamespace(),
        agent_runner=SimpleNamespace(),
    )
    _init_git_repo(active)

    async def complete_archive(path, *_args, **_kwargs):
        (path / "openspec" / "changes" / change_name).rmdir()
        _archived_change(path, change_name)
        return True

    coordinator._run_sync_and_archive = AsyncMock(side_effect=complete_archive)

    active_result = await coordinator._ensure_doc_closing_sync_archive(
        active, "codex", change_name
    )

    assert active_result == (True, None)
    coordinator._run_sync_and_archive.assert_awaited_once_with(
        active, "codex", change_name, project_id=None, uow=None, run=None,
        operator_response=None, operator_action_id=None,
    )

    archived = tmp_path / "archived"
    _archived_change(archived, change_name)
    archived_head = _init_git_repo(archived)
    coordinator._run_sync_and_archive.reset_mock()
    archived_result = await coordinator._ensure_doc_closing_sync_archive(
        archived, "codex", change_name
    )

    assert archived_result == (True, None)
    coordinator._run_sync_and_archive.assert_not_awaited()
    assert subprocess.run(
        ["git", "-C", str(archived), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip() == archived_head


@pytest.mark.asyncio
async def test_reentry_commits_pending_openspec_paths_before_pr2(tmp_path: Path):
    doc_path = tmp_path / "doc"
    _init_git_repo(doc_path)
    _archived_change(doc_path)

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=SimpleNamespace(),
        worktree_manager=SimpleNamespace(),
        agent_runner=SimpleNamespace(),
    )

    result = await coordinator._ensure_doc_closing_sync_archive(
        doc_path, "codex", "issue-263-doc-closing-idempotency"
    )

    assert result == (True, None)
    assert subprocess.run(
        ["git", "-C", str(doc_path), "log", "-1", "--format=%s"],
        check=True, capture_output=True, text=True,
    ).stdout.strip() == "docs(issue-263-doc-closing-idempotency): sync specs and archive change"
    assert not subprocess.run(
        ["git", "-C", str(doc_path), "status", "--porcelain", "--", "openspec/"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.mark.asyncio
async def test_reentry_refuses_openspec_commit_with_unrelated_staged_paths(tmp_path: Path):
    doc_path = tmp_path / "doc"
    base_head = _init_git_repo(doc_path)
    _archived_change(doc_path)
    unrelated = doc_path / "notes.txt"
    unrelated.write_text("must not be included", encoding="utf-8")
    subprocess.run(["git", "-C", str(doc_path), "add", "notes.txt"], check=True)

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=SimpleNamespace(),
        worktree_manager=SimpleNamespace(),
        agent_runner=SimpleNamespace(),
    )

    result = await coordinator._ensure_doc_closing_sync_archive(
        doc_path, "codex", "issue-263-doc-closing-idempotency"
    )

    assert result[0] is False
    assert "unrelated paths are already staged" in result[1]
    assert subprocess.run(
        ["git", "-C", str(doc_path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip() == base_head
    assert "notes.txt" in subprocess.run(
        ["git", "-C", str(doc_path), "diff", "--cached", "--name-only"],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.mark.parametrize("missing", ["proposal.md", "design.md", "tasks.md", "main_spec"])
def test_doc_closing_probe_does_not_accept_incomplete_archive(tmp_path: Path, missing: str):
    change_name = "issue-263-doc-closing-idempotency"
    archived = _archived_change(tmp_path, change_name)
    if missing == "main_spec":
        (tmp_path / "openspec" / "specs" / "two-phase-pr-and-closure" / "spec.md").unlink()
    else:
        (archived / missing).unlink()

    state, detail = NativeOrchestrationCoordinator._observe_doc_closing_change(
        tmp_path, change_name
    )

    assert state == "incomplete"
    assert detail


def test_doc_closing_probe_rejects_duplicate_archive_matches(tmp_path: Path):
    change_name = "issue-263-doc-closing-idempotency"
    _archived_change(tmp_path, change_name)
    duplicate = tmp_path / "openspec" / "changes" / "archive" / f"2026-11-03-{change_name}"
    duplicate.mkdir()

    state, detail = NativeOrchestrationCoordinator._observe_doc_closing_change(
        tmp_path, change_name
    )

    assert state == "ambiguous"
    assert "found 2" in detail


def test_doc_closing_probe_rejects_active_and_archived_change_together(tmp_path: Path):
    change_name = "issue-263-doc-closing-idempotency"
    _archived_change(tmp_path, change_name)
    (tmp_path / "openspec" / "changes" / change_name).mkdir(parents=True)

    state, detail = NativeOrchestrationCoordinator._observe_doc_closing_change(
        tmp_path, change_name
    )

    assert state == "ambiguous"
    assert "both an active Change" in detail


@pytest.mark.asyncio
async def test_reentry_with_archived_change_skips_workflows_and_continues_to_pr2(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    worktree_parent = tmp_path / "worktrees"
    doc_worktree = worktree_parent / "doc-close-263-doc-closing-idempotency"
    candidate_worktree = worktree_parent / "request-263-doc-closing-idempotency"
    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow,
        "issue-263-project",
        repo,
        worktree_parent,
        canonical_repository_identity="github.com/silverberdi/mini-me-fixture",
    )
    uow.projects.save(
        Project(
            project_id="issue-263-project",
            display_name="DOC_CLOSING idempotency fixture",
            repository="silverberdi/mini-me-fixture",
        )
    )
    change_name = "issue-263-doc-closing-idempotency"
    _archived_change(doc_worktree, change_name)
    _init_git_repo(doc_worktree)

    run = OrchestrationRun(
        project_id="issue-263-project",
        run_id="run-doc-closing-263",
        change_name=change_name,
        base_sha="base-sha",
        current_stage=OrchestrationStage.DOC_CLOSING,
        resumable_stage=OrchestrationStage.DOC_CLOSING,
        stop_details={
            "issue_number": 263,
            "issue_title": "DOC_CLOSING idempotency fixture",
            "request_normalization": {"normalized_body": "Accepted fixture request"},
        },
    )
    uow.orchestration_runs.save(run)

    github = SimpleNamespace(
        _repo=object(),
        create_pull_request=AsyncMock(
            return_value=ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github-fixture",
                data={"number": 902, "html_url": "https://github.com/silverberdi/mini-me-fixture/pull/902"},
            )
        ),
        get_pull_request_details=AsyncMock(
            return_value=ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="github-fixture",
                data={
                    "state": "open",
                    "head_sha": "dddddddddddddddddddddddddddddddddddddddd",
                    "head_branch": "doc-close-263-doc-closing-idempotency",
                    "base_branch": "main",
                },
            )
        ),
        merge_pull_request=AsyncMock(
            return_value=ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="github-fixture",
                data=None,
            )
        ),
    )
    worktrees = SimpleNamespace(
        create_request_worktree=AsyncMock(
            return_value=WorktreeInfo(
                path=candidate_worktree,
                branch_name="request-263-doc-closing-idempotency",
                base_sha="base-sha",
            )
        ),
        create_documentation_worktree=AsyncMock(
            return_value=WorktreeInfo(
                path=doc_worktree,
                branch_name="doc-close-263-doc-closing-idempotency",
                base_sha="merged-main-sha",
            )
        ),
    )
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=github,
        worktree_manager=worktrees,
        agent_runner=SimpleNamespace(
            resolve_workflow=MagicMock(return_value=SimpleNamespace())
        ),
    )
    coordinator._push_branch = AsyncMock()
    coordinator._get_git_head_sha = AsyncMock(return_value="dddddddddddddddddddddddddddddddddddddddd")
    coordinator._run_sync_and_archive = AsyncMock(return_value=False)

    result = await coordinator.execute_project_request(
        "issue-263-project",
        target_run_id=run.run_id,
        thinker_provider="codex",
    )

    assert result.status == "PAUSED"
    assert result.current_stage == OrchestrationStage.PR2_PENDING
    assert "PR2" in result.message or "documentation PR2" in result.message
    coordinator._run_sync_and_archive.assert_not_awaited()
    github.create_pull_request.assert_awaited_once()
    assert github.create_pull_request.await_args.kwargs["branch"] == (
        "doc-close-263-doc-closing-idempotency"
    )
    assert github.create_pull_request.await_args.kwargs["head_sha"] == "dddddddddddddddddddddddddddddddddddddddd"
