"""Composable, fail-closed lifecycle gates backed by canonical evidence."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.models import Project, utc_now


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GateReason:
    code: str
    message: str
    severity: str = "BLOCKER"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GateResult:
    gate_name: str
    status: GateStatus
    reason: GateReason

    @property
    def is_blocking(self) -> bool:
        return self.status is not GateStatus.PASS


def _is_planning_artifact(path: str, planning_root: str) -> bool:
    """Return True when a repo-relative path lives inside the OpenSpec planning tree."""
    normalized = path.replace("\\", "/")
    return normalized == planning_root or normalized.startswith(planning_root + "/")


class LifecycleGate:
    """Base contract for a predicate evaluated from durable/canonical evidence."""

    name = "lifecycle_gate"

    def evaluate(self, **_: Any) -> GateResult:
        raise NotImplementedError


class StrictValidationGate(LifecycleGate):
    """Require the installed OpenSpec CLI to strictly validate a change."""

    name = "strict_validation"

    def __init__(self, openspec_adapter: OpenSpecAdapter):
        self.openspec_adapter = openspec_adapter

    def evaluate(self, *, change_name: str, project_root: str | Path, **_: Any) -> GateResult:
        evidence = self.openspec_adapter.validate_change_strict(change_name, project_root)
        if evidence["status"] == "PASS":
            return GateResult(self.name, GateStatus.PASS, GateReason("OPENSPEC_STRICT_VALIDATION_PASSED", "OpenSpec strict validation passed.", severity="INFO", details=evidence))
        if evidence["status"] == "UNKNOWN":
            return GateResult(self.name, GateStatus.UNKNOWN, GateReason("OPENSPEC_CLI_UNAVAILABLE", "OpenSpec strict validation could not be evaluated.", details=evidence))
        return GateResult(self.name, GateStatus.FAIL, GateReason("OPENSPEC_STRICT_VALIDATION_FAILED", "OpenSpec strict validation failed.", details=evidence))


class ApplyAttributionGate(LifecycleGate):
    """Require an attributable OpenSpec APPLY context with no pre-admission implementation drift.

    The gate answers three questions from canonical evidence:

    1. Does an OpenSpec change exist on disk for the admission target?
    2. Does that change carry the required planning artifacts?
    3. Does any implementation evidence (commits or working-tree modifications
       outside the change's planning directory) already exist relative to the
       registered base boundary?

    Because the gate is evaluated *before* ``OrchestrationRun`` creation, any
    implementation evidence already present necessarily predates the
    orchestration-run boundary. Planning-only OpenSpec artifacts (files under
    the project's ``<openspec_path>/`` tree) are never mistaken for
    implementation, and pre-existing base-branch history is never treated as
    candidate drift.
    """

    name = "apply_attribution"

    def __init__(self, openspec_adapter: OpenSpecAdapter | None = None):
        self.openspec_adapter = openspec_adapter or OpenSpecAdapter()

    def evaluate(
        self,
        *,
        project: Project,
        change_name: str,
        project_root: str | Path,
        boundary: datetime | None = None,
        **_: Any,
    ) -> GateResult:
        root = Path(project_root).resolve()
        boundary = boundary or utc_now()

        artifacts = self.openspec_adapter.evaluate_artifacts(project, change_name, str(root))
        if not artifacts.get("exists"):
            return GateResult(
                self.name,
                GateStatus.FAIL,
                GateReason(
                    "OPENSPEC_CHANGE_MISSING",
                    f"No OpenSpec change '{change_name}' exists for the admission target.",
                    details={"change_name": change_name, "project_root": str(root)},
                ),
            )

        missing = [
            label
            for label, key in (
                ("proposal.md", "proposal_present"),
                ("tasks.md", "tasks_present"),
                ("design.md", "design_present"),
                ("specs/", "specs_present"),
            )
            if not artifacts.get(key)
        ]
        if missing:
            return GateResult(
                self.name,
                GateStatus.FAIL,
                GateReason(
                    "OPENSPEC_ARTIFACTS_INVALID",
                    f"OpenSpec change '{change_name}' is missing required artifacts: "
                    f"{', '.join(missing)}.",
                    details={"change_name": change_name, "missing_artifacts": missing},
                ),
            )

        drift = self._evaluate_attribution(root, project, change_name, boundary)
        if drift.status is GateStatus.UNKNOWN:
            return GateResult(
                self.name,
                GateStatus.UNKNOWN,
                GateReason(
                    "ATTRIBUTION_UNVERIFIABLE",
                    drift.reason.message,
                    details=drift.reason.details,
                ),
            )
        if drift.status is GateStatus.FAIL:
            return drift
        return GateResult(
            self.name,
            GateStatus.PASS,
            GateReason(
                "APPLY_ATTRIBUTION_VERIFIED",
                "Implementation evidence is attributable to an admitted OpenSpec APPLY lifecycle.",
                severity="INFO",
                details={
                    "change_name": change_name,
                    "base_sha": drift.reason.details.get("base_sha"),
                },
            ),
        )

    def _evaluate_attribution(
        self,
        root: Path,
        project: Project,
        change_name: str,
        boundary: datetime,
    ) -> GateResult:
        base_sha = self._resolve_base_sha(root, project.base_branch)
        if base_sha is None:
            return GateResult(
                self.name,
                GateStatus.UNKNOWN,
                GateReason(
                    "ATTRIBUTION_UNVERIFIABLE",
                    f"Cannot resolve the admission base boundary for branch "
                    f"'{project.base_branch}'; attribution is ambiguous.",
                    details={"base_branch": project.base_branch, "project_root": str(root)},
                ),
            )

        planning_root = project.openspec_path
        drift_paths = self._implementation_paths(root, base_sha, planning_root)
        if drift_paths is None:
            return GateResult(
                self.name,
                GateStatus.UNKNOWN,
                GateReason(
                    "ATTRIBUTION_UNVERIFIABLE",
                    "Cannot inspect candidate git state; attribution is ambiguous.",
                    details={"base_sha": base_sha, "project_root": str(root)},
                ),
            )
        if drift_paths:
            return GateResult(
                self.name,
                GateStatus.FAIL,
                GateReason(
                    "LIFECYCLE_DRIFT",
                    "Implementation evidence predates the orchestration-run admission boundary.",
                    details={
                        "base_sha": base_sha,
                        "predating_paths": drift_paths,
                        "boundary": boundary.isoformat(),
                    },
                ),
            )
        return GateResult(
            self.name,
            GateStatus.PASS,
            GateReason(
                "NO_IMPLEMENTATION_DRIFT",
                "No pre-admission implementation evidence detected.",
                severity="INFO",
                details={"base_sha": base_sha},
            ),
        )

    @staticmethod
    def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    @classmethod
    def _resolve_base_sha(cls, root: Path, base_branch: str) -> str | None:
        for ref in (f"origin/{base_branch}", base_branch):
            result = cls._run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], root)
            if result is not None and result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        return None

    @classmethod
    def _implementation_paths(
        cls, root: Path, base_sha: str, planning_root: str
    ) -> list[str] | None:
        """Return candidate implementation paths relative to base, or None if unverifiable."""
        committed = cls._run_git(["diff", "--name-only", base_sha, "HEAD"], root)
        uncommitted = cls._run_git(["diff", "--name-only", "HEAD"], root)
        untracked = cls._run_git(["ls-files", "--others", "--exclude-standard"], root)
        if (
            committed is None
            or committed.returncode != 0
            or uncommitted is None
            or uncommitted.returncode != 0
            or untracked is None
            or untracked.returncode != 0
        ):
            return None

        candidates: list[str] = []
        for stream in (committed, uncommitted, untracked):
            for line in stream.stdout.splitlines():
                path = line.strip()
                if path and not _is_planning_artifact(path, planning_root):
                    candidates.append(path)

        seen: set[str] = set()
        ordered: list[str] = []
        for path in candidates:
            if path not in seen:
                seen.add(path)
                ordered.append(path)
        return ordered


class VerifyGate(LifecycleGate):
    """Require canonical VERIFY evidence before the human merge gate.

    Evaluates three change/candidate-bound conditions:

    1. canonical strict validation (`openspec validate --strict --type change`) passes;
    2. implementation/task coherence (the candidate carries non-planning
       implementation evidence, so checked tasks are not mass-checked);
    3. scope integrity (no candidate change touches OpenSpec state outside the
       change's own directory, e.g. another change or canonical specs).

    The gate is candidate-bound via ``candidate_sha`` and fails closed when
    evidence is unavailable (UNKNOWN) or any condition fails (FAIL).
    """

    name = "verify"

    def __init__(self, openspec_adapter: OpenSpecAdapter | None = None):
        self.openspec_adapter = openspec_adapter or OpenSpecAdapter()

    def evaluate(
        self,
        *,
        project: Project,
        change_name: str,
        project_root: str | Path,
        candidate_sha: str | None = None,
        changed_paths: list[str] | None = None,
        **_: Any,
    ) -> GateResult:
        root = Path(project_root).resolve()

        # 1. Canonical strict validation is authoritative and independent.
        strict = StrictValidationGate(self.openspec_adapter).evaluate(
            change_name=change_name, project_root=str(root)
        )
        if strict.status is GateStatus.FAIL:
            return GateResult(
                self.name,
                GateStatus.FAIL,
                GateReason(
                    "VERIFY_OPENSPEC_INVALID",
                    "OpenSpec strict validation failed.",
                    details=strict.reason.details,
                ),
            )
        if strict.status is GateStatus.UNKNOWN:
            return GateResult(
                self.name,
                GateStatus.UNKNOWN,
                GateReason(
                    "VERIFY_UNVERIFIABLE",
                    strict.reason.message,
                    details=strict.reason.details,
                ),
            )

        if not candidate_sha:
            return GateResult(
                self.name,
                GateStatus.UNKNOWN,
                GateReason(
                    "VERIFY_UNVERIFIABLE",
                    "No candidate SHA bound for verification.",
                    details={"change_name": change_name},
                ),
            )

        if changed_paths is None:
            return GateResult(
                self.name,
                GateStatus.UNKNOWN,
                GateReason(
                    "VERIFY_UNVERIFIABLE",
                    "Candidate diff evidence is unavailable.",
                    details={"change_name": change_name, "candidate_sha": candidate_sha},
                ),
            )

        planning_root = project.openspec_path
        artifacts = self.openspec_adapter.evaluate_artifacts(project, change_name, str(root))
        tasks_count = artifacts.get("tasks_count", 0)
        tasks_remaining = artifacts.get("tasks_remaining", 0)

        # 2. Implementation/task coherence: checked tasks must be backed by
        # non-planning candidate changes; otherwise completion is unsubstantiated.
        implementation_paths = [
            p for p in changed_paths if not _is_planning_artifact(p, planning_root)
        ]
        if not implementation_paths:
            return GateResult(
                self.name,
                GateStatus.FAIL,
                GateReason(
                    "VERIFY_TASK_EVIDENCE_MISSING",
                    "Completed tasks are not backed by candidate implementation evidence.",
                    details={
                        "candidate_sha": candidate_sha,
                        "tasks_count": tasks_count,
                        "tasks_remaining": tasks_remaining,
                        "changed_paths": changed_paths,
                    },
                ),
            )

        # 3. Scope integrity: within the OpenSpec tree, only the change's own
        # directory may be modified. Other changes and canonical specs are out of scope.
        change_dir = f"{planning_root}/changes/{change_name}"
        scope_violations = [
            p
            for p in changed_paths
            if _is_planning_artifact(p, planning_root) and not _is_planning_artifact(p, change_dir)
        ]
        if scope_violations:
            return GateResult(
                self.name,
                GateStatus.FAIL,
                GateReason(
                    "VERIFY_SCOPE_VIOLATION",
                    "Candidate modifies OpenSpec state outside the change's declared scope.",
                    details={"candidate_sha": candidate_sha, "scope_violations": scope_violations},
                ),
            )

        return GateResult(
            self.name,
            GateStatus.PASS,
            GateReason(
                "VERIFY_PASSED",
                "OpenSpec validation, task coherence, and scope integrity verified.",
                severity="INFO",
                details={"candidate_sha": candidate_sha, "changed_paths": changed_paths},
            ),
        )
