"""Unit tests for polyglot CandidateTestResolver (Ref #359)."""

from pathlib import Path

import pytest

from minime.services.candidate_test_resolver import (
    CandidateTestResolver,
    CandidateTestStrategyKind,
)
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator


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


def test_tooling_inventory_exposes_only_database_test_identity_and_named_ci_check(tmp_path: Path):
    check = {
        "name": "postgres-tests",
        "command": "pytest tests/db --database-url postgresql://user:password@db/prod",
        "uses_test_database": True,
        "pr_ci_check_name": "Backend / PostgreSQL",
        "database_url": "postgresql://user:password@db/prod",
    }

    inventory = CandidateTestResolver.inspect_tooling(tmp_path, project_checks=[check])

    configured = inventory["configured_checks"][0]
    assert configured["name"] == "postgres-tests"
    assert configured["uses_test_database"] is True
    assert configured["pr_ci_check_name"] == "Backend / PostgreSQL"
    assert "password" not in repr(inventory)
    assert "database_url" not in repr(inventory)


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
    (tmp_path / "package.json").write_text(
        '{"name": "multiplo", "scripts": {"test": "node --version"}}', encoding="utf-8"
    )

    plan = CandidateTestResolver.resolve(
        tmp_path,
        {"index.html", "css/styles.css", "js/app.js", "tests/unit.test.js"},
    )
    assert plan.kind == CandidateTestStrategyKind.NODE_ROOT
    assert plan.is_executable is True
    assert plan.command == ["npm", "run", "test"]
    assert plan.cwd == tmp_path


def test_monorepo_frontend_subfolder_detection(tmp_path: Path):
    # Like mini-me: frontend/package.json
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "package.json").write_text(
        '{"name": "ui", "scripts": {"test": "node --version"}}', encoding="utf-8"
    )

    plan = CandidateTestResolver.resolve(
        tmp_path,
        {"frontend/src/app.ts", "openspec/changes/req-1/tasks.md"},
    )
    assert plan.kind == CandidateTestStrategyKind.NODE_SUBDIRECTORY
    assert plan.is_executable is True
    assert plan.command == ["npm", "--prefix", "frontend", "run", "test"]


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
    assert "command: npm run test" in evidence
    assert "exit_code: 0" in evidence
    assert "candidate_sha:" in evidence
    assert "duration_ms:" in evidence


@pytest.mark.asyncio
async def test_coordinator_python_test_child_does_not_receive_host_provider_credentials(
    monkeypatch, tmp_path
):
    repo = _git_init_repo(tmp_path)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_feature.py").write_text(
        "import os\n"
        "def test_candidate_test_environment_is_sanitized():\n"
        "    assert all(key not in os.environ for key in (\n"
        "        'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY',\n"
        "        'CUSTOM_SERVICE_API_KEY', 'CUSTOM_SERVICE_SECRET',\n"
        "        'AWS_ACCESS_KEY_ID', 'POSTGRES_PASSWORD', 'GITHUB_TOKEN',\n"
        "        'ANTHROPIC_AUTH_TOKEN', 'HOST_ONLY_SETTING'))\n"
        "    assert os.environ.get('PATH')\n"
        "    assert os.environ.get('HOME')\n"
        "    assert os.environ.get('LANG') == 'en_US.UTF-8'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "host-deepseek-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "host-openai-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "host-anthropic-secret")
    monkeypatch.setenv("CUSTOM_SERVICE_API_KEY", "host-custom-secret")
    monkeypatch.setenv("CUSTOM_SERVICE_SECRET", "host-infra-secret")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "host-aws-secret")
    monkeypatch.setenv("POSTGRES_PASSWORD", "host-postgres-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "host-github-secret")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "host-anthropic-secret")
    monkeypatch.setenv("HOST_ONLY_SETTING", "not-for-candidate")
    monkeypatch.setenv("LANG", "en_US.UTF-8")

    coord = NativeOrchestrationCoordinator(
        uow_factory=lambda: None,
        github_adapter=None,
        worktree_manager=None,
        agent_runner=None,
    )
    passed, evidence = await coord._run_automated_tests(repo, "main")

    assert passed, evidence
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


def test_resolver_prefers_declared_playwright_script(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "node --test", "test:e2e": "playwright test"}}', encoding="utf-8"
    )

    plan = CandidateTestResolver.resolve(tmp_path, {"src/app.js"})

    assert plan.command == ["npm", "run", "test:e2e"]


def test_resolver_uses_declared_makefile_test_target(tmp_path: Path):
    (tmp_path / "Makefile").write_text("test:\n\tpytest -q\n", encoding="utf-8")

    plan = CandidateTestResolver.resolve(tmp_path, {"src/app.py"})

    assert plan.kind == CandidateTestStrategyKind.MAKEFILE_TEST
    assert plan.command == ["make", "test"]


def test_resolver_does_not_invent_undeclared_node_test(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "no-test-script"}', encoding="utf-8")

    plan = CandidateTestResolver.resolve(tmp_path, {"src/app.js"})

    assert plan.kind == CandidateTestStrategyKind.NO_HARNESS_DETECTED
    assert not plan.is_executable


def test_tooling_inventory_is_bounded_and_reports_declared_browser_capability(tmp_path: Path, monkeypatch):
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test:e2e": "playwright test --project=chromium"}, '
        '"devDependencies": {"@playwright/test": "^1.65.0"}}', encoding="utf-8"
    )
    runtime_browser = tmp_path / "playwright-browsers" / "chromium-headless-shell-123" / "chrome-headless-shell"
    runtime_browser.parent.mkdir(parents=True)
    runtime_browser.write_text("#!/bin/sh\necho Chromium 123\n", encoding="utf-8")
    runtime_browser.chmod(0o755)
    monkeypatch.setattr(
        "minime.services.candidate_test_resolver.PLAYWRIGHT_BROWSERS_PATH",
        str(runtime_browser.parents[1]),
    )
    monkeypatch.setattr(
        "minime.services.candidate_test_resolver.subprocess.run",
        lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": "Chromium 123", "stderr": ""})(),
    )

    inventory = CandidateTestResolver.inspect_tooling(tmp_path)

    assert inventory["playwright_declared"] is True
    assert inventory["playwright_packages"] == [{"name": "@playwright/test", "version": "^1.65.0"}]
    assert inventory["declared_test_commands"][0]["command"] == "npm run test:e2e"
    assert inventory["declared_test_commands"][0]["declared_command"] == "playwright test --project=chromium"
    assert inventory["chromium_runtime"] == {
        "available": True,
        "executable": str(runtime_browser),
        "version": "Chromium 123",
    }


def test_playwright_runtime_path_is_fixed_and_missing_browser_has_no_fallback(tmp_path: Path, monkeypatch):
    from minime.config import PLAYWRIGHT_BROWSERS_PATH
    from minime.services.agent_confinement import AgentProcessConfinement

    environment = AgentProcessConfinement.prepare_candidate_test_environment(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": "/usr/bin",
            "PLAYWRIGHT_BROWSERS_PATH": str(tmp_path / "user-cache"),
        }
    )
    assert environment["PLAYWRIGHT_BROWSERS_PATH"] == PLAYWRIGHT_BROWSERS_PATH

    monkeypatch.setattr(
        "minime.services.candidate_test_resolver.PLAYWRIGHT_BROWSERS_PATH",
        str(tmp_path / "missing-runtime-browsers"),
    )
    inventory = CandidateTestResolver.inspect_tooling(tmp_path)
    assert inventory["chromium_runtime"] == {
        "available": False,
        "executable": None,
        "version": None,
    }
