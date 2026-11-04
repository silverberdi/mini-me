"""Focused Git-backed tests for Apply/Verify pytest selection and evidence."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from minime.services import orchestration_coordinator as coordinator_module
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _write(repo: Path, relative_path: str, content: str) -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _candidate_repo(repo: Path) -> Path:
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main", str(repo)], check=True
    )
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Focused Test")
    _write(repo, "src/minime/service.py", "VALUE = 1\n")
    _write(
        repo,
        "tests/test_service.py",
        "from minime.service import VALUE\n\ndef test_service():\n    assert VALUE == 1\n",
    )
    _write(repo, "tests/test_unrelated.py", "def test_unrelated():\n    assert True\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "base")
    _git(repo, "switch", "--quiet", "-c", "candidate")
    return repo


def _coordinator() -> NativeOrchestrationCoordinator:
    return NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=SimpleNamespace(),
        worktree_manager=SimpleNamespace(),
        agent_runner=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_changed_file_discovery_includes_commit_index_worktree_and_untracked(tmp_path: Path):
    repo = _candidate_repo(tmp_path)
    _write(repo, "src/minime/service.py", "VALUE = 2\n")
    _git(repo, "add", "src/minime/service.py")
    _git(repo, "commit", "--quiet", "-m", "candidate source update")
    _write(repo, "tests/test_service.py", "def test_service():\n    assert True\n")
    _write(repo, "tests/test_staged.py", "def test_staged():\n    assert True\n")
    _git(repo, "add", "tests/test_staged.py")
    _write(repo, "tests/test_untracked.py", "def test_untracked():\n    assert True\n")

    changed, error = await _coordinator()._git_changed_paths_for_tests(repo, "main")

    assert error is None
    assert changed == {
        "src/minime/service.py",
        "tests/test_service.py",
        "tests/test_staged.py",
        "tests/test_untracked.py",
    }


@pytest.mark.asyncio
async def test_selection_includes_tests_added_or_modified_by_change(tmp_path: Path):
    repo = _candidate_repo(tmp_path)
    _write(repo, "tests/test_new_feature.py", "def test_new_feature():\n    assert True\n")
    changed, error = await _coordinator()._git_changed_paths_for_tests(repo, "main")
    assert error is None
    candidates = set(
        (await _coordinator()._git_run(
            repo, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        )).stdout.split("\0")
    )

    selected = _coordinator()._select_relevant_test_paths(repo, changed or set(), candidates)

    assert "tests/test_new_feature.py" in selected


@pytest.mark.asyncio
async def test_selection_maps_by_module_name_and_excludes_unrelated_tests(tmp_path: Path):
    repo = _candidate_repo(tmp_path)
    _write(repo, "src/minime/service.py", "VALUE = 2\n")
    changed, error = await _coordinator()._git_changed_paths_for_tests(repo, "main")
    assert error is None
    candidates = set(
        (await _coordinator()._git_run(
            repo, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        )).stdout.split("\0")
    )

    selected = _coordinator()._select_relevant_test_paths(repo, changed or set(), candidates)

    assert selected == ["tests/test_service.py"]
    assert "tests/test_unrelated.py" not in selected


@pytest.mark.asyncio
async def test_selection_maps_tests_that_directly_import_changed_module(tmp_path: Path):
    repo = _candidate_repo(tmp_path)
    _write(repo, "src/minime/service.py", "VALUE = 2\n")
    _write(
        repo,
        "tests/test_feature_behavior.py",
        "from minime.service import VALUE\n\ndef test_feature():\n    assert VALUE == 1\n",
    )
    changed, error = await _coordinator()._git_changed_paths_for_tests(repo, "main")
    assert error is None
    candidates = set(
        (await _coordinator()._git_run(
            repo, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        )).stdout.split("\0")
    )

    selected = _coordinator()._select_relevant_test_paths(repo, changed or set(), candidates)

    assert "tests/test_feature_behavior.py" in selected
    assert "tests/test_unrelated.py" not in selected


@pytest.mark.asyncio
async def test_import_index_parses_each_candidate_test_file_once(tmp_path: Path, monkeypatch):
    repo = _candidate_repo(tmp_path)
    _write(repo, "src/minime/service.py", "VALUE = 2\n")
    changed, error = await _coordinator()._git_changed_paths_for_tests(repo, "main")
    assert error is None
    candidates = set(
        (await _coordinator()._git_run(
            repo, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        )).stdout.split("\0")
    )
    original_parse = coordinator_module.ast.parse
    parsed_sources: list[str] = []

    def count_parse(source, *args, **kwargs):
        parsed_sources.append(source)
        return original_parse(source, *args, **kwargs)

    monkeypatch.setattr(coordinator_module.ast, "parse", count_parse)

    selected = _coordinator()._select_relevant_test_paths(repo, changed or set(), candidates)

    assert selected == ["tests/test_service.py"]
    assert len(parsed_sources) == 2
    assert len(set(parsed_sources)) == 2


@pytest.mark.asyncio
async def test_empty_selection_fails_without_running_pytest(tmp_path: Path):
    repo = _candidate_repo(tmp_path)
    _write(repo, "src/minime/uncovered.py", "VALUE = 2\n")

    passed, evidence = await _coordinator()._run_automated_tests(repo, "main")

    assert not passed
    assert "no tests were selected" in evidence.lower()
    assert "pytest was not run" in evidence.lower()
    assert "command:" not in evidence


@pytest.mark.asyncio
async def test_selected_file_with_no_collected_tests_does_not_pass(tmp_path: Path):
    repo = _candidate_repo(tmp_path)
    _write(repo, "tests/test_empty_collected.py", "# Deliberately contains no tests.\n")

    passed, evidence = await _coordinator()._run_automated_tests(repo, "main")

    assert not passed
    assert "selected_tests: tests/test_empty_collected.py" in evidence
    assert "exit_code: 5" in evidence
    assert "no tests ran" in evidence.lower()


@pytest.mark.asyncio
async def test_git_selection_error_fails_closed_without_running_pytest(tmp_path: Path):
    repo = _candidate_repo(tmp_path)

    passed, evidence = await _coordinator()._run_automated_tests(repo, "missing-base")

    assert not passed
    assert "test selection failed" in evidence.lower()
    assert "pytest was not run" in evidence.lower()


@pytest.mark.asyncio
async def test_pytest_command_and_execution_evidence_are_exact(tmp_path: Path):
    repo = _candidate_repo(tmp_path)
    _write(
        repo,
        "tests/test_focused_failure.py",
        "def test_focused_failure():\n    assert False, 'focused-evidence-sentinel'\n",
    )
    expected_command = shlex.join(
        [sys.executable, "-m", "pytest", "-q", "tests/test_focused_failure.py"]
    )

    passed, evidence = await _coordinator()._run_automated_tests(repo, "main")

    assert not passed
    assert "selected_tests: tests/test_focused_failure.py" in evidence
    assert f"command: {expected_command}" in evidence
    assert "exit_code: 1" in evidence
    assert "stdout:" in evidence
    assert "focused-evidence-sentinel" in evidence
    assert "stderr:" in evidence


@pytest.mark.asyncio
async def test_apply_passes_candidate_base_branch_to_test_gate(tmp_path: Path):
    repo = _candidate_repo(tmp_path)
    _write(repo, "openspec/changes/change/tasks.md", "- [x] 1.1 Implement focused tests\n")

    class SuccessfulRunner:
        def resolve_workflow(self, **_kwargs):
            return SimpleNamespace(dispatch_command="openspec apply")

        async def run(self, **_kwargs):
            return SimpleNamespace(
                exit_code=0,
                timed_out=False,
                preflight_error=None,
                environment_error=False,
                structured_output_missing=False,
                structured_output_too_large=False,
                final_response_status="COMPLETE",
                response_output="Apply completed",
                workflow_handoff_required=False,
            )

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=SimpleNamespace(),
        worktree_manager=SimpleNamespace(),
        agent_runner=SuccessfulRunner(),
    )
    observed: list[str] = []

    async def fake_test_gate(worktree_path: Path, base_branch: str):
        assert worktree_path == repo
        observed.append(base_branch)
        return True, "focused evidence"

    coordinator._run_automated_tests = fake_test_gate

    outcome = await coordinator._run_apply(repo, "codex", "change", base_branch="main")

    assert outcome.status == "COMPLETE"
    assert outcome.tests_passed is True
    assert outcome.test_evidence == "focused evidence"
    assert observed == ["main"]
