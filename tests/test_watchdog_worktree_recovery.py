import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from minime.services.worktree_manager import WorktreeManager


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.mark.asyncio
async def test_watchdog_removes_only_owned_lock_after_process_and_candidate_proof(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "test")
    _git(repository, "config", "user.email", "test@example.invalid")
    (repository / "tracked.txt").write_text("candidate\n")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-m", "candidate")
    _git(repository, "worktree", "add", "-b", "run-branch", str(worktree), "HEAD")
    candidate_sha = _git(worktree, "rev-parse", "HEAD")

    ownership = SimpleNamespace(
        project_id="project",
        job_id="job",
        run_id="run",
        change_name="change",
        canonical_worktree_path=str(worktree),
        branch="run-branch",
    )
    ownership_repo = SimpleNamespace(get_by_canonical_path=lambda _path: ownership)
    manager = WorktreeManager(
        project_root=repository,
        uow=SimpleNamespace(orchestration_worktree_ownerships=ownership_repo),
    )
    monkeypatch.setattr(manager, "_authorize_mutating_operation", lambda *args, **kwargs: None)

    async def verify_ownership(**_kwargs):
        return None

    monkeypatch.setattr(manager, "_verify_worktree_adoption_proof", verify_ownership)
    git_dir = Path(_git(worktree, "rev-parse", "--absolute-git-dir"))
    lock_path = git_dir / "index.lock"
    lock_bytes = b"orphaned lock evidence"
    lock_path.write_bytes(lock_bytes)

    recovered = await manager.recover_orphaned_index_lock(
        worktree,
        project_id="project",
        job_id="job",
        run_id="run",
        change_name="change",
        candidate_sha=candidate_sha,
        process_absence_proven=True,
    )

    assert recovered == {
        "lock_path": str(lock_path),
        "lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "size_bytes": len(lock_bytes),
        "candidate_sha": candidate_sha,
    }
    assert not lock_path.exists()


@pytest.mark.asyncio
async def test_watchdog_refuses_lock_recovery_without_absence_or_matching_candidate(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "test")
    _git(repository, "config", "user.email", "test@example.invalid")
    (repository / "tracked.txt").write_text("candidate\n")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-m", "candidate")
    _git(repository, "worktree", "add", "-b", "run-branch", str(worktree), "HEAD")
    candidate_sha = _git(worktree, "rev-parse", "HEAD")
    ownership = SimpleNamespace(
        project_id="project",
        job_id="job",
        run_id="run",
        change_name="change",
        canonical_worktree_path=str(worktree),
        branch="run-branch",
    )
    manager = WorktreeManager(
        project_root=repository,
        uow=SimpleNamespace(
            orchestration_worktree_ownerships=SimpleNamespace(
                get_by_canonical_path=lambda _path: ownership
            )
        ),
    )
    monkeypatch.setattr(manager, "_authorize_mutating_operation", lambda *args, **kwargs: None)

    async def verify_ownership(**_kwargs):
        return None

    monkeypatch.setattr(manager, "_verify_worktree_adoption_proof", verify_ownership)
    lock_path = Path(_git(worktree, "rev-parse", "--absolute-git-dir")) / "index.lock"
    lock_path.write_text("preserve")

    with pytest.raises(RuntimeError, match="proven process absence"):
        await manager.recover_orphaned_index_lock(
            worktree,
            project_id="project",
            job_id="job",
            run_id="run",
            change_name="change",
            candidate_sha=candidate_sha,
            process_absence_proven=False,
        )
    with pytest.raises(RuntimeError, match="candidate SHA"):
        await manager.recover_orphaned_index_lock(
            worktree,
            project_id="project",
            job_id="job",
            run_id="run",
            change_name="change",
            candidate_sha="b" * 40,
            process_absence_proven=True,
        )

    assert lock_path.read_text() == "preserve"


@pytest.mark.asyncio
async def test_watchdog_preserves_and_restores_only_attributed_verify_outputs(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "test")
    _git(repository, "config", "user.email", "test@example.invalid")
    (repository / ".gitignore").write_text(".minime/\n")
    (repository / "coverage").mkdir()
    (repository / "coverage" / "summary.xml").write_text("candidate evidence\n")
    (repository / "src.py").write_text("candidate code\n")
    _git(repository, "add", ".gitignore", "coverage/summary.xml", "src.py")
    _git(repository, "commit", "-m", "candidate")
    _git(repository, "worktree", "add", "-b", "run-branch", str(worktree), "HEAD")
    candidate_sha = _git(worktree, "rev-parse", "HEAD")
    ownership = SimpleNamespace(
        project_id="project",
        job_id="job",
        run_id="run",
        change_name="change",
        canonical_worktree_path=str(worktree),
        branch="run-branch",
    )
    manager = WorktreeManager(
        project_root=repository,
        uow=SimpleNamespace(
            orchestration_worktree_ownerships=SimpleNamespace(
                get_by_canonical_path=lambda _path: ownership
            ),
            git_operations=SimpleNamespace(
                save=lambda _operation: None,
                update_status=lambda *args, **kwargs: None,
            ),
            commit=lambda: None,
        ),
    )
    monkeypatch.setattr(manager, "_authorize_mutating_operation", lambda *args, **kwargs: None)

    async def verify_ownership(**_kwargs):
        return None

    monkeypatch.setattr(manager, "_verify_worktree_adoption_proof", verify_ownership)
    (worktree / "coverage" / "summary.xml").write_text("verify output\n")
    (worktree / "test-results").mkdir()
    (worktree / "test-results" / "run.xml").write_text("test output\n")
    source_output = "verify output\n"
    test_output = "test output\n"

    evidence = await manager.recover_verify_generated_outputs(
        worktree,
        project_id="project",
        job_id="job",
        run_id="run",
        change_name="change",
        candidate_sha=candidate_sha,
        attempt_id="attempt_1",
    )

    assert {entry["path"] for entry in evidence["outputs"]} == {
        "coverage/summary.xml",
        "test-results/run.xml",
    }
    assert (worktree / "coverage" / "summary.xml").read_text() == "candidate evidence\n"
    assert not (worktree / "test-results" / "run.xml").exists()
    assert (worktree / ".minime/verify-attempts/attempt_1/captured/coverage/summary.xml").read_text() == source_output
    assert (worktree / ".minime/verify-attempts/attempt_1/captured/test-results/run.xml").read_text() == test_output
    assert _git(worktree, "status", "--porcelain", "--untracked-files=all") == ""


