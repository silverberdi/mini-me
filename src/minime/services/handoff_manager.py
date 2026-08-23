"""Handoff management and structured context transfer for mini me."""

from __future__ import annotations

import logging
from typing import Any

from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    BlockerClaim,
    CandidateAuthorship,
    CandidateManifest,
    CheckResult,
    JobHandoff,
)
from minime.services.openspec_tasks import OpenSpecTask

logger = logging.getLogger(__name__)


class HandoffManager:
    """Creates, packages, and consumes structured handoff contexts across executors."""

    def create_handoff(
        self,
        job_id: str,
        from_attempt_id: str,
        from_executor: str,
        to_executor: str,
        worktree_path: str,
        base_sha: str,
        candidate_sha: str,
        completed_tasks: list[OpenSpecTask],
        remaining_tasks: list[OpenSpecTask],
        manifest: CandidateManifest | None = None,
        check_results: list[CheckResult] | None = None,
        blocker_claims: list[BlockerClaim] | None = None,
        authorship_history: list[CandidateAuthorship] | None = None,
        architectural_notes: dict[str, Any] | None = None,
    ) -> JobHandoff:
        """Create a structured, deterministic JobHandoff payload."""
        completed_task_ids = [t.task_id for t in completed_tasks]
        remaining_task_ids = [t.task_id for t in remaining_tasks]

        # Manifest summary
        manifest_summary: dict[str, Any] = {}
        if manifest:
            manifest_summary = {
                "manifest_hash": manifest.manifest_hash,
                "total_files": manifest.total_files_count,
                "tracked_files_count": len(manifest.tracked_files),
                "staged_files_count": len(manifest.staged_files),
                "untracked_files_count": len(manifest.untracked_files),
            }

        # Checks summary
        checks_summary: dict[str, Any] = {}
        if check_results:
            passing = [c.check_name for c in check_results if c.exit_code == 0]
            failing = [c.check_name for c in check_results if c.exit_code != 0]
            checks_summary = {
                "passing_checks": passing,
                "failing_checks": failing,
                "total_checks": len(check_results),
            }

        # Blockers summary
        blockers_summary: dict[str, Any] = {}
        if blocker_claims:
            blockers_summary = {
                "claims": [
                    {
                        "type": c.blocker_type,
                        "verdict": c.validation_verdict.value,
                        "rationale": c.rationale,
                    }
                    for c in blocker_claims
                ]
            }

        # Do-not-redo guidance
        do_not_redo_guidance: list[str] = [
            f"Preserve all working code in the worktree ({worktree_path}). Do NOT discard or revert progress made in earlier attempts.",
        ]
        if completed_task_ids:
            do_not_redo_guidance.append(
                f"The following tasks are already completed and verified: {', '.join(completed_task_ids)}. Do not re-implement them from scratch."
            )
        if check_results:
            passing = [c.check_name for c in check_results if c.exit_code == 0]
            if passing:
                do_not_redo_guidance.append(
                    f"The following checks are currently passing: {', '.join(passing)}. Ensure your modifications do not cause regressions."
                )

        authorships_payload = [a.model_dump(mode="json") for a in (authorship_history or [])]

        return JobHandoff(
            job_id=job_id,
            from_attempt_id=from_attempt_id,
            to_attempt_id=None,
            from_executor=from_executor,
            to_executor=to_executor,
            worktree_path=worktree_path,
            base_sha=base_sha,
            candidate_sha=candidate_sha,
            completed_tasks=completed_task_ids,
            remaining_tasks=remaining_task_ids,
            manifest_summary=manifest_summary,
            checks_summary=checks_summary,
            blockers_summary=blockers_summary,
            architectural_notes=architectural_notes or {},
            do_not_redo_guidance=do_not_redo_guidance,
            authorship_history=authorships_payload,
            is_consumed=False,
        )

    def consume_handoff(
        self,
        handoff_id: str,
        to_attempt_id: str,
        uow: PersistenceUnitOfWork,
    ) -> JobHandoff | None:
        """Mark a handoff payload as consumed by the succeeding attempt."""
        handoff = uow.job_handoffs.get_by_id(handoff_id)
        if not handoff:
            return None
        handoff.to_attempt_id = to_attempt_id
        handoff.is_consumed = True
        uow.job_handoffs.save(handoff)
        return handoff

    def format_handoff_prompt(self, handoff: JobHandoff) -> str:
        """Generate formatted prompt context for the incoming executor."""
        lines = [
            "==================================================",
            "HANDOFF CONTEXT FROM PREVIOUS EXECUTOR",
            "==================================================",
            f"Prior Executor: {handoff.from_executor}",
            f"Worktree Path: {handoff.worktree_path}",
            f"Base SHA: {handoff.base_sha}",
            f"Candidate SHA: {handoff.candidate_sha}",
            "",
            "COMPLETED TASKS (PRESERVE):",
        ]
        if handoff.completed_tasks:
            for t in handoff.completed_tasks:
                lines.append(f"  [x] Task {t}")
        else:
            lines.append("  (None)")

        lines.extend(
            [
                "",
                "REMAINING TASKS (ACTION REQUIRED):",
            ]
        )
        if handoff.remaining_tasks:
            for t in handoff.remaining_tasks:
                lines.append(f"  [ ] Task {t}")
        else:
            lines.append("  (All tasks marked completed; verify and stabilize)")

        lines.extend(
            [
                "",
                "DO NOT REDO GUIDANCE:",
            ]
        )
        for g in handoff.do_not_redo_guidance:
            lines.append(f"- {g}")

        if handoff.checks_summary.get("failing_checks"):
            lines.extend(
                [
                    "",
                    "FAILING CHECKS TO RESOLVE:",
                    f"- {', '.join(handoff.checks_summary['failing_checks'])}",
                ]
            )

        lines.append("==================================================")
        return "\n".join(lines)
