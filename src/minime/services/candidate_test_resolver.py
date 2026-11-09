"""Candidate test resolution and strategy selection for polyglot project execution."""

from __future__ import annotations

import json
import shlex
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class CandidateTestStrategyKind(str, Enum):
    PROJECT_CHECKS = "PROJECT_CHECKS"
    NODE_ROOT = "NODE_ROOT"
    NODE_SUBDIRECTORY = "NODE_SUBDIRECTORY"
    RUST_CARGO = "RUST_CARGO"
    GO_MODULE = "GO_MODULE"
    PYTHON_PYTEST = "PYTHON_PYTEST"
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

        # 2. Python focused test selection if pytest tests were selected
        if selected_python_tests and len(selected_python_tests) > 0:
            cmd = [sys.executable, "-m", "pytest", "-q", *selected_python_tests]
            return CandidateTestPlan(
                kind=CandidateTestStrategyKind.PYTHON_PYTEST,
                is_executable=True,
                command=cmd,
                cwd=worktree_path,
                selected_tests=list(selected_python_tests),
            )

        # 3. Root Node / JavaScript / TypeScript project
        root_package_json = worktree_path / "package.json"
        if root_package_json.is_file():
            return CandidateTestPlan(
                kind=CandidateTestStrategyKind.NODE_ROOT,
                is_executable=True,
                command=["npm", "test"],
                cwd=worktree_path,
            )

        # 4. Monorepo subproject Node (e.g. frontend/package.json)
        frontend_package_json = worktree_path / "frontend" / "package.json"
        if frontend_package_json.is_file():
            frontend_changes = {
                p for p in changed_paths
                if p.startswith("frontend/") or p.startswith("openspec/") or p.endswith(".md")
            }
            if frontend_changes == changed_paths and any(p.startswith("frontend/") for p in changed_paths):
                return CandidateTestPlan(
                    kind=CandidateTestStrategyKind.NODE_SUBDIRECTORY,
                    is_executable=True,
                    command=["npm", "--prefix", "frontend", "test"],
                    cwd=worktree_path,
                )

        # 5. Rust Cargo project
        if (worktree_path / "Cargo.toml").is_file():
            return CandidateTestPlan(
                kind=CandidateTestStrategyKind.RUST_CARGO,
                is_executable=True,
                command=["cargo", "test"],
                cwd=worktree_path,
            )

        # 6. Go Module project
        if (worktree_path / "go.mod").is_file():
            return CandidateTestPlan(
                kind=CandidateTestStrategyKind.GO_MODULE,
                is_executable=True,
                command=["go", "test", "./..."],
                cwd=worktree_path,
            )

        sorted_changes = ", ".join(sorted(changed_paths)) or "(none)"

        # 7. Python project with no relevant tests selected
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

        # 8. Unsupported / no recognized test harness
        return CandidateTestPlan(
            kind=CandidateTestStrategyKind.NO_HARNESS_DETECTED,
            is_executable=False,
            cwd=worktree_path,
            diagnostic=(
                "No tests were selected or no supported test harness detected in candidate worktree. "
                f"Changed files: {sorted_changes}"
            ),
        )
