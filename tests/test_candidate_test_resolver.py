"""Unit tests for polyglot CandidateTestResolver (Ref #359)."""

from pathlib import Path

from minime.services.candidate_test_resolver import (
    CandidateTestPlan,
    CandidateTestResolver,
    CandidateTestStrategyKind,
)


def test_explicit_project_checks_precedence(tmp_path: Path):
    checks = [{"name": "lint", "command": "npm run lint"}, {"name": "test", "command": "npm test"}]
    # Even if package.json and pyproject.toml exist, checks take precedence
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")

    plan = CandidateTestResolver.resolve(
        tmp_path,
        {"index.html"},
        project_checks=checks,
    )
    assert plan.kind == CandidateTestStrategyKind.PROJECT_CHECKS
    assert plan.is_executable is True
    assert plan.custom_checks == checks


def test_python_selected_tests_precedence(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    selected_tests = ["tests/test_models.py", "tests/test_api.py"]

    plan = CandidateTestResolver.resolve(
        tmp_path,
        {"src/models.py"},
        selected_python_tests=selected_tests,
    )
    assert plan.kind == CandidateTestStrategyKind.PYTHON_PYTEST
    assert plan.is_executable is True
    assert plan.selected_tests == selected_tests
    assert "pytest" in plan.command_text
    assert "tests/test_models.py" in plan.command_text


def test_root_node_project_detection(tmp_path: Path):
    # Like Multiplo: package.json in root, no Python files
    (tmp_path / "package.json").write_text('{"name": "multiplo"}', encoding="utf-8")

    plan = CandidateTestResolver.resolve(
        tmp_path,
        {"index.html", "css/styles.css", "js/app.js", "tests/unit.test.js"},
    )
    assert plan.kind == CandidateTestStrategyKind.NODE_ROOT
    assert plan.is_executable is True
    assert plan.command == ["npm", "test"]
    assert plan.cwd == tmp_path


def test_monorepo_frontend_subfolder_detection(tmp_path: Path):
    # Like mini-me: frontend/package.json
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "package.json").write_text('{"name": "ui"}', encoding="utf-8")

    plan = CandidateTestResolver.resolve(
        tmp_path,
        {"frontend/src/app.ts", "openspec/changes/req-1/tasks.md"},
    )
    assert plan.kind == CandidateTestStrategyKind.NODE_SUBDIRECTORY
    assert plan.is_executable is True
    assert plan.command == ["npm", "--prefix", "frontend", "test"]


def test_rust_cargo_project_detection(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "rust-app"', encoding="utf-8")

    plan = CandidateTestResolver.resolve(
        tmp_path,
        {"src/main.rs"},
    )
    assert plan.kind == CandidateTestStrategyKind.RUST_CARGO
    assert plan.is_executable is True
    assert plan.command == ["cargo", "test"]


def test_go_module_project_detection(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/app\n", encoding="utf-8")

    plan = CandidateTestResolver.resolve(
        tmp_path,
        {"main.go"},
    )
    assert plan.kind == CandidateTestStrategyKind.GO_MODULE
    assert plan.is_executable is True
    assert plan.command == ["go", "test", "./..."]


def test_python_project_no_relevant_tests_diagnostic(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")

    plan = CandidateTestResolver.resolve(
        tmp_path,
        {"src/core/utils.py"},
        selected_python_tests=[],
    )
    assert plan.kind == CandidateTestStrategyKind.NO_RELEVANT_TESTS
    assert plan.is_executable is False
    assert "pytest was not run" in plan.diagnostic
    assert "src/core/utils.py" in plan.diagnostic


def test_unsupported_harness_honest_diagnostic(tmp_path: Path):
    # A markdown / documentation only change without manifests
    plan = CandidateTestResolver.resolve(
        tmp_path,
        {"docs/guide.md", "assets/logo.png"},
    )
    assert plan.kind == CandidateTestStrategyKind.NO_HARNESS_DETECTED
    assert plan.is_executable is False
    assert "pytest" not in plan.diagnostic
    assert "No tests were selected or no supported test harness detected" in plan.diagnostic


def _git_init_repo(path: Path) -> Path:
    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# Project\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, check=True, capture_output=True)
    return path


import pytest
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


@pytest.mark.asyncio
async def test_coordinator_runs_root_node_test_suite(tmp_path: Path):
    repo = _git_init_repo(tmp_path)
    # Add root package.json with node --version test script
    (repo / "package.json").write_text('{"name": "test-node", "scripts": {"test": "node --version"}}', encoding="utf-8")
    (repo / "index.js").write_text("console.log('hi');\n", encoding="utf-8")

    coord = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=None,
        worktree_manager=None,
        agent_runner=None,
    )
    passed, evidence = await coord._run_automated_tests(repo, "main")
    assert passed is True
    assert "command: npm test" in evidence
    assert "exit_code: 0" in evidence


@pytest.mark.asyncio
async def test_coordinator_runs_configured_project_checks(tmp_path: Path):
    repo = _git_init_repo(tmp_path)
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")

    from types import SimpleNamespace

    class FakeProjectRepo:
        def get_by_id(self, project_id: str):
            return SimpleNamespace(
                project_id=project_id,
                checks=[{"name": "echo-check", "command": "echo 'check-passed'"}],
            )

    class FakeUow:
        projects = FakeProjectRepo()

    coord = NativeOrchestrationCoordinator(
        uow_factory=lambda: FakeUow(),
        github_adapter=None,
        worktree_manager=None,
        agent_runner=None,
    )
    coord.uow = FakeUow()

    passed, evidence = await coord._run_automated_tests(repo, "main", project_id="test-proj")
    assert passed is True
    assert "check: echo-check" in evidence
    assert "check-passed" in evidence
    assert "exit_code: 0" in evidence