@pytest.mark.asyncio
async def test_watchdog_preserves_unattributed_verify_changes(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "test")
    _git(repository, "config", "user.email", "test@example.invalid")
    (repository / ".gitignore").write_text(".minime/\n")
    (repository / "src.py").write_text("candidate code\n")
    _git(repository, "add", ".gitignore", "src.py")
    _git(repository, "commit", "-m", "candidate")
    _git(repository, "worktree", "add", "-b", "run-branch", str(worktree), "HEAD")
    candidate_sha = _git(worktree, "rev-parse", "HEAD")
    ownership = SimpleNamespace(
        project_id="project",
        job_id="job",
        run_id="run",
        change_name="change",
        canonical_worktree_path=str(worktree),
        branch="run-branch",
    )
    manager = WorktreeManager(
        project_root=repository,
        uow=SimpleNamespace(
            orchestration_worktree_ownerships=SimpleNamespace(
                get_by_canonical_path=lambda _path: ownership
            )
        ),
    )
    monkeypatch.setattr(manager, "_authorize_mutating_operation", lambda *args, **kwargs: None)

    async def verify_ownership(**_kwargs):
        return None

    monkeypatch.setattr(manager, "_verify_worktree_adoption_proof", verify_ownership)
    (worktree / "src.py").write_text("unattributed Verify edit\n")

    with pytest.raises(RuntimeError, match="unattributed path"):
        await manager.recover_verify_generated_outputs(
            worktree,
            project_id="project",
            job_id="job",
            run_id="run",
            change_name="change",
            candidate_sha=candidate_sha,
            attempt_id="attempt_2",
        )

    assert (worktree / "src.py").read_text() == "unattributed Verify edit\n"


@pytest.mark.asyncio
async def test_watchdog_rebaselines_apply_worktree_preserving_openspec_artifacts(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "test")
    _git(repository, "config", "user.email", "test@example.invalid")
    (repository / ".gitignore").write_text(".minime/\n")
    (repository / "src.py").write_text("clean candidate code\n")
    _git(repository, "add", ".gitignore", "src.py")
    _git(repository, "commit", "-m", "candidate")
    _git(repository, "worktree", "add", "-b", "run-branch", str(worktree), "HEAD")
    candidate_sha = _git(worktree, "rev-parse", "HEAD")
    ownership = SimpleNamespace(
        project_id="project",
        job_id="job",
        run_id="run",
        change_name="my-change",
        canonical_worktree_path=str(worktree),
        branch="run-branch",
    )
    manager = WorktreeManager(
        project_root=repository,
        uow=SimpleNamespace(
            orchestration_worktree_ownerships=SimpleNamespace(
                get_by_canonical_path=lambda _path: ownership
            ),
            git_operations=SimpleNamespace(
                save=lambda _operation: None,
                update_status=lambda *args, **kwargs: None,
            ),
            commit=lambda: None,
        ),
    )
    monkeypatch.setattr(manager, "_authorize_mutating_operation", lambda *args, **kwargs: None)

    async def verify_ownership(**_kwargs):
        return None

    monkeypatch.setattr(manager, "_verify_worktree_adoption_proof", verify_ownership)

    # 1. Modify tracked file
    (worktree / "src.py").write_text("dirty uncommitted edits\n")

    # 2. Add untracked code file (scratch debris)
    (worktree / "scratch.astro").write_text("untracked scratch component\n")

    # 3. Add OpenSpec change artifact (MUST be preserved)
    change_dir = worktree / "openspec" / "changes" / "my-change"
    change_dir.mkdir(parents=True)
    proposal_file = change_dir / "proposal.md"
    proposal_file.write_text("# Proposal\nVerified proposal artifact\n")

    # Execute rebaseline
    result = await manager.rebaseline_apply_worktree(
        worktree,
        project_id="project",
        job_id="job",
        run_id="run",
        change_name="my-change",
        candidate_sha=candidate_sha,
        process_absence_proven=True,
    )

    assert result["rebaselined"] is True
    assert result["candidate_sha"] == candidate_sha
    assert "scratch.astro" in result["cleaned_files"]

    # Assert tracked file was restored to candidate clean state
    assert (worktree / "src.py").read_text() == "clean candidate code\n"

    # Assert untracked scratch file was deleted
    assert not (worktree / "scratch.astro").exists()

    # Assert OpenSpec change artifact was strictly preserved
    assert proposal_file.exists()
    assert proposal_file.read_text() == "# Proposal\nVerified proposal artifact\n"

