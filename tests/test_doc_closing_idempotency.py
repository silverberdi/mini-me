from __future__ import annotations

from pathlib import Path
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
    coordinator._run_sync_and_archive = AsyncMock(return_value=True)

    active_result = await coordinator._ensure_doc_closing_sync_archive(
        active, "codex", change_name
    )

    assert active_result == (True, None)
    coordinator._run_sync_and_archive.assert_awaited_once_with(
        active, "codex", change_name, project_id=None
    )

    archived = tmp_path / "archived"
    _archived_change(archived, change_name)
    coordinator._run_sync_and_archive.reset_mock()
    archived_result = await coordinator._ensure_doc_closing_sync_archive(
        archived, "codex", change_name
    )

    assert archived_result == (True, None)
    coordinator._run_sync_and_archive.assert_not_awaited()


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
