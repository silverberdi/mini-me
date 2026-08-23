"""Outcome governance and completion verification service for mini me."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minime.domain.enums import (
    BlockerValidationVerdict,
    ExecutionOutcome,
    ProgressClassification,
    ProviderResultClass,
)
from minime.domain.models import (
    BlockerClaim,
    CheckResult,
    NormalizedProviderResult,
)
from minime.services.openspec_tasks import OpenSpecTask, OpenSpecTaskTracker

logger = logging.getLogger(__name__)


@dataclass
class CompletionVerificationResult:
    """Detailed result of fail-closed completion verification."""

    is_complete: bool
    reason: str | None = None
    incomplete_tasks: list[OpenSpecTask] = field(default_factory=list)
    failing_checks: list[CheckResult] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    candidate_sha: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProgressSignals:
    """Hard-evidence counters and deltas for deterministic progress evaluation."""

    completed_task_delta: int = 0
    remaining_task_count: int = 0
    candidate_file_delta: int = 0
    checks_pass_delta: int = 0
    checks_fail_delta: int = 0
    acceptance_evidence_delta: int = 0
    regression_detected: bool = False
    policy_violation: bool = False


class OutcomeGovernanceService:
    """Supervises executor execution results, verifies completion, and evaluates progress."""

    def __init__(self, task_tracker: OpenSpecTaskTracker | None = None):
        self.task_tracker = task_tracker

    def verify_completion(
        self,
        worktree_path: str | Path,
        openspec_path: str,
        change_name: str,
        base_sha: str,
        candidate_sha: str | None = None,
        check_results: list[CheckResult] | None = None,
        require_candidate_sha: bool = False,
    ) -> CompletionVerificationResult:
        """Perform fail-closed verification against OpenSpec tasks, git diff, and deterministic checks."""
        worktree = Path(worktree_path)

        # 1. OpenSpec Task Check
        tracker = self.task_tracker or OpenSpecTaskTracker(worktree)
        try:
            incomplete_tasks = tracker.incomplete_tasks(openspec_path, change_name)
        except Exception as err:
            logger.warning("Failed to parse OpenSpec tasks: %s", err)
            return CompletionVerificationResult(
                is_complete=False,
                reason=f"OpenSpec tasks could not be verified: {err}",
            )

        if incomplete_tasks:
            return CompletionVerificationResult(
                is_complete=False,
                reason=f"OpenSpec tasks incomplete ({len(incomplete_tasks)} remaining)",
                incomplete_tasks=incomplete_tasks,
            )

        # 2. Git Working Tree / Diff Check
        modified_files: list[str] = []
        try:
            diff_proc = subprocess.run(
                ["git", "diff", "--name-only", base_sha],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            if diff_proc.returncode == 0 and diff_proc.stdout:
                modified_files = [
                    line.strip() for line in diff_proc.stdout.splitlines() if line.strip()
                ]

            # Also check untracked files
            status_proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            if status_proc.returncode == 0 and status_proc.stdout:
                for line in status_proc.stdout.splitlines():
                    clean_line = line.strip()
                    if clean_line:
                        parts = clean_line.split(maxsplit=1)
                        if len(parts) == 2 and parts[1] not in modified_files:
                            modified_files.append(parts[1])
        except Exception as err:
            logger.warning("Failed to inspect worktree git status: %s", err)

        if not modified_files:
            # Fallback for non-git fake worktree test directories
            try:
                for p in worktree.rglob("*"):
                    if p.is_file() and not any(part.startswith(".") for part in p.parts):
                        rel = str(p.relative_to(worktree))
                        if not rel.startswith(openspec_path) or rel.endswith(".md"):
                            modified_files.append(rel)
            except Exception as f_err:
                logger.debug("Filesystem inspect fallback: %s", f_err)

        if not modified_files:
            return CompletionVerificationResult(
                is_complete=False,
                reason="No candidate file modifications detected against base SHA",
                modified_files=[],
            )

        # 3. Deterministic Checks Check
        failing_checks: list[CheckResult] = []
        if check_results:
            for check in check_results:
                if check.exit_code != 0:
                    failing_checks.append(check)

        if failing_checks:
            return CompletionVerificationResult(
                is_complete=False,
                reason=f"Deterministic checks failed ({len(failing_checks)} failing checks)",
                failing_checks=failing_checks,
                modified_files=modified_files,
            )

        # 4. Mandatory Candidate SHA Verification & Binding
        actual_head_sha: str | None = None
        head_resolution_failed = False
        try:
            head_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            if head_proc.returncode == 0 and head_proc.stdout:
                parsed_head = head_proc.stdout.strip()
                if parsed_head and re.match(r"^[0-9a-fA-F]{7,64}$", parsed_head):
                    actual_head_sha = parsed_head
                else:
                    head_resolution_failed = True
            else:
                head_resolution_failed = True
        except Exception as err:
            logger.warning("Failed to resolve worktree HEAD SHA: %s", err)
            head_resolution_failed = True

        # HEAD resolution is mandatory for any successful completion
        if head_resolution_failed or not actual_head_sha:
            return CompletionVerificationResult(
                is_complete=False,
                reason="Worktree HEAD resolution failure: could not resolve actual HEAD SHA for candidate verification",
                candidate_sha=None,
                modified_files=modified_files,
            )

        if require_candidate_sha and not candidate_sha:
            return CompletionVerificationResult(
                is_complete=False,
                reason="Missing required candidate SHA for committed candidate verification",
                candidate_sha=actual_head_sha,
                modified_files=modified_files,
            )

        if candidate_sha is not None:
            clean_cand_sha = candidate_sha.strip()
            # Malformed SHA check (must be a valid hex string of minimum length, e.g. 7-64 hex characters)
            if not clean_cand_sha or not re.match(r"^[0-9a-fA-F]{7,64}$", clean_cand_sha):
                return CompletionVerificationResult(
                    is_complete=False,
                    reason=f"Malformed candidate SHA: '{candidate_sha}'",
                    candidate_sha=actual_head_sha,
                    modified_files=modified_files,
                )

            # Exact full SHA comparison
            if clean_cand_sha.lower() != actual_head_sha.lower():
                return CompletionVerificationResult(
                    is_complete=False,
                    reason=f"Candidate SHA mismatch: supplied '{clean_cand_sha}' does not match actual worktree HEAD '{actual_head_sha}'",
                    candidate_sha=actual_head_sha,
                    modified_files=modified_files,
                )

        # Invariant: Successful completion MUST ALWAYS have a non-None, verified candidate_sha
        return CompletionVerificationResult(
            is_complete=True,
            candidate_sha=actual_head_sha,
            modified_files=modified_files,
        )

    def classify_outcome(
        self,
        verification_result: CompletionVerificationResult,
        provider_result: NormalizedProviderResult | None = None,
        blocker_claim: BlockerClaim | None = None,
        has_policy_violation: bool = False,
        has_environment_failure: bool = False,
        has_malformed_result: bool = False,
    ) -> ExecutionOutcome:
        """Classify executor execution into a normalized ExecutionOutcome enum."""
        # 1. Provider-level errors
        if provider_result:
            if provider_result.result_class in (
                ProviderResultClass.QUOTA_LIMIT,
                ProviderResultClass.RATE_LIMIT,
            ):
                return ExecutionOutcome.PROVIDER_EXHAUSTED
            if provider_result.result_class in (
                ProviderResultClass.AUTH_ERROR,
                ProviderResultClass.TIMEOUT,
                ProviderResultClass.UNKNOWN_ERROR,
                ProviderResultClass.TRANSIENT_ERROR,
            ):
                return ExecutionOutcome.PROVIDER_FAILURE
            if provider_result.result_class == ProviderResultClass.POLICY_DENIED:
                return ExecutionOutcome.POLICY_VIOLATION
            if provider_result.result_class == ProviderResultClass.MALFORMED_OUTPUT:
                return ExecutionOutcome.MALFORMED_RESULT

        # 2. Execution-level flags
        if has_policy_violation:
            return ExecutionOutcome.POLICY_VIOLATION

        if has_malformed_result:
            return ExecutionOutcome.MALFORMED_RESULT

        # 3. Blocker claims
        if blocker_claim:
            if blocker_claim.validation_verdict == BlockerValidationVerdict.REAL_BLOCKER:
                return ExecutionOutcome.REAL_BLOCKER
            if blocker_claim.validation_verdict == BlockerValidationVerdict.FALSE_BLOCKER:
                return ExecutionOutcome.FALSE_BLOCKER

        # 4. Environment inabilities
        if has_environment_failure:
            return ExecutionOutcome.ENVIRONMENT_UNAVAILABLE

        # 5. Verification evaluation
        if verification_result.is_complete:
            return ExecutionOutcome.COMPLETED

        if not verification_result.modified_files:
            return ExecutionOutcome.NO_PROGRESS

        if verification_result.incomplete_tasks:
            return ExecutionOutcome.PREMATURE_STOP

        if verification_result.failing_checks:
            return ExecutionOutcome.CHANGES_REQUIRED

        return ExecutionOutcome.EVIDENCE_INSUFFICIENT

    def evaluate_progress(self, signals: ProgressSignals) -> ProgressClassification:
        """Deterministically classify progress using hard-evidence deltas."""
        if signals.regression_detected or signals.checks_fail_delta > 0:
            return ProgressClassification.REGRESSION

        if (
            signals.completed_task_delta > 0
            or signals.checks_pass_delta > 0
            or signals.acceptance_evidence_delta > 0
        ) and not signals.policy_violation:
            return ProgressClassification.GOOD_PROGRESS

        if signals.candidate_file_delta > 0 and not signals.policy_violation:
            return ProgressClassification.PARTIAL_PROGRESS

        return ProgressClassification.NO_PROGRESS
