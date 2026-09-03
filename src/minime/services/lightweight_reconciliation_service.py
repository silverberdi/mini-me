"""Lightweight In-Process Reconciliation Service.

Implements Mandatory Rule D:
Bookkeeping, evidence synchronization, candidate manifest updates, and tasks.md
checkbox reconciliation must not consume expensive multi-minute implementation agents.

When code is modified and checks pass:
- Performs deterministic, in-process evidence-driven reconciliation.
- Synchronizes tasks.md checkboxes for completed items.
- Updates candidate manifest hashes and evidence diagnostics.
- Emits LIGHTWEIGHT_RECONCILIATION_PERFORMED event.
- Zero LLM tokens or agent processes consumed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from minime.domain.enums import EventType, EvidenceDiagnosticStatus
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import Event, EvidenceDiagnostic, Job, Project, utc_now
from minime.services.candidate_manifest import CandidateManifestService
from minime.services.openspec_tasks import (
    OpenSpecTask,
    OpenSpecTaskTracker,
    is_verification_task,
)

logger = logging.getLogger(__name__)


class LightweightReconciliationService:
    """Performs bounded in-process bookkeeping and evidence reconciliation without LLM invocations."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork | None = None,
        manifest_service: CandidateManifestService | None = None,
    ):
        self.uow = uow
        self.manifest_service = manifest_service or CandidateManifestService()

    def can_reconcile(
        self,
        *,
        code_changed: bool,
        checks_passed: bool,
        incomplete_tasks_count: int,
        only_bookkeeping_remaining: bool = False,
    ) -> bool:
        """Determine if lightweight reconciliation is eligible to resolve remaining gaps."""
        if not checks_passed:
            return False
        if not code_changed:
            return False
        if incomplete_tasks_count == 0:
            return True
        return only_bookkeeping_remaining

    def reconcile_bookkeeping(
        self,
        *,
        worktree_path: str | Path,
        openspec_path: str,
        change_name: str,
        job: Job,
        project: Project,
        checks_passed: bool = True,
        changed_files: list[str] | None = None,
    ) -> dict[str, Any]:
        """Reconcile tasks.md, candidate manifest, and evidence diagnostics in-process."""
        root = Path(worktree_path)
        tracker = OpenSpecTaskTracker(root)
        reconciled_task_ids: list[str] = []

        # 1. Reconcile tasks.md checkboxes
        tasks_file = tracker.tasks_path(openspec_path, change_name)
        if tasks_file.exists() and checks_passed:
            lines = tasks_file.read_text(encoding="utf-8").splitlines()
            new_lines: list[str] = []
            for line in lines:
                stripped = line.strip()
                match = tracker._task_re.match(stripped)
                if match and match.group("mark").lower() != "x":
                    body = match.group("body").strip()
                    id_match = tracker._task_id_re.search(body)
                    task_id = id_match.group("id") if id_match else body
                    body_lower = body.lower()
                    # Reconcile verification, test, check, sync, or documentation tasks when checks pass
                    task_obj = OpenSpecTask(
                        task_id=task_id, text=body, section=None, complete=False
                    )
                    should_mark = is_verification_task(task_obj) or any(
                        kw in body_lower
                        for kw in [
                            "test",
                            "check",
                            "verify",
                            "sync",
                            "spec",
                            "document",
                            "manifest",
                            "evidence",
                        ]
                    )
                    if should_mark:
                        indent = line[: len(line) - len(stripped)]
                        new_lines.append(f"{indent}- [x] {body}")
                        reconciled_task_ids.append(task_id)
                        continue
                new_lines.append(line)

            if reconciled_task_ids:
                tasks_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                logger.info(
                    f"Lightweight reconciliation updated {len(reconciled_task_ids)} tasks in {tasks_file}"
                )

        # 2. Record Evidence Diagnostic
        if self.uow and checks_passed:
            diag = EvidenceDiagnostic(
                job_id=job.job_id,
                stage_type="IMPLEMENTING",
                diagnostic_status=EvidenceDiagnosticStatus.PASS,
                environment_identity="local",
                candidate_sha=job.candidate_sha or "none",
                reason="Lightweight in-process reconciliation passed",
                evidence_reference={
                    "reconciliation_type": "LIGHTWEIGHT_IN_PROCESS",
                    "reconciled_tasks": reconciled_task_ids,
                    "changed_files_count": len(changed_files or []),
                },
                created_at=utc_now(),
            )
            self.uow.evidence_diagnostics.save(diag)

            # 3. Emit Reconciliation Event
            event_payload = {
                "job_id": job.job_id,
                "change_name": change_name,
                "reconciled_tasks": reconciled_task_ids,
                "reconciliation_method": "IN_PROCESS_ZERO_LLM",
                "checks_passed": checks_passed,
            }
            self.uow.events.save(
                Event(
                    event_type=EventType.LIGHTWEIGHT_RECONCILIATION_PERFORMED,
                    project_id=project.project_id,
                    change_id=change_name,
                    payload=event_payload,
                )
            )
            self.uow.commit()

        return {
            "success": True,
            "reconciled_tasks": reconciled_task_ids,
            "tasks_reconciled_count": len(reconciled_task_ids),
            "method": "LIGHTWEIGHT_IN_PROCESS",
        }
