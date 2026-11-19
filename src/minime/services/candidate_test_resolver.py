"""Candidate test resolution and strategy selection for polyglot project execution."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from minime.logging import redact_secrets


class CandidateTestStrategyKind(str, Enum):
    PROJECT_CHECKS = "PROJECT_CHECKS"
    NODE_ROOT = "NODE_ROOT"
    NODE_SUBDIRECTORY = "NODE_SUBDIRECTORY"
    RUST_CARGO = "RUST_CARGO"
    GO_MODULE = "GO_MODULE"
    PYTHON_PYTEST = "PYTHON_PYTEST"
    MAKEFILE_TEST = "MAKEFILE_TEST"
    NO_HARNESS_DETECTED = "NO_HARNESS_DETECTED"
    NO_RELEVANT_TESTS = "NO_RELEVANT_TESTS"


@dataclass(frozen=True)
class CandidateTestPlan:
    """Resolved test execution plan for candidate worktree."""

    kind: CandidateTestStrategyKind
    is_executable: bool
    command: list[str] = field(default_factory=list)
    cwd: Path = field(default_factory=Path)
    diagnostic: str = ""
    custom_checks: list[dict[str, Any]] = field(default_factory=list)
    selected_tests: list[str] = field(default_factory=list)

    @property
    def command_text(self) -> str:
        return shlex.join(self.command) if self.command else ""


class CandidateTestResolver:
    """Discovers and resolves the native test execution strategy for a candidate worktree."""

    PYTHON_MANIFESTS = ("pyproject.toml", "pytest.ini", "setup.py", "setup.cfg", "requirements.txt")
    INVENTORY_FILE_LIMIT = 256_000
    INVENTORY_COMMAND_LIMIT = 32
    INVENTORY_COMMAND_LENGTH = 1000

    @classmethod
    def _read_candidate_manifest(cls, path: Path, root: Path) -> str | None:
        try:
            if path.is_symlink():
                return None
            resolved_root = root.resolve(strict=True)
            resolved_path = path.resolve(strict=True)
            resolved_path.relative_to(resolved_root)
            if not resolved_path.is_file() or resolved_path.stat().st_size > cls.INVENTORY_FILE_LIMIT:
                return None
            return resolved_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            return None

    @classmethod
    def inspect_tooling(
        cls,
        worktree_path: Path,
        *,
        project_checks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return bounded, read-only evidence about declared test commands and Chromium."""
        declared: list[dict[str, str]] = []
        configured: list[dict[str, str]] = []
        manifests: list[str] = []
        playwright_packages: list[dict[str, str]] = []

        def add(source: str, name: str, command: str) -> None:
            command = command.strip()
            if command and len(command) <= cls.INVENTORY_COMMAND_LENGTH:
                declared.append({"source": source, "name": name[:120], "command": command})

        for check in (project_checks or ())[: cls.INVENTORY_COMMAND_LIMIT]:
            if isinstance(check, dict):
                command = str(check.get("command") or "").strip()
                if command and len(command) <= cls.INVENTORY_COMMAND_LENGTH:
                    configured.append(
                        {
                            "source": "project.checks",
                            "name": str(check.get("name") or "configured-check")[:120],
                            "command": redact_secrets(command),
                        }
                    )

        for relative in ("package.json", "frontend/package.json"):
            path = worktree_path / relative
            raw_manifest = cls._read_candidate_manifest(path, worktree_path)
            if raw_manifest is None:
                continue
            try:
                manifest = json.loads(raw_manifest)
            except json.JSONDecodeError:
                continue
            manifests.append(relative)
            scripts = manifest.get("scripts", {}) if isinstance(manifest, dict) else {}
            dependencies = {}
            if isinstance(manifest, dict):
                dependencies.update(manifest.get("dependencies", {}) or {})
                dependencies.update(manifest.get("devDependencies", {}) or {})
            if isinstance(dependencies, dict):
                for package_name in ("playwright", "playwright-core", "@playwright/test"):
                    version = dependencies.get(package_name)
                    if isinstance(version, str):
                        playwright_packages.append({"name": package_name, "version": version[:80]})
            if isinstance(scripts, dict):
                for name, command in scripts.items():
                    key = str(name).lower()
                    value = str(command) if isinstance(command, str) else ""
                    if value and ("test" in key or "playwright" in key or key in {"e2e", "check"}):
                        add(
                            relative,
                            str(name),
                            f"npm {'--prefix frontend ' if relative.startswith('frontend/') else ''}run {name}",
                        )
                        if declared:
                            declared[-1]["declared_command"] = redact_secrets(value)[: cls.INVENTORY_COMMAND_LENGTH]

        pyproject = worktree_path / "pyproject.toml"
        pyproject_text = cls._read_candidate_manifest(pyproject, worktree_path)
        if pyproject_text is not None:
            try:
                manifest = tomllib.loads(pyproject_text)
            except tomllib.TOMLDecodeError:
                manifest = {}
            else:
                manifests.append("pyproject.toml")
            pytest_config = manifest.get("tool", {}).get("pytest", {}).get("ini_options", {})
            if isinstance(pytest_config, dict) and (pytest_config.get("testpaths") or pytest_config.get("addopts")):
                add("pyproject.toml", "pytest", "python -m pytest")

        makefile = worktree_path / "Makefile"
        makefile_text = cls._read_candidate_manifest(makefile, worktree_path)
        if makefile_text is not None:
            lines = makefile_text.splitlines()
            manifests.append("Makefile")
            for line in lines:
                target = line.split(":", 1)[0].strip() if ":" in line and not line[0:1].isspace() else ""
                if target and re.fullmatch(r"(?:test|tests|e2e|test[-_][A-Za-z0-9_.-]+)", target):
                    add("Makefile", target, f"make {target}")

        browser_candidates: list[str] = []
        shared_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(
            Path.home() / "Library" / "Caches" / "ms-playwright"
            if sys.platform == "darwin"
            else Path.home() / ".cache" / "ms-playwright"
        )
        if shared_path:
            cache = Path(shared_path)
            if cache.is_dir():
                browser_candidates.extend(
                    str(path)
                    for pattern in ("**/chrome-headless-shell", "**/headless_shell", "**/chrome")
                    for path in cache.glob(pattern)
                    if path.is_file() and os.access(path, os.X_OK)
                )
        browser_candidates.extend(
            path for name in ("chromium", "chromium-browser", "google-chrome")
            if (path := shutil.which(name))
        )
        chromium = next(iter(dict.fromkeys(browser_candidates)), None)
        browser: dict[str, Any] = {"available": False, "executable": None, "version": None}
        if chromium:
            browser["executable"] = chromium
            try:
                result = subprocess.run(
                    [chromium, "--version"], capture_output=True, text=True, timeout=3, check=False
                )
                if result.returncode == 0:
                    browser["available"] = True
                    browser["version"] = (result.stdout or result.stderr).strip()[:200]
            except (OSError, subprocess.TimeoutExpired):
                pass

        return {
            "configured_checks": configured,
            "manifests_observed": manifests,
            "declared_test_commands": declared[: cls.INVENTORY_COMMAND_LIMIT],
            "playwright_packages": playwright_packages,
            "playwright_declared": bool(playwright_packages) or any(
                "playwright" in entry["command"].lower()
                or "playwright" in entry.get("declared_command", "").lower()
                or "playwright" in entry["name"].lower()
                for entry in declared
            ),
            "chromium_runtime": browser,
        }

    @classmethod
    def is_python_project(cls, worktree_path: Path, changed_paths: set[str] | None = None) -> bool:
        """Inspects if the candidate exhibits Python project characteristics."""
        for manifest in cls.PYTHON_MANIFESTS:
            if (worktree_path / manifest).is_file():
                return True
        if changed_paths:
            if any(p.endswith(".py") for p in changed_paths):
                return True
        return False

    @classmethod
    def resolve(
        cls,
        worktree_path: Path,
        changed_paths: set[str],
        *,
        project_checks: list[dict[str, Any]] | None = None,
        selected_python_tests: list[str] | None = None,
    ) -> CandidateTestPlan:
        """Determines the appropriate test strategy in strict order of prevalence."""
        # 1. Explicit project checks take highest precedence
        if project_checks and len(project_checks) > 0:
            return CandidateTestPlan(
                kind=CandidateTestStrategyKind.PROJECT_CHECKS,
                is_executable=True,
                cwd=worktree_path,
                custom_checks=list(project_checks),
            )

        # 2. Root Node / JavaScript / TypeScript project
        root_package_json = worktree_path / "package.json"
        if root_package_json.is_file():
            node_plan = cls._declared_node_plan(root_package_json, worktree_path)
            if node_plan:
                return node_plan

        # 4. Monorepo subproject Node (e.g. frontend/package.json)
        frontend_package_json = worktree_path / "frontend" / "package.json"
        if frontend_package_json.is_file():
            frontend_changes = {
                p for p in changed_paths
                if p.startswith("frontend/") or p.startswith("openspec/") or p.endswith(".md")
            }
            if frontend_changes == changed_paths and any(p.startswith("frontend/") for p in changed_paths):
                node_plan = cls._declared_node_plan(frontend_package_json, worktree_path, prefix="frontend")
                if node_plan:
                    return node_plan

        # 3. Declared Makefile test targets (only invoke a fixed make target).
        make_targets = cls._declared_make_targets(worktree_path / "Makefile")
        if make_targets:
            selected = next((name for name in ("test", "tests", "e2e") if name in make_targets), make_targets[0])
            return CandidateTestPlan(
                kind=CandidateTestStrategyKind.MAKEFILE_TEST,
                is_executable=True,
                command=["make", selected],
                cwd=worktree_path,
                diagnostic=f"Declared Makefile target: {selected}",
            )

        # 4. Focused Python test selection where no project-declared runner exists.
        if selected_python_tests and len(selected_python_tests) > 0:
            cmd = [sys.executable, "-m", "pytest", "-q", *selected_python_tests]
            return CandidateTestPlan(
                kind=CandidateTestStrategyKind.PYTHON_PYTEST,
                is_executable=True,
                command=cmd,
                cwd=worktree_path,
                selected_tests=list(selected_python_tests),
            )

        # 6. Rust Cargo project
        if (worktree_path / "Cargo.toml").is_file():
            return CandidateTestPlan(
                kind=CandidateTestStrategyKind.RUST_CARGO,
                is_executable=True,
                command=["cargo", "test"],
                cwd=worktree_path,
            )

        # 7. Go Module project
        if (worktree_path / "go.mod").is_file():
            return CandidateTestPlan(
                kind=CandidateTestStrategyKind.GO_MODULE,
                is_executable=True,
                command=["go", "test", "./..."],
                cwd=worktree_path,
            )

        sorted_changes = ", ".join(sorted(changed_paths)) or "(none)"

        # 8. Python project with no relevant tests selected
        if cls.is_python_project(worktree_path, changed_paths):
            return CandidateTestPlan(
                kind=CandidateTestStrategyKind.NO_RELEVANT_TESTS,
                is_executable=False,
                cwd=worktree_path,
                diagnostic=(
                    "Test selection failed: no tests were selected; pytest was not run. "
                    f"Changed files: {sorted_changes}"
                ),
            )

        # 9. Unsupported / no recognized test harness
        return CandidateTestPlan(
            kind=CandidateTestStrategyKind.NO_HARNESS_DETECTED,
            is_executable=False,
            cwd=worktree_path,
            diagnostic=(
                "No tests were selected or no supported test harness detected in candidate worktree. "
                f"Changed files: {sorted_changes}"
            ),
        )

    @classmethod
    def _declared_node_plan(
        cls, manifest_path: Path, worktree_path: Path, *, prefix: str = ""
    ) -> CandidateTestPlan | None:
        raw_manifest = cls._read_candidate_manifest(manifest_path, worktree_path)
        if raw_manifest is None:
            return None
        try:
            manifest = json.loads(raw_manifest)
        except json.JSONDecodeError:
            return None
        scripts = manifest.get("scripts", {}) if isinstance(manifest, dict) else {}
        if not isinstance(scripts, dict):
            return None
        selected = next((str(name) for name in ("test:e2e", "e2e", "test", "tests")
                         if isinstance(scripts.get(name), str) and scripts[name].strip()), None)
        if selected is None:
            selected = next(
                (
                    str(name)
                    for name, script in scripts.items()
                    if isinstance(script, str)
                    and script.strip()
                    and (
                        "test" in str(name).lower()
                        or "playwright" in str(name).lower()
                        or "playwright" in script.lower()
                    )
                ),
                None,
            )
        if not selected:
            return None
        command = ["npm"]
        if prefix:
            command.extend(["--prefix", prefix])
        command.extend(["run", selected])
        return CandidateTestPlan(
            kind=CandidateTestStrategyKind.NODE_SUBDIRECTORY if prefix else CandidateTestStrategyKind.NODE_ROOT,
            is_executable=True,
            command=command,
            cwd=worktree_path,
        )

    @classmethod
    def _declared_make_targets(cls, makefile: Path) -> list[str]:
        raw_makefile = cls._read_candidate_manifest(makefile, makefile.parent)
        if raw_makefile is None:
            return []
        lines = raw_makefile.splitlines()
        targets: list[str] = []
        for line in lines:
            if ":" not in line or line[:1].isspace():
                continue
            target = line.split(":", 1)[0].strip()
            if re.fullmatch(r"(?:test|tests|e2e|test[-_][A-Za-z0-9_.-]+)", target):
                targets.append(target)
        return targets
