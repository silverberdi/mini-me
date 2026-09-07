"""Autonomous Queue and Work Selection Scheduler Service.

Manages work discovery, deterministic prioritization, roadmap governance,
concurrency limits, admission control, and autonomous candidate execution startup.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from minime.domain.enums import (
    AdmissionDecision,
    AdmissionRefusalCode,
    ChangeStatus,
    HumanGate,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProjectStatus,
    ProviderHealthStatus,
    QueuePriority,
    ReadinessState,
    SchedulerMode,
    WorkItemStatus,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    OrchestrationRun,
    QueueExplainReport,
    SchedulerDecisionRecord,
    SchedulerStatusView,
    WorkQueueItem,
    utc_now,
)
from minime.services.discovery_service import WorkDiscoveryService, extract_roadmap_stage
from minime.services.intake_service import IntakeService
from minime.services.orchestration_service import OrchestrationService
from minime.services.post_merge_service import PostMergeReconciliationService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.readiness_service import ReadinessService

logger = logging.getLogger(__name__)

PRIORITY_BASE_SCORES: dict[QueuePriority, float] = {
    QueuePriority.CRITICAL: 10000.0,
    QueuePriority.HIGH: 5000.0,
    QueuePriority.NORMAL: 1000.0,
    QueuePriority.LOW: 100.0,
}

MAX_AGING_BONUS: float = 2000.0
HOURLY_AGING_RATE: float = 50.0


class SchedulerService:
    """Autonomous work scheduler and queue dispatcher."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        project_root: str | Path = ".",
        discovery_service: WorkDiscoveryService | None = None,
        orchestration_service: OrchestrationService | None = None,
        provider_health_service: ProviderHealthService | None = None,
        readiness_service: ReadinessService | None = None,
        post_merge_service: PostMergeReconciliationService | None = None,
        intake_service: IntakeService | None = None,
        max_global_jobs: int = 1,
        one_active_implementation_per_project: bool = True,
        mode: SchedulerMode = SchedulerMode.RUN,
    ):
        self.uow = uow
        self.project_root = Path(project_root).resolve()
        self.readiness_service = readiness_service or ReadinessService(uow)
        gh_adapter = getattr(self.readiness_service, "github_adapter", None)
        os_adapter = getattr(self.readiness_service, "openspec_adapter", None)
        self.discovery_service = discovery_service or WorkDiscoveryService(
            uow,
            project_root=self.project_root,
            github_adapter=gh_adapter,
            openspec_adapter=os_adapter,
            readiness_service=self.readiness_service,
        )
        self.orchestration_service = orchestration_service or OrchestrationService(
            uow,
            project_root=self.project_root,
            github_adapter=gh_adapter,
            openspec_adapter=os_adapter,
        )
        self.post_merge_service = post_merge_service or PostMergeReconciliationService(
            uow,
            project_root=self.project_root,
            github_adapter=gh_adapter,
        )
        self.intake_service = intake_service or IntakeService(
            uow,
            project_root=self.project_root,
            github_adapter=gh_adapter,
            openspec_adapter=os_adapter,
            readiness_service=self.readiness_service,
        )
        self.provider_health_service = provider_health_service or ProviderHealthService(uow)
        self.max_global_jobs = max_global_jobs
        self.one_active_implementation_per_project = one_active_implementation_per_project
        self.mode = mode

    def compute_priority_score(
        self, item: WorkQueueItem, now: datetime | None = None
    ) -> tuple[float, float, float, float]:
        """Compute deterministic priority score: (base_score, aging_bonus, stage_bonus, total_score)."""
        current_time = now or utc_now()
        base_score = PRIORITY_BASE_SCORES.get(item.priority, 1000.0)

        # Aging bonus (prevents starvation of low-priority items over time)
        age_seconds = max(0.0, (current_time - item.discovered_at).total_seconds())
        age_hours = age_seconds / 3600.0
        aging_bonus = min(MAX_AGING_BONUS, age_hours * HOURLY_AGING_RATE)

        # Stage bonus (earlier roadmap stages get a small deterministic precedence boost)
        stage_num = item.roadmap_stage or extract_roadmap_stage(item.change_name) or 99
        stage_bonus = max(0.0, (100.0 - stage_num) * 10.0)

        total_score = base_score + aging_bonus + stage_bonus
        return base_score, aging_bonus, stage_bonus, total_score

    def rank_candidates(
        self, items: list[WorkQueueItem], now: datetime | None = None
    ) -> list[WorkQueueItem]:
        """Deterministically rank queue items by priority score and tie-breaking rules."""
        current_time = now or utc_now()

        scored_items: list[WorkQueueItem] = []
        for item in items:
            _, _, _, total_score = self.compute_priority_score(item, current_time)
            updated = item.model_copy(update={"priority_score": total_score})
            scored_items.append(updated)

        # Sort order:
        # 1. Total score descending
        # 2. Roadmap stage ascending (earlier stages first)
        # 3. Discovered timestamp ascending (earlier items first)
        # 4. GitHub issue number ascending
        scored_items.sort(
            key=lambda i: (
                -i.priority_score,
                i.roadmap_stage if i.roadmap_stage is not None else 9999,
                i.discovered_at,
                i.github_issue_number if i.github_issue_number is not None else 999999,
            )
        )
        return scored_items

    def explain_item_priority(self, project_id: str, change_name: str) -> QueueExplainReport:
        """Provide detailed explainability report for an item's queue ranking and blockers."""
        item = self.uow.work_queue.get_by_project_and_change(project_id, change_name)
        if not item:
            raise ValueError(
                f"Work queue item not found for project '{project_id}' and change '{change_name}'."
            )

        all_items = self.uow.work_queue.list_all(project_id)
        ranked = self.rank_candidates(all_items)

        position = None
        for idx, r in enumerate(ranked, start=1):
            if r.change_name == change_name and r.project_id == project_id:
                position = idx
                break

        base_score, aging_bonus, stage_bonus, total_score = self.compute_priority_score(item)

        decision, refusal_code, reason_summary, _ = self.evaluate_admission(project_id, change_name)

        blockers = list(item.unmet_readiness_reasons)
        if refusal_code and refusal_code != AdmissionRefusalCode.NOT_READY:
            blockers.append(f"Admission Blocker: {refusal_code.value} - {reason_summary}")

        rationale = (
            f"Ranked #{position}: Base score {base_score:.0f} ({item.priority.value}) + "
            f"Aging bonus {aging_bonus:.1f} + Stage bonus {stage_bonus:.1f} = {total_score:.1f}. "
            f"Status: {decision.value}"
            + (f" ({refusal_code.value}: {reason_summary})" if refusal_code else "")
        )

        return QueueExplainReport(
            project_id=project_id,
            change_name=change_name,
            github_issue_number=item.github_issue_number,
            readiness_state=item.readiness_state,
            admission_eligible=item.admission_eligible and decision == AdmissionDecision.ADMITTED,
            priority=item.priority,
            base_score=base_score,
            aging_bonus=aging_bonus,
            roadmap_precedence_penalty=0.0,
            total_score=total_score,
            queue_position=position,
            blockers=blockers,
            refusal_code=refusal_code,
            selection_rationale=rationale,
            evaluated_at=utc_now(),
        )

    def evaluate_admission(
        self, project_id: str, change_name: str
    ) -> tuple[AdmissionDecision, AdmissionRefusalCode | None, str, str | None]:
        """Evaluate full admission criteria and determine eligibility, refusal code, and implementer."""
        # 1. Registered project check
        project = self.uow.projects.get_by_id(project_id)
        if not project or project.status != ProjectStatus.ACTIVE:
            return (
                AdmissionDecision.REFUSED,
                AdmissionRefusalCode.INVALID_BINDING,
                f"Project '{project_id}' is not active or registered.",
                None,
            )

        # 2. Durable ProjectBinding check
        binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)
        if not binding or not binding.is_valid or not binding.github_issue_number:
            return (
                AdmissionDecision.REFUSED,
                AdmissionRefusalCode.INVALID_BINDING,
                f"Project binding for change '{change_name}' is invalid or missing issue number.",
                None,
            )

        # 3. Definition of Ready (DoR) check
        readiness = self.readiness_service.evaluate_change_readiness(
            project_id=project_id,
            change_name=change_name,
            project_root=str(self.project_root),
            github_repo=project.repository,
            github_issue=binding.github_issue_number,
        )
        if not readiness.is_ready or readiness.status != ReadinessState.READY:
            return (
                AdmissionDecision.REFUSED,
                AdmissionRefusalCode.NOT_READY,
                f"Definition of Ready unmet: {'; '.join(readiness.unmet_reasons)}",
                None,
            )

        # 4. Roadmap governance: check for incomplete predecessor roadmap stages
        stage_num = extract_roadmap_stage(change_name)
        if stage_num is not None:
            all_changes = self.uow.changes.list_by_project(project_id)
            for other_change in all_changes:
                if other_change.name == change_name:
                    continue
                other_stage = extract_roadmap_stage(other_change.name)
                if other_stage is not None and other_stage < stage_num:
                    # If an earlier roadmap stage is not DONE/archived, block admission
                    if other_change.status not in (ChangeStatus.DONE, ChangeStatus.CANCELLED):
                        return (
                            AdmissionDecision.REFUSED,
                            AdmissionRefusalCode.ROADMAP_PREDECESSOR_INCOMPLETE,
                            f"Roadmap predecessor stage {other_stage:03d} ('{other_change.name}') is incomplete.",
                            None,
                        )

        # 5. Dependency check
        queue_item = self.uow.work_queue.get_by_project_and_change(project_id, change_name)
        if queue_item and queue_item.dependencies:
            for dep_name in queue_item.dependencies:
                dep_change = self.uow.changes.get_by_name(project_id, dep_name)
                dep_backlog = self.uow.backlog_items.get_by_openspec_change_name(
                    project_id, dep_name
                )
                is_complete = False
                if dep_change and dep_change.status in (
                    ChangeStatus.DONE,
                    ChangeStatus.CANCELLED,
                ):
                    is_complete = True
                elif dep_backlog and dep_backlog.status in (
                    WorkItemStatus.COMPLETED,
                    WorkItemStatus.CANCELLED,
                ):
                    is_complete = True

                if not is_complete:
                    return (
                        AdmissionDecision.REFUSED,
                        AdmissionRefusalCode.DEPENDENCY_BLOCKED,
                        f"Declared dependency '{dep_name}' is not complete.",
                        None,
                    )

        # 6. Scheduler mode check (RUN / DRAIN / WAIT)
        if self.mode == SchedulerMode.DRAIN:
            return (
                AdmissionDecision.REFUSED,
                AdmissionRefusalCode.PROVIDER_DRAIN,
                "Scheduler is in DRAIN mode: no new changes may be admitted.",
                None,
            )
        if self.mode == SchedulerMode.WAIT:
            return (
                AdmissionDecision.REFUSED,
                AdmissionRefusalCode.PROVIDER_WAIT,
                "Scheduler is in WAIT mode: all admissions suspended.",
                None,
            )

        # 7. Provider health check for primary implementer
        selected_implementer = project.implementer or "codex"
        health = self.provider_health_service.get_health(selected_implementer)
        if health.status not in (ProviderHealthStatus.AVAILABLE, ProviderHealthStatus.DEGRADED):
            return (
                AdmissionDecision.REFUSED,
                AdmissionRefusalCode.PROVIDER_UNAVAILABLE,
                f"Configured implementer '{selected_implementer}' is {health.status.value}.",
                None,
            )

        # 8. Project policy checks
        if not getattr(project, "auto_admit", True):
            return (
                AdmissionDecision.REFUSED,
                AdmissionRefusalCode.MANUAL_ADMISSION_POLICY,
                f"Project '{project_id}' policy requires manual admission ('auto_admit' is disabled).",
                None,
            )

        # 9. Concurrency checks
        active_runs = self.uow.orchestration_runs.list_runs(is_active=True)

        # Same-change exclusivity check
        for active_run in active_runs:
            if active_run.project_id == project_id and active_run.change_name == change_name:
                return (
                    AdmissionDecision.REFUSED,
                    AdmissionRefusalCode.CHANGE_ALREADY_ACTIVE,
                    f"Active orchestration run '{active_run.run_id}' already executing change '{change_name}'.",
                    None,
                )

        # Per-project concurrency check
        max_project_jobs = getattr(project, "max_concurrent_jobs", 1)
        project_active = [r for r in active_runs if r.project_id == project_id]
        if len(project_active) >= max_project_jobs:
            return (
                AdmissionDecision.REFUSED,
                AdmissionRefusalCode.PROJECT_CONCURRENCY_LIMIT,
                f"Project '{project_id}' concurrency limit reached ({len(project_active)}/{max_project_jobs} active runs).",
                None,
            )

        # Global concurrency check
        if len(active_runs) >= self.max_global_jobs:
            return (
                AdmissionDecision.REFUSED,
                AdmissionRefusalCode.GLOBAL_CONCURRENCY_LIMIT,
                f"Global concurrency limit reached ({len(active_runs)}/{self.max_global_jobs} active runs).",
                None,
            )

        # All criteria satisfied
        return (
            AdmissionDecision.ADMITTED,
            None,
            f"Work item '{change_name}' is READY and admitted for execution.",
            selected_implementer,
        )

    def admit_work_item(
        self, project_id: str, change_name: str, drive_admitted: bool = False
    ) -> tuple[AdmissionDecision, SchedulerDecisionRecord, OrchestrationRun | None]:
        """Atomically evaluate admission and start native candidate execution if eligible."""
        decision, refusal_code, reason_summary, selected_implementer = self.evaluate_admission(
            project_id, change_name
        )

        item = self.uow.work_queue.get_by_project_and_change(project_id, change_name)
        _, _, _, priority_score = (
            self.compute_priority_score(item) if item else (0.0, 0.0, 0.0, 0.0)
        )
        issue_number = item.github_issue_number if item else None

        active_runs = self.uow.orchestration_runs.list_runs(is_active=True)
        concurrency_snapshot = {
            "global_active": len(active_runs),
            "max_global_jobs": self.max_global_jobs,
            "project_active": len([r for r in active_runs if r.project_id == project_id]),
        }
        capacity_snapshot = {
            "mode": self.mode.value,
            "implementer": selected_implementer,
        }

        if decision == AdmissionDecision.ADMITTED:
            # Native admission via OrchestrationService
            admission_result = self.orchestration_service.admit_change(
                project_id=project_id,
                change_name=change_name,
                project_root=self.project_root,
            )
            if not admission_result.admitted or not admission_result.run:
                # Admission failed at orchestration layer
                refusal_code_str = (
                    admission_result.refusal_details.get("code")
                    if admission_result.refusal_details
                    else "EVALUATION_ERROR"
                )
                try:
                    refusal = AdmissionRefusalCode(refusal_code_str)
                except ValueError:
                    refusal = AdmissionRefusalCode.EVALUATION_ERROR

                decision_record = SchedulerDecisionRecord(
                    project_id=project_id,
                    change_name=change_name,
                    github_issue_number=issue_number,
                    decision=AdmissionDecision.REFUSED,
                    reason_code=refusal,
                    reason_summary=admission_result.refusal_reason
                    or "Orchestration admission failed",
                    priority_score=priority_score,
                    selected_implementer=selected_implementer,
                    concurrency_snapshot=concurrency_snapshot,
                    capacity_snapshot=capacity_snapshot,
                    evaluated_at=utc_now(),
                )
                self.uow.scheduler_decisions.save(decision_record)
                self.uow.commit()
                return AdmissionDecision.REFUSED, decision_record, None

            run = admission_result.run

            decision_record = SchedulerDecisionRecord(
                project_id=project_id,
                change_name=change_name,
                github_issue_number=issue_number,
                decision=AdmissionDecision.ADMITTED,
                reason_code=None,
                reason_summary=reason_summary,
                priority_score=priority_score,
                selected_implementer=selected_implementer,
                concurrency_snapshot=concurrency_snapshot,
                capacity_snapshot=capacity_snapshot,
                run_id=run.run_id,
                evaluated_at=utc_now(),
            )
            self.uow.scheduler_decisions.save(decision_record)

            # Update queue item
            if item:
                updated_item = item.model_copy(
                    update={
                        "admission_eligible": False,
                        "blocked_reason": f"Admitted in active run '{run.run_id}'",
                        "last_evaluated_at": utc_now(),
                    }
                )
                self.uow.work_queue.save(updated_item)

            # Update BacklogItem if present
            backlog_item = self.uow.backlog_items.get_by_openspec_change_name(
                project_id, change_name
            )
            if backlog_item:
                updated_backlog = backlog_item.model_copy(
                    update={
                        "status": WorkItemStatus.RUNNING,
                        "run_id": run.run_id,
                        "updated_at": utc_now(),
                    }
                )
                self.uow.backlog_items.save(updated_backlog)

            self.uow.commit()

            if drive_admitted:
                run = self.orchestration_service.drive_coordinator(
                    run.run_id, project_root=self.project_root
                )

            return AdmissionDecision.ADMITTED, decision_record, run

        else:
            decision_record = SchedulerDecisionRecord(
                project_id=project_id,
                change_name=change_name,
                github_issue_number=issue_number,
                decision=AdmissionDecision.REFUSED,
                reason_code=refusal_code,
                reason_summary=reason_summary,
                priority_score=priority_score,
                selected_implementer=selected_implementer,
                concurrency_snapshot=concurrency_snapshot,
                capacity_snapshot=capacity_snapshot,
                evaluated_at=utc_now(),
            )
            self.uow.scheduler_decisions.save(decision_record)

            if item:
                updated_item = item.model_copy(
                    update={
                        "blocked_reason": f"{refusal_code.value if refusal_code else 'BLOCKED'}: {reason_summary}",
                        "last_evaluated_at": utc_now(),
                    }
                )
                self.uow.work_queue.save(updated_item)

            self.uow.commit()
            return AdmissionDecision.REFUSED, decision_record, None

    def reconcile_waiting_runs(
        self,
        project_id: str | None = None,
        drive_resumed: bool = False,
        timeout_hours: float = 2.0,
    ) -> list[str]:
        """Re-evaluate active orchestration runs waiting for capacity or external environment.

        Automatically resumes runs when capacity/environment becomes available,
        or transitions to NEEDS_HUMAN when the bounded waiting timeout is exceeded.
        Does not consume retry budget merely for waiting.
        """
        resumed_run_ids: list[str] = []
        now = utc_now()

        all_runs = self.uow.orchestration_runs.list_runs(project_id=project_id, is_active=True)
        waiting_runs = [
            r
            for r in all_runs
            if r.stop_outcome
            in {
                OrchestrationStopOutcome.WAITING_CAPACITY,
                OrchestrationStopOutcome.WAITING_EXTERNAL,
            }
            and (project_id is None or r.project_id == project_id)
        ]

        for run in waiting_runs:
            # 1. Determine waiting_since
            waiting_since = None
            if run.stop_details and "waiting_since" in run.stop_details:
                try:
                    val = run.stop_details["waiting_since"]
                    if isinstance(val, str):
                        waiting_since = datetime.fromisoformat(val)
                    elif isinstance(val, datetime):
                        waiting_since = val
                except Exception:
                    pass
            if not waiting_since:
                waiting_since = run.updated_at or run.created_at or now

            # 2. Check bounded timeout
            elapsed_seconds = max(0.0, (now - waiting_since).total_seconds())
            if elapsed_seconds > (timeout_hours * 3600.0):
                logger.warning(
                    "Waiting capacity timeout (%.1fh) exceeded for run '%s' (%s). Escalating to NEEDS_HUMAN.",
                    timeout_hours,
                    run.run_id,
                    run.change_name,
                )
                run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
                run.human_gate = HumanGate.NEEDS_HUMAN
                run.is_active = False
                run.stop_reason = (
                    f"Waiting capacity timeout exceeded ({elapsed_seconds / 3600.0:.1f}h). "
                    f"Operator intervention required."
                )
                details = dict(run.stop_details or {})
                details["code"] = "WAITING_CAPACITY_TIMEOUT"
                details["timed_out_at"] = now.isoformat()
                run.stop_details = details
                run.updated_at = now
                self.uow.orchestration_runs.save(run)

                if run.active_job_id:
                    job = self.uow.jobs.get_by_id(run.active_job_id)
                    if job and job.status in {
                        JobStatus.WAITING_CAPACITY,
                        JobStatus.RECOVERY_BLOCKED,
                    }:
                        job.status = JobStatus.NEEDS_HUMAN
                        job.escalation_reason = run.stop_reason
                        self.uow.jobs.save(job)
                self.uow.commit()
                continue

            # 3. Check capacity restoration
            if self.mode == SchedulerMode.WAIT:
                logger.debug(
                    "Scheduler in WAIT mode: skipping capacity wake-up for run '%s'.",
                    run.run_id,
                )
                continue

            project = self.uow.projects.get_by_id(run.project_id)
            if not project:
                continue

            # Determine provider being awaited
            provider = (
                (run.stop_details.get("provider") if run.stop_details else None)
                or (
                    self.uow.jobs.get_by_id(run.active_job_id).waiting_provider
                    if run.active_job_id
                    else None
                )
                or project.implementer
                or "codex"
            )

            # Reset timestamps are estimates, not evidence of actual recovery.
            # Only a verified provider probe/operation restoring health to AVAILABLE may resume waiting work.
            health = self.provider_health_service.get_health(provider)
            is_available = health.status in (
                ProviderHealthStatus.AVAILABLE,
                ProviderHealthStatus.DEGRADED,
            )

            if is_available:
                logger.info(
                    "Capacity restored for provider '%s'; auto-resuming waiting run '%s' (%s).",
                    provider,
                    run.run_id,
                    run.change_name,
                )
                try:
                    self.orchestration_service.resume(
                        run.run_id,
                        project_root=self.project_root,
                    )
                    resumed_run_ids.append(run.run_id)
                except Exception as exc:
                    logger.error(
                        "Error auto-resuming waiting run '%s': %s",
                        run.run_id,
                        exc,
                        exc_info=True,
                    )

        return resumed_run_ids

    def tick(
        self, project_id: str | None = None, drive_admitted: bool = False
    ) -> list[SchedulerDecisionRecord]:
        """Execute one complete scheduler evaluation and admission cycle."""
        # 0.0 Proactively probe unavailable providers to detect recovery without creating Runs/Jobs
        try:
            import asyncio
            try:
                asyncio.get_running_loop()
                # If running loop exists, run probe in background task or skip blocking
            except RuntimeError:
                asyncio.run(self.provider_health_service.probe_unavailable_providers())
        except Exception as exc:
            logger.debug(f"Background provider probing during tick encountered error: {exc}")

        # 0. Check and reconcile any merged runs waiting at READY_FOR_HUMAN_MERGE or PR_PREPARED
        all_runs_pre = self.uow.orchestration_runs.list_runs(project_id=project_id)
        for r in all_runs_pre:
            if (
                (
                    r.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
                    or r.current_stage
                    in {OrchestrationStage.PR_PREPARED, OrchestrationStage.POST_MERGE_RECONCILING}
                )
                and r.current_stage != OrchestrationStage.COMPLETED
                and (project_id is None or r.project_id == project_id)
            ):
                try:
                    res = self.post_merge_service.reconcile_post_merge(
                        project_id=r.project_id,
                        change_name=r.change_name,
                        run_id=r.run_id,
                    )
                    if res.success and not res.already_closed:
                        logger.info(
                            "Autonomously reconciled post-merge for run '%s' (%s).",
                            r.run_id,
                            r.change_name,
                        )
                except Exception as exc:
                    logger.warning("Post-merge check failed for run '%s': %s", r.run_id, exc)

        # 0.1 Check and re-evaluate runs waiting for capacity or external environment
        self.reconcile_waiting_runs(project_id=project_id, drive_resumed=drive_admitted)

        # 0.2 Autonomous intake sweep for unprepared backlog items when auto_prepare is enabled
        try:
            self.intake_service.sweep_unprepared_backlog_items(project_id=project_id)
        except Exception as exc:
            logger.warning(f"Autonomous intake sweep error during scheduler tick: {exc}")

        # 1. Discover work items
        try:
            self.discovery_service.discover_work(project_id)
        except Exception as exc:
            logger.warning(f"Work discovery error during scheduler tick: {exc}")

        # 2. Retrieve all queue items
        items = self.uow.work_queue.list_all(project_id)

        # 3. Rank candidates
        ranked_candidates = self.rank_candidates(items)

        # 4. Evaluate admission for candidates up to available concurrency
        decision_records: list[SchedulerDecisionRecord] = []
        active_runs_count = len(self.uow.orchestration_runs.list_runs(is_active=True))
        available_slots = max(0, self.max_global_jobs - active_runs_count)

        for candidate in ranked_candidates:
            try:
                decision, refusal, summary, impl = self.evaluate_admission(
                    candidate.project_id, candidate.change_name
                )
                if decision == AdmissionDecision.ADMITTED and available_slots > 0:
                    dec, record, run = self.admit_work_item(
                        candidate.project_id, candidate.change_name, drive_admitted=drive_admitted
                    )
                    decision_records.append(record)
                    if dec == AdmissionDecision.ADMITTED:
                        available_slots -= 1
                else:
                    # Refused or concurrency exhausted
                    if decision == AdmissionDecision.ADMITTED and available_slots <= 0:
                        refusal = AdmissionRefusalCode.GLOBAL_CONCURRENCY_LIMIT
                        summary = f"Global concurrency limit reached ({self.max_global_jobs} active runs)."

                    record = SchedulerDecisionRecord(
                        project_id=candidate.project_id,
                        change_name=candidate.change_name,
                        github_issue_number=candidate.github_issue_number,
                        decision=AdmissionDecision.REFUSED,
                        reason_code=refusal,
                        reason_summary=summary,
                        priority_score=candidate.priority_score,
                        selected_implementer=impl,
                        concurrency_snapshot={
                            "global_active": active_runs_count,
                            "max_global_jobs": self.max_global_jobs,
                        },
                        capacity_snapshot={"mode": self.mode.value},
                        evaluated_at=utc_now(),
                    )
                    self.uow.scheduler_decisions.save(record)
                    decision_records.append(record)
            except Exception as exc:
                logger.error(
                    f"Error evaluating candidate '{candidate.change_name}': {exc}",
                    exc_info=True,
                )
                record = SchedulerDecisionRecord(
                    project_id=candidate.project_id,
                    change_name=candidate.change_name,
                    github_issue_number=candidate.github_issue_number,
                    decision=AdmissionDecision.REFUSED,
                    reason_code=AdmissionRefusalCode.EVALUATION_ERROR,
                    reason_summary=f"Evaluation error: {exc}",
                    priority_score=candidate.priority_score,
                    evaluated_at=utc_now(),
                )
                self.uow.scheduler_decisions.save(record)
                decision_records.append(record)

        self.uow.commit()
        return decision_records

    def get_status(self, project_id: str | None = None) -> SchedulerStatusView:
        """Get operational status view of the autonomous queue and scheduler."""
        items = self.uow.work_queue.list_all(project_id)
        ranked = self.rank_candidates(items)

        ready_count = len([i for i in items if i.admission_eligible])
        blocked_count = len(items) - ready_count
        active_runs = self.uow.orchestration_runs.list_runs(is_active=True)

        next_cand = None
        for r in ranked:
            if r.admission_eligible:
                next_cand = r
                break

        recent = self.uow.scheduler_decisions.list_recent(project_id, limit=20)

        health_dict = {}
        for h in self.uow.provider_health.list_all():
            health_dict[h.provider] = h.status.value

        return SchedulerStatusView(
            mode=self.mode,
            queue_depth=len(items),
            ready_count=ready_count,
            blocked_count=blocked_count,
            active_runs_count=len(active_runs),
            max_global_jobs=self.max_global_jobs,
            next_candidate=next_cand,
            recent_decisions=recent,
            provider_health=health_dict,
            evaluated_at=utc_now(),
        )
