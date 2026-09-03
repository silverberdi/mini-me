"""Deterministic Task Classifier for mini me.

Provides evidence-based classification of tasks and execution attempts into canonical
task classes (e.g. ROUTINE_IMPLEMENTATION, ORDINARY_REMEDIATION, TEST_FIX,
BOOKKEEPING_RECONCILIATION, ARCHITECTURE, UX_VISUAL_QA, PLATFORM_RECOVERY).
Does NOT use opaque LLM prompts for canonical classification decisions.
"""

from __future__ import annotations

import logging
from typing import Any

from minime.domain.enums import ExecutionOutcome, OrchestrationStage, TaskClass
from minime.domain.models import CheckResult, TaskClassificationResult
from minime.services.openspec_tasks import OpenSpecTask

logger = logging.getLogger(__name__)


class TaskClassifier:
    """Deterministic, evidence-based classifier for mini me work and remediation tasks."""

    def classify(
        self,
        *,
        stage: OrchestrationStage | str | None = None,
        outcome: ExecutionOutcome | str | None = None,
        attempt_number: int = 1,
        code_changed: bool = False,
        failing_checks: list[CheckResult] | list[dict[str, Any]] | None = None,
        incomplete_tasks: list[OpenSpecTask] | list[dict[str, Any]] | None = None,
        is_platform_failure: bool = False,
        is_ux_validation: bool = False,
        is_architecture_scope: bool = False,
        extra_context: dict[str, Any] | None = None,
    ) -> TaskClassificationResult:
        """Deterministically evaluate signals and return a structured classification result."""
        signals: dict[str, Any] = {
            "stage": str(stage) if stage else None,
            "outcome": str(outcome) if outcome else None,
            "attempt_number": attempt_number,
            "code_changed": code_changed,
            "failing_checks_count": len(failing_checks or []),
            "incomplete_tasks_count": len(incomplete_tasks or []),
            "is_platform_failure": is_platform_failure,
            "is_ux_validation": is_ux_validation,
            "is_architecture_scope": is_architecture_scope,
        }
        if extra_context:
            signals.update(extra_context)

        # 1. Explicit Platform / Infrastructure Defect
        if is_platform_failure:
            return TaskClassificationResult(
                task_class=TaskClass.PLATFORM_RECOVERY,
                rationale="Platform defect, container failure, git lock collision, or environment outage detected.",
                signals=signals,
            )

        # 2. Explicit UX / Visual QA Task
        if is_ux_validation or (stage and str(stage).upper() in {"PREVIEW_READY", "GUIDED_VALIDATION"}):
            return TaskClassificationResult(
                task_class=TaskClass.UX_VISUAL_QA,
                rationale="Visual preview inspection, containerized UI validation, or interactive scenario QA.",
                signals=signals,
            )

        # 3. Explicit Architecture / Structural Refactoring
        if is_architecture_scope:
            return TaskClassificationResult(
                task_class=TaskClass.ARCHITECTURE,
                rationale="Cross-cutting architectural overhaul, interface redesign, or structural subsystem contract change.",
                signals=signals,
            )

        # 4. Check Failure Classification (Test Fix vs Platform vs Routine Remediation)
        if failing_checks:
            check_names = []
            has_lint_only = True
            has_test_failures = False
            for c in failing_checks:
                name = c.check_name if isinstance(c, CheckResult) else c.get("check_name", c.get("name", ""))
                check_names.append(name.lower())
                if "test" in name.lower() or "pytest" in name.lower():
                    has_test_failures = True
                    has_lint_only = False
                elif "ruff" not in name.lower() and "format" not in name.lower() and "lint" not in name.lower():
                    has_lint_only = False

            if has_test_failures:
                return TaskClassificationResult(
                    task_class=TaskClass.TEST_FIX,
                    rationale=f"Automated test assertions failed ({', '.join(check_names)}); targeted test fix required.",
                    signals=signals,
                )
            if has_lint_only:
                return TaskClassificationResult(
                    task_class=TaskClass.ORDINARY_REMEDIATION,
                    rationale="Formatting or linting check failures detected; routine remediation required.",
                    signals=signals,
                )
            return TaskClassificationResult(
                task_class=TaskClass.ORDINARY_REMEDIATION,
                rationale=f"Checks failed on ({', '.join(check_names)}); routine remediation required.",
                signals=signals,
            )

        # 5. Bookkeeping / Evidence Reconciliation Detection
        # If code is already modified and remaining tasks are only checkboxes/sync/documentation
        if incomplete_tasks is not None and len(incomplete_tasks) > 0:
            all_bookkeeping = True
            for t in incomplete_tasks:
                desc = t.text if isinstance(t, OpenSpecTask) else t.get("text", t.get("description", ""))
                desc_lower = desc.lower()
                is_sync_or_doc = any(
                    kw in desc_lower
                    for kw in [
                        "sync",
                        "checkbox",
                        "tasks.md",
                        "evidence",
                        "record",
                        "verify and archive",
                        "documentation",
                        "manifest",
                    ]
                )
                if not is_sync_or_doc:
                    all_bookkeeping = False
                    break

            if all_bookkeeping and code_changed:
                return TaskClassificationResult(
                    task_class=TaskClass.BOOKKEEPING_RECONCILIATION,
                    rationale="Code implementation is complete and remaining tasks consist exclusively of tasks.md/evidence synchronization.",
                    signals=signals,
                )

        # 6. Stage-Specific Remediation vs Routine Implementation
        normalized_stage = str(stage).upper() if stage else ""
        if normalized_stage in {
            OrchestrationStage.REVIEW_REMEDIATION.value,
            OrchestrationStage.AUDIT_REMEDIATION.value,
        }:
            return TaskClassificationResult(
                task_class=TaskClass.ORDINARY_REMEDIATION,
                rationale="Remediating findings from review or audit gate.",
                signals=signals,
            )

        # 7. Default to Routine Implementation
        return TaskClassificationResult(
            task_class=TaskClass.ROUTINE_IMPLEMENTATION,
            rationale="Standard feature implementation or code task.",
            signals=signals,
        )
