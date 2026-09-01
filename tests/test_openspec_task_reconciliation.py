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


def test_reconcile_verification_tasks_updates_tasks_file(tmp_path):
    tasks_dir = tmp_path / "openspec" / "changes" / "sample-change"
    tasks_dir.mkdir(parents=True)
    tasks_file = tasks_dir / "tasks.md"

    tasks_file.write_text(
        "# Tasks: Sample\n\n"
        "- [x] 1. Implement feature X\n"
        "- [x] 2. Add tests for feature X\n"
        "- [ ] 3. Run test suite and ruff checks to confirm clean pass\n",
        encoding="utf-8",
    )

    tracker = OpenSpecTaskTracker(tmp_path)
    reconciled, ids = tracker.reconcile_verification_tasks(
        "openspec", "sample-change", check_evidence_passed=True
    )

    assert reconciled is True
    assert ids == ["3"]

    tasks = tracker.parse_tasks("openspec", "sample-change")
    assert all(t.complete for t in tasks)

    # Calling again when all complete should return False
    reconciled_again, ids_again = tracker.reconcile_verification_tasks(
        "openspec", "sample-change", check_evidence_passed=True
    )
    assert reconciled_again is False
    assert ids_again == []


def test_reconcile_verification_tasks_does_not_reconcile_substantive_tasks(tmp_path):
    tasks_dir = tmp_path / "openspec" / "changes" / "sample-change"
    tasks_dir.mkdir(parents=True)
    tasks_file = tasks_dir / "tasks.md"

    tasks_file.write_text(
        "# Tasks: Sample\n\n"
        "- [x] 1. Implement feature X\n"
        "- [ ] 2. Add tests for feature X\n"
        "- [ ] 3. Run test suite and ruff checks to confirm clean pass\n",
        encoding="utf-8",
    )

    tracker = OpenSpecTaskTracker(tmp_path)
    reconciled, ids = tracker.reconcile_verification_tasks(
        "openspec", "sample-change", check_evidence_passed=True
    )

    assert reconciled is True
    assert ids == ["3"]

    tasks = tracker.parse_tasks("openspec", "sample-change")
    assert tasks[0].complete is True
    assert tasks[1].complete is False  # Task 2 remained unchecked
    assert tasks[2].complete is True  # Task 3 was reconciled
