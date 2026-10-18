"""Efficiency Telemetry Service for PostgreSQL metrics persistence and querying.

Tracks and computes:
- attempts_by_provider & duration_by_provider_ms
- productive_attempt_count vs no_progress_attempt_count
- same_sha_retry_count & same_sha_retry_suppressed_count
- corrective_retry_count & reassignments_count
- premium_provider_assignments & premium_provider_reason_codes
- cycle time milestones (time_to_candidate, time_to_checks, time_to_review, time_to_pr)
- self_hosting_percentage across 9 canonical native pipeline phases.
"""

from __future__ import annotations

import logging
from typing import Any

from minime.domain.enums import (
    AttemptProductivityClass,
    ContinuationDecision,
    EventType,
    ExecutionOutcome,
    OrchestrationStage,
    PremiumProviderReasonCode,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    EfficiencyTelemetryView,
    OrchestrationRun,
    ProviderEfficiencyMetrics,
    utc_now,
)
from minime.logging import redact_secrets

logger = logging.getLogger(__name__)


class EfficiencyTelemetryService:
    """Computes, updates, and queries provider efficiency facts and telemetry."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    def record_run_telemetry(self, run: OrchestrationRun) -> ProviderEfficiencyMetrics:
        """Compute durable efficiency telemetry facts and persist to PostgreSQL."""
        job = self.uow.jobs.get_by_id(run.active_job_id) if run.active_job_id else None
        attempts = self.uow.job_attempts.list_by_job(job.job_id) if job else []

        attempts_by_provider: dict[str, int] = {}
        duration_by_provider_ms: dict[str, int] = {}
        productive_count = 0
        no_progress_count = 0
        same_sha_count = 0
        suppressed_count = 0
        corrective_count = 0
        premium_assignments = 0
        premium_reason_codes: list[str] = []

        for att in attempts:
            prov = att.executor_role
            attempts_by_provider[prov] = attempts_by_provider.get(prov, 0) + 1
            duration_by_provider_ms[prov] = duration_by_provider_ms.get(prov, 0) + (
                att.duration_ms or 0
            )

            if (
                att.productivity_class
                in {
                    AttemptProductivityClass.SUBSTANTIVE_PROGRESS,
                    AttemptProductivityClass.VALID_CORRECTIVE_WORK,
                    AttemptProductivityClass.PLATFORM_REPAIR,
                    AttemptProductivityClass.ARCHITECTURE_WORK,
                }
                or att.normalized_outcome == ExecutionOutcome.COMPLETED
            ):
                productive_count += 1
            elif (
                att.productivity_class
                in {
                    AttemptProductivityClass.SAME_SHA_NO_PROGRESS,
                    AttemptProductivityClass.DUPLICATE_RETRY,
                    AttemptProductivityClass.PROVIDER_FAILURE,
                }
                or att.normalized_outcome == ExecutionOutcome.NO_PROGRESS
            ):
                no_progress_count += 1

            if att.is_same_sha_duplicate:
                same_sha_count += 1

            if att.continuation_decision == ContinuationDecision.CORRECT_AND_RETRY:
                corrective_count += 1

            if (
                att.premium_reason_code
                and att.premium_reason_code
                != PremiumProviderReasonCode.PREMIUM_PROVIDER_NOT_REQUIRED
            ):
                premium_assignments += 1
                if att.premium_reason_code.value not in premium_reason_codes:
                    premium_reason_codes.append(att.premium_reason_code.value)

        # Inspect events for suppressed same-SHA retries, exhaustion, and drain transitions
        events = self.uow.events.list_events(change_id=run.change_name)
        exhaustion_events: list[dict[str, Any]] = []
        drain_transitions: list[dict[str, Any]] = []
        reassignment_reasons: list[str] = []

        for evt in events:
            if evt.event_type == EventType.SAME_SHA_RETRY_SUPPRESSED:
                suppressed_count += 1
            elif evt.event_type == EventType.PROVIDER_DRAIN_TRANSITION:
                drain_transitions.append(evt.payload)
            elif evt.event_type == EventType.PRIMARY_CAPACITY_EXHAUSTED:
                exhaustion_events.append(evt.payload)
            elif evt.event_type == EventType.AGENT_REASSIGNED:
                reason = evt.payload.get("reason") or "Continuation governance reassignment"
                if reason not in reassignment_reasons:
                    reassignment_reasons.append(reason)

        # Milestone timings
        time_to_cand: int | None = None
        time_to_checks: int | None = None
        time_to_rev: int | None = None
        time_to_pr: int | None = None
        total_cycle: int | None = None

        stage_events = self.uow.orchestration_stage_events.list_by_run(run.run_id)
        start_time = getattr(run, "started_at", getattr(run, "created_at", utc_now()))
        for se in stage_events:
            if se.to_stage == OrchestrationStage.FREEZING_CANDIDATE and time_to_cand is None:
                time_to_cand = int((se.created_at - start_time).total_seconds() * 1000)
            elif se.to_stage == OrchestrationStage.RUNNING_CHECKS and time_to_checks is None:
                time_to_checks = int((se.created_at - start_time).total_seconds() * 1000)
            elif se.to_stage == OrchestrationStage.COMPLEMENTARY_REVIEW and time_to_rev is None:
                time_to_rev = int((se.created_at - start_time).total_seconds() * 1000)
            elif (
                se.to_stage in {OrchestrationStage.PREPARING_PR, OrchestrationStage.PR_PREPARED}
                and time_to_pr is None
            ):
                time_to_pr = int((se.created_at - start_time).total_seconds() * 1000)

        if getattr(run, "completed_at", None):
            total_cycle = int((run.completed_at - start_time).total_seconds() * 1000)
        elif start_time:
            total_cycle = int((utc_now() - start_time).total_seconds() * 1000)

        # Self-hosting calculation (9 native canonical phases)
        operator_actions = (
            self.uow.operator_actions.list_by_project(run.project_id)
            if hasattr(self.uow, "operator_actions")
            else []
        )
        run_operator_actions = [
            a
            for a in operator_actions
            if a.run_id == run.run_id and a.action_type not in {"CONTINUE", "RESUME"}
        ]
        total_phases = 9
        native_phases = max(0, total_phases - len(run_operator_actions))
        self_hosting_pct = round((native_phases / total_phases) * 100.0, 2)

        existing = self.uow.provider_efficiency.get_by_run_id(run.run_id)
        metrics_id = existing.metrics_id if existing else None

        metrics = ProviderEfficiencyMetrics(
            metrics_id=metrics_id or f"eff-{run.run_id}",
            run_id=run.run_id,
            project_id=run.project_id,
            change_name=run.change_name,
            attempts_by_provider=attempts_by_provider,
            duration_by_provider_ms=duration_by_provider_ms,
            productive_attempt_count=productive_count,
            no_progress_attempt_count=no_progress_count,
            same_sha_retry_count=same_sha_count,
            same_sha_retry_suppressed_count=suppressed_count,
            corrective_retry_count=corrective_count,
            reassignments_count=job.reassignment_count if job else 0,
            reassignment_reason_codes=reassignment_reasons,
            provider_exhaustion_events=exhaustion_events,
            drain_transitions=drain_transitions,
            premium_provider_assignments=premium_assignments,
            premium_provider_reason_codes=premium_reason_codes,
            candidate_generations_count=run.current_generation,
            time_to_candidate_ms=time_to_cand,
            time_to_checks_ms=time_to_checks,
            time_to_review_ms=time_to_rev,
            time_to_pr_ms=time_to_pr,
            total_cycle_time_ms=total_cycle,
            human_gates_count=1 if run.human_gate else 0,
            operator_actions_count=len(run_operator_actions),
            self_hosting_native_phases=native_phases,
            self_hosting_total_phases=total_phases,
            self_hosting_percentage=self_hosting_pct,
            created_at=existing.created_at if existing else utc_now(),
            updated_at=utc_now(),
        )
        self.uow.provider_efficiency.save(metrics)
        self.uow.commit()
        return metrics

    def get_efficiency_view(
        self, project_id: str, change_name: str
    ) -> EfficiencyTelemetryView | None:
        """Query aggregated operational efficiency telemetry for a project/change."""
        metrics = self.uow.provider_efficiency.get_by_project_and_change(project_id, change_name)
        if not metrics:
            return None

        provider_summary: list[dict[str, Any]] = []
        for prov, atts in metrics.attempts_by_provider.items():
            dur_ms = metrics.duration_by_provider_ms.get(prov, 0)
            dur_min = round(dur_ms / 60000.0, 1)
            provider_summary.append(
                {
                    "provider": prov,
                    "attempts": atts,
                    "duration_ms": dur_ms,
                    "duration_min": dur_min,
                }
            )

        return EfficiencyTelemetryView(
            project_id=project_id,
            change_name=change_name,
            run_id=metrics.run_id,
            metrics=metrics,
            provider_summary=provider_summary,
            evaluated_at=utc_now(),
        )

    def get_project_efficiency_summary(self, project_id: str) -> dict[str, Any]:
        """Return aggregate provider-efficiency telemetry for every run in a project."""
        metrics = self.uow.provider_efficiency.list_by_project(project_id, limit=None)

        summary: dict[str, Any] = {
            "total_runs": len(metrics),
            "total_productive_attempts": sum(m.productive_attempt_count for m in metrics),
            "total_no_progress_attempts": sum(m.no_progress_attempt_count for m in metrics),
            "productive_attempt_ratio": 0.0,
            "total_same_sha_suppressed": sum(m.same_sha_retry_suppressed_count for m in metrics),
            "total_corrective_retries": sum(m.corrective_retry_count for m in metrics),
            "total_reassignments": sum(m.reassignments_count for m in metrics),
            "average_self_hosting_percentage": 0.0,
            "provider_breakdown": {},
        }

        total_attempts = (
            summary["total_productive_attempts"] + summary["total_no_progress_attempts"]
        )
        if total_attempts:
            summary["productive_attempt_ratio"] = round(
                summary["total_productive_attempts"] / total_attempts * 100.0, 2
            )
        if metrics:
            summary["average_self_hosting_percentage"] = round(
                sum(m.self_hosting_percentage for m in metrics) / len(metrics), 2
            )

        provider_breakdown: dict[str, dict[str, int]] = {}
        for metric in metrics:
            for provider, attempts in metric.attempts_by_provider.items():
                provider_summary = provider_breakdown.setdefault(
                    provider, {"attempts": 0, "duration_ms": 0}
                )
                provider_summary["attempts"] += attempts
                provider_summary["duration_ms"] += metric.duration_by_provider_ms.get(provider, 0)
        summary["provider_breakdown"] = provider_breakdown
        return summary

    def get_operational_duration_breakdown(self, run_id: str) -> dict[str, Any]:
        """Compute exact duration breakdown, token attribution, and transport stats for an orchestration run."""
        run = (
            self.uow.orchestration_runs.get_by_id(run_id)
            if hasattr(self.uow.orchestration_runs, "get_by_id")
            else None
        )
        if not run:
            return {}

        job = (
            self.uow.jobs.get_by_id(run.active_job_id)
            if run.active_job_id and hasattr(self.uow, "jobs")
            else None
        )
        attempts = (
            self.uow.job_attempts.list_by_job(job.job_id)
            if job and hasattr(self.uow, "job_attempts")
            else []
        )
        stage_events = (
            self.uow.orchestration_stage_events.list_by_run(run_id)
            if hasattr(self.uow, "orchestration_stage_events")
            else []
        )

        stage_durations: dict[str, int] = {}
        for evt in stage_events:
            ev_refs = evt.evidence_references or {}
            duration_ms = ev_refs.get("stage_duration_ms")
            if duration_ms is not None and evt.from_stage:
                stage_durations[evt.from_stage.value] = stage_durations.get(
                    evt.from_stage.value, 0
                ) + int(duration_ms)

        # Categorize by operational component
        admission_duration_ms = stage_durations.get(OrchestrationStage.ADMITTED.value, 0)
        contract_review_duration_ms = stage_durations.get(
            OrchestrationStage.PREPARING_EXECUTION.value, 0
        )

        # Implementer sandbox active compute: sum of attempt duration_ms or stage duration
        attempt_compute_ms = sum((att.duration_ms or 0) for att in attempts)
        implementer_active_compute_duration_ms = (
            attempt_compute_ms
            if attempt_compute_ms > 0
            else stage_durations.get(OrchestrationStage.IMPLEMENTING.value, 0)
        )

        checks_duration_ms = stage_durations.get(OrchestrationStage.RUNNING_CHECKS.value, 0)
        code_review_duration_ms = (
            stage_durations.get(OrchestrationStage.COMPLEMENTARY_REVIEW.value, 0)
            + stage_durations.get(OrchestrationStage.INDEPENDENT_AUDIT.value, 0)
        )
        pr_preparation_duration_ms = (
            stage_durations.get(OrchestrationStage.PREPARING_PR.value, 0)
            + stage_durations.get(OrchestrationStage.PR_PREPARED.value, 0)
        )

        # Diagnostics for transport retries & stalls
        diagnostics = (
            self.uow.evidence_diagnostics.list_by_job(job.job_id)
            if job and hasattr(self.uow, "evidence_diagnostics")
            else []
        )
        total_transport_retries = 0
        total_transport_stall_ms = 0
        for diag in diagnostics:
            ref = diag.evidence_reference or {}
            total_transport_retries += int(ref.get("transport_retry_count") or 0)
            total_transport_stall_ms += int(ref.get("transport_stall_ms") or 0)

        # Total cycle time
        start_time = getattr(run, "started_at", getattr(run, "created_at", None))
        end_time = (
            getattr(run, "completed_at", None)
            or getattr(run, "updated_at", None)
            or utc_now()
        )
        total_duration_ms = 0
        if start_time and end_time:
            total_duration_ms = max(0, int((end_time - start_time).total_seconds() * 1000))

        # Ledger token and cost attribution
        ledger_entries = (
            self.uow.budget_ledger.list_by_project(run.project_id)
            if hasattr(self.uow, "budget_ledger")
            else []
        )
        job_ledger = [
            e
            for e in ledger_entries
            if getattr(e, "job_id", None) == (job.job_id if job else None)
        ]
        total_prompt_tokens = sum((e.prompt_tokens or 0) for e in job_ledger)
        total_completion_tokens = sum((e.completion_tokens or 0) for e in job_ledger)
        total_cost_usd = float(sum((e.amount_usd or 0) for e in job_ledger))

        tokens_by_stage: dict[str, dict[str, Any]] = {}
        for entry in job_ledger:
            stg = entry.stage
            current = tokens_by_stage.setdefault(
                stg, {"prompt_tokens": 0, "completion_tokens": 0, "amount_usd": 0.0}
            )
            current["prompt_tokens"] += entry.prompt_tokens or 0
            current["completion_tokens"] += entry.completion_tokens or 0
            current["amount_usd"] = round(current["amount_usd"] + float(entry.amount_usd or 0), 6)

        accounted_duration = (
            admission_duration_ms
            + contract_review_duration_ms
            + implementer_active_compute_duration_ms
            + checks_duration_ms
            + code_review_duration_ms
            + pr_preparation_duration_ms
        )
        idle_or_waiting_duration_ms = (
            max(0, total_duration_ms - accounted_duration)
            if total_duration_ms > accounted_duration
            else total_transport_stall_ms
        )

        raw_result = {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "change_name": run.change_name,
            "admission_duration_ms": admission_duration_ms,
            "contract_review_duration_ms": contract_review_duration_ms,
            "implementer_active_compute_duration_ms": implementer_active_compute_duration_ms,
            "checks_duration_ms": checks_duration_ms,
            "code_review_duration_ms": code_review_duration_ms,
            "pr_preparation_duration_ms": pr_preparation_duration_ms,
            "idle_or_waiting_duration_ms": idle_or_waiting_duration_ms,
            "transport_retry_count": total_transport_retries,
            "transport_stall_ms": total_transport_stall_ms,
            "total_duration_ms": total_duration_ms,
            "tokens_by_stage": tokens_by_stage,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_cost_usd": round(total_cost_usd, 6),
        }

        def _sanitize(val: Any) -> Any:
            if isinstance(val, str):
                return redact_secrets(val)
            if isinstance(val, dict):
                return {k: _sanitize(v) for k, v in val.items()}
            if isinstance(val, list):
                return [_sanitize(v) for v in val]
            return val

        return _sanitize(raw_result)
