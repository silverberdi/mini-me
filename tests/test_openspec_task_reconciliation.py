"""Tests for OpenSpec verification task reconciliation."""

from minime.services.openspec_tasks import OpenSpecTask, OpenSpecTaskTracker, is_verification_task


def test_is_verification_task_detection():
    # True cases
    assert is_verification_task(
        OpenSpecTask("3", "Run test suite and ruff checks to confirm clean pass", None, False)
    )
    assert is_verification_task(
        OpenSpecTask("2", "Run pytest to verify all tests pass", None, False)
    )
    assert is_verification_task(
        OpenSpecTask("4", "Execute test suite and confirm clean pass", None, False)
    )
    assert is_verification_task(OpenSpecTask("5", "Run ruff check .", None, False))

    # False cases (substantive tasks)
    assert not is_verification_task(
        OpenSpecTask("1", "Add get_self_hosting_diagnostic method to StatusService", None, False)
    )
    assert not is_verification_task(
        OpenSpecTask("2", "Create unit test tests/test_self_hosting_diagnostic.py", None, False)
    )
    assert not is_verification_task(
        OpenSpecTask("3", "Implement Postgres persistence repository", None, False)
    )


def _setup_test_env(tmp_path):
    import json
    import subprocess

    from minime.domain.enums import WorktreeCreationState
    from minime.domain.models import (
        OrchestrationWorktreeOwnership,
        ProjectManagedRepositoryBinding,
    )

    wt_parent = tmp_path / ".minime" / "worktrees"
    wt_dir = wt_parent / "job-123"
    wt_dir.mkdir(parents=True, exist_ok=True)

    managed_repo = tmp_path / "repo"
    managed_repo.mkdir(parents=True, exist_ok=True)

    for d in (wt_dir, managed_repo):
        subprocess.run(["git", "init"], cwd=d, capture_output=True, check=False)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=d,
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"], cwd=d, capture_output=True, check=False
        )
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/silverberdi/mini-me.git"],
            cwd=d,
            capture_output=True,
            check=False,
        )
        marker = {
            "project_id": "mini-me",
            "canonical_repository_identity": "github.com/silverberdi/mini-me",
        }
        (d / ".minime-managed-project.json").write_text(json.dumps(marker))

    binding = ProjectManagedRepositoryBinding(
        project_id="mini-me",
        canonical_repository_identity="github.com/silverberdi/mini-me",
        managed_repository_root=str(managed_repo),
        worktree_parent_dir=str(wt_parent),
        is_valid=True,
    )
    ownership = OrchestrationWorktreeOwnership(
        worktree_id="wt-123",
        job_id="job-123",
        run_id="run-123",
        change_name="sample-change",
        project_id="mini-me",
        canonical_worktree_path=str(wt_dir),
        source_repository_identity="github.com/silverberdi/mini-me",
        source_base_sha="base123",
        branch="branch-123",
        creation_state=WorktreeCreationState.CREATED,
    )

    class MockBindingRepo:
        def get_by_project_id(self, project_id):
            return binding

    class MockOwnershipRepo:
        def get_by_job_id(self, job_id):
            return ownership

        def get_by_canonical_path(self, path):
            return ownership

        def list_by_project(self, project_id):
            return [ownership]

    class MockUOW:
        def __init__(self):
            self.project_managed_repository_bindings = MockBindingRepo()
            self.orchestration_worktree_ownerships = MockOwnershipRepo()

    return wt_dir, MockUOW()


def test_reconcile_verification_tasks_updates_tasks_file(tmp_path):
    wt_dir, uow = _setup_test_env(tmp_path)
    tasks_dir = wt_dir / "openspec" / "changes" / "sample-change"
    tasks_dir.mkdir(parents=True)
    tasks_file = tasks_dir / "tasks.md"

    tasks_file.write_text(
        "# Tasks: Sample\n\n"
        "- [x] 1. Implement feature X\n"
        "- [x] 2. Add tests for feature X\n"
        "- [ ] 3. Run test suite and ruff checks to confirm clean pass\n",
        encoding="utf-8",
    )

    tracker = OpenSpecTaskTracker(wt_dir)
    reconciled, ids = tracker.reconcile_verification_tasks(
        "openspec",
        "sample-change",
        check_evidence_passed=True,
        project_id="mini-me",
        job_id="job-123",
        uow=uow,
    )

    assert reconciled is True
    assert ids == ["3"]

    tasks = tracker.parse_tasks("openspec", "sample-change")
    assert all(t.complete for t in tasks)

    # Calling again when all complete should return False
    reconciled_again, ids_again = tracker.reconcile_verification_tasks(
        "openspec",
        "sample-change",
        check_evidence_passed=True,
        project_id="mini-me",
        job_id="job-123",
        uow=uow,
    )
    assert reconciled_again is False
    assert ids_again == []


def test_reconcile_verification_tasks_does_not_reconcile_substantive_tasks(tmp_path):
    wt_dir, uow = _setup_test_env(tmp_path)
    tasks_dir = wt_dir / "openspec" / "changes" / "sample-change"
    tasks_dir.mkdir(parents=True)
    tasks_file = tasks_dir / "tasks.md"

    tasks_file.write_text(
        "# Tasks: Sample\n\n"
        "- [x] 1. Implement feature X\n"
        "- [ ] 2. Add tests for feature X\n"
        "- [ ] 3. Run test suite and ruff checks to confirm clean pass\n",
        encoding="utf-8",
    )

    tracker = OpenSpecTaskTracker(wt_dir)
    reconciled, ids = tracker.reconcile_verification_tasks(
        "openspec",
        "sample-change",
        check_evidence_passed=True,
        project_id="mini-me",
        job_id="job-123",
        uow=uow,
    )

    assert reconciled is True
    assert ids == ["3"]

    tasks = tracker.parse_tasks("openspec", "sample-change")
    assert tasks[0].complete is True
    assert tasks[1].complete is False  # Task 2 remained unchecked
    assert tasks[2].complete is True  # Task 3 was reconciled
