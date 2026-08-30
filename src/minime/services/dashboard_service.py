"""Operations dashboard read model and query service for mini me."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from minime.domain.enums import (
    AuditRiskLevel,
    AuditStatus,
    ChangeStatus,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ReadinessState,
    ReviewVerdict,
    SchedulerMode,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import Change, Job, OrchestrationRun
from minime.logging import redact_secrets
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
from minime.services.provider_health_service import ProviderHealthService

logger = logging.getLogger(__name__)


def _short_sha(sha: str | None) -> str | None:
    if not sha:
        return None
    return sha[:8] if len(sha) >= 8 else sha


def _format_dt(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _sanitize_obj(val: Any) -> Any:
    """Recursively sanitize nested strings, dicts, and lists against secrets."""
    if isinstance(val, str):
        return redact_secrets(val)
    elif isinstance(val, dict):
        return {k: _sanitize_obj(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_sanitize_obj(item) for item in val]
    return val


class ProviderHealthDTO(BaseModel):
    provider_id: str
    status: str
    message: str | None = None
    last_probe_at: str | None = None


class SystemStatusDTO(BaseModel):
    healthy: bool = True
    database_engine: str = "PostgreSQL"
    database_healthy: bool = True
    database_message: str = "Connected"
    scheduler_mode: str = SchedulerMode.RUN.value
    queue_depth: int = 0
    github_app_health: str = "HEALTHY"
    active_runs_count: int = 0
    total_changes_count: int = 0
    attention_runs_count: int = 0
    providers: list[ProviderHealthDTO] = Field(default_factory=list)


class AttentionItemDTO(BaseModel):
    project_id: str
    change_name: str
    run_id: str
    job_id: str | None = None
    stage: str
    stop_outcome: str | None = None
    human_gate: str | None = None
    reason: str
    remediation_guidance: str | None = None
    stop_code: str | None = None
    provider: str | None = None
    can_retry: bool = False
    can_reassign: bool = False
    can_remediate: bool = False
    updated_at: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ActiveExecutionDTO(BaseModel):
    project_id: str
    change_name: str
    run_id: str
    job_id: str | None = None
    stage: str
    current_executor: str | None = None
    generation: int = 1
    candidate_sha: str | None = None
    candidate_sha_short: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    latest_progress: str | None = None


class RecentCompletionDTO(BaseModel):
    project_id: str
    change_name: str
    run_id: str
    candidate_sha: str | None = None
    candidate_sha_short: str | None = None
    generation: int = 1
    pr_number: int | None = None
    pr_url: str | None = None
    review_verdict: str | None = None
    audit_risk: str | None = None
    completed_at: str | None = None


class ChangeSummaryDTO(BaseModel):
    project_id: str
    change_name: str
    status: str  # DISCOVERED, NOT_READY, READY, RUNNING, WAITING, NEEDS_HUMAN, COMPLETED, FAILED
    schema_name: str = "spec-driven"
    current_run_id: str | None = None
    active_job_id: str | None = None
    current_stage: str | None = None
    stop_outcome: str | None = None
    human_gate: str | None = None
    current_executor: str | None = None
    generation: int | None = None
    candidate_sha: str | None = None
    candidate_sha_short: str | None = None
    github_issue_number: int | None = None
    github_pr_number: int | None = None
    updated_at: str | None = None


class PipelinePhaseDTO(BaseModel):
    name: str  # readiness, implementation, checks, review, audit, pr_merge
    display_name: str
    status: str  # not_started, running, passed, failed, blocked, waiting
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class CandidateAuthorityDTO(BaseModel):
    generation: int
    candidate_sha: str
    candidate_sha_short: str
    base_sha: str
    base_sha_short: str
    manifest_hash: str | None = None
    is_frozen: bool = False
    is_superseded: bool = False
    changed_files: list[str] = Field(default_factory=list)
    created_at: str | None = None


class CheckResultItemDTO(BaseModel):
    check_name: str
    command: str
    status: str  # PASS, FAIL, SKIPPED
    exit_code: int | None = None
    duration_ms: int | None = None
    candidate_sha: str | None = None
    diagnostic_snippet: str | None = None


class ReviewSummaryDTO(BaseModel):
    review_id: str | None = None
    reviewer_role: str | None = None
    model: str | None = None
    status: str = "not_started"  # not_started, running, completed, failed
    verdict: str | None = None  # READY_TO_MERGE, CHANGES_REQUIRED
    candidate_sha: str | None = None
    is_stale_to_current_candidate: bool = False
    is_mixed_authorship: bool = False
    material_findings_count: int = 0
    summary: str | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list)


class AuditSummaryDTO(BaseModel):
    audit_id: str | None = None
    provider: str | None = None
    model: str | None = None
    status: str = "not_started"  # not_started, running, completed, failed, blocked
    risk: str | None = None  # low, medium, high, critical
    candidate_sha: str | None = None
    is_stale_to_current_candidate: bool = False
    material_findings_count: int = 0
    summary: str | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list)


class GitHubPRSummaryDTO(BaseModel):
    issue_number: int | None = None
    issue_url: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    pr_state: str | None = None
    is_merged: bool = False
    merge_commit_sha: str | None = None
    candidate_bound: bool = False


class TimelineEventDTO(BaseModel):
    event_id: str
    timestamp: str
    event_type: str
    from_stage: str | None = None
    to_stage: str | None = None
    actor: str | None = None
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class DashboardOverviewResponse(BaseModel):
    system_status: SystemStatusDTO
    attention_items: list[AttentionItemDTO] = Field(default_factory=list)
    active_executions: list[ActiveExecutionDTO] = Field(default_factory=list)
    recent_completions: list[RecentCompletionDTO] = Field(default_factory=list)
    changes: list[ChangeSummaryDTO] = Field(default_factory=list)


class DashboardChangeDetailResponse(BaseModel):
    project_id: str
    change_name: str
    status: str
    run_id: str | None = None
    job_id: str | None = None
    current_stage: str | None = None
    target_branch: str | None = None
    current_executor: str | None = None
    stop_outcome: str | None = None
    human_gate: str | None = None
    pipeline: list[PipelinePhaseDTO] = Field(default_factory=list)
    candidate_authority: CandidateAuthorityDTO | None = None
    candidate_history: list[CandidateAuthorityDTO] = Field(default_factory=list)
    checks: list[CheckResultItemDTO] = Field(default_factory=list)
    review: ReviewSummaryDTO = Field(default_factory=ReviewSummaryDTO)
    audit: AuditSummaryDTO = Field(default_factory=AuditSummaryDTO)
    github: GitHubPRSummaryDTO = Field(default_factory=GitHubPRSummaryDTO)
    timeline: list[TimelineEventDTO] = Field(default_factory=list)
    blocker_details: list[dict[str, Any]] = Field(default_factory=list)


class OperationsDashboardService:
    """Read-model projection and query service for mini me operational surface."""

    def __init__(self, uow: PersistenceUnitOfWork) -> None:
        self.uow = uow

    def get_overview(self) -> DashboardOverviewResponse:
        """Construct high-level operational overview."""
        # 1. Capacity & Scheduler Status
        cap_service = CapacityLifecycleService(self.uow)
        sched_status = cap_service.get_scheduler_status()

        # 2. Provider Health
        health_service = ProviderHealthService(self.uow)
        prov_health = health_service.list_all_health()
        prov_dtos = [
            ProviderHealthDTO(
                provider_id=h.provider,
                status=h.status.value if hasattr(h.status, "value") else str(h.status),
                message=redact_secrets(h.last_error_summary or "") if h.last_error_summary else None,
                last_probe_at=_format_dt(h.updated_at),
            )
            for h in prov_health
        ]

        # 3. Projects & Changes
        projects = self.uow.projects.list_all()
        all_changes: list[Change] = []
        jobs_map: dict[str, Job] = {}
        for p in projects:
            all_changes.extend(self.uow.changes.list_by_project(p.project_id))
            if hasattr(self.uow.jobs, "list_by_project"):
                for j in self.uow.jobs.list_by_project(p.project_id):
                    jobs_map[j.job_id] = j

        # 4. Orchestration Runs
        all_runs = self.uow.orchestration_runs.list_runs()
        runs_by_change: dict[tuple[str, str], list[OrchestrationRun]] = {}
        for r in all_runs:
            key = (r.project_id, r.change_name)
            if key not in runs_by_change:
                runs_by_change[key] = []
            runs_by_change[key].append(r)

        # Sort runs for each change newest first
        for key in runs_by_change:
            runs_by_change[key].sort(key=lambda x: x.created_at, reverse=True)

        # 5. Attention Items, Active Executions & Recent Completions
        attention_items: list[AttentionItemDTO] = []
        active_executions: list[ActiveExecutionDTO] = []
        recent_completions: list[RecentCompletionDTO] = []

        for r in all_runs:
            job_for_run = jobs_map.get(r.active_job_id) if r.active_job_id else None
            is_recovery_blocked = (
                (job_for_run and job_for_run.status == JobStatus.RECOVERY_BLOCKED)
                or (r.stop_reason and "recovery" in r.stop_reason.lower())
            )
            is_checks_failed = (job_for_run and job_for_run.status == JobStatus.CHECKS_FAILED)

            if not r.is_active and (
                r.stop_outcome in {
                    OrchestrationStopOutcome.NEEDS_HUMAN,
                    OrchestrationStopOutcome.WAITING_CAPACITY,
                    OrchestrationStopOutcome.WAITING_EXTERNAL,
                }
                or is_recovery_blocked
                or is_checks_failed
            ):
                reason = r.stop_reason or (job_for_run.recovery_blocked_reason if (job_for_run and is_recovery_blocked) else None)
                if not reason and is_checks_failed:
                    reason = "Deterministic verification checks failed on candidate"
                if not reason:
                    reason = f"Stopped at {r.current_stage.value if r.current_stage else 'unknown'}"
                reason = redact_secrets(reason)

                guidance = "Review the stop reason and take necessary action."
                if r.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN:
                    guidance = "Human intervention required to resolve gate or decision."
                elif r.stop_outcome == OrchestrationStopOutcome.WAITING_CAPACITY:
                    guidance = "Wait for provider rate limits/capacity reset window."
                elif is_recovery_blocked:
                    guidance = "Unblock recovery by resolving external dependency or workspace state."
                elif is_checks_failed:
                    guidance = "Fix code or tests to satisfy deterministic verification suite."
                elif r.stop_outcome == OrchestrationStopOutcome.WAITING_EXTERNAL:
                    guidance = "Check external system status and resume run."

                attention_items.append(
                    AttentionItemDTO(
                        project_id=r.project_id,
                        change_name=r.change_name,
                        run_id=r.run_id,
                        job_id=r.active_job_id,
                        stage=r.current_stage.value if r.current_stage else "UNKNOWN",
                        stop_outcome=r.stop_outcome.value if r.stop_outcome else ("CHECKS_FAILED" if is_checks_failed else None),
                        human_gate=r.human_gate.value if r.human_gate else None,
                        reason=reason,
                        remediation_guidance=guidance,
                        stop_code=r.stop_outcome.value if r.stop_outcome else ("CHECKS_FAILED" if is_checks_failed else None),
                        can_retry=r.stop_outcome != OrchestrationStopOutcome.NEEDS_HUMAN,
                        can_reassign=True,
                        can_remediate=r.current_candidate_sha is not None,
                        updated_at=_format_dt(r.updated_at),
                    )
                )
            elif r.is_active:
                job_for_run = jobs_map.get(r.active_job_id) if r.active_job_id else (self.uow.jobs.get_by_id(r.active_job_id) if r.active_job_id else None)
                executor = (job_for_run.current_executor or job_for_run.implementer_role) if job_for_run else None
                active_executions.append(
                    ActiveExecutionDTO(
                        project_id=r.project_id,
                        change_name=r.change_name,
                        run_id=r.run_id,
                        job_id=r.active_job_id,
                        stage=r.current_stage.value if r.current_stage else "UNKNOWN",
                        current_executor=executor,
                        generation=r.current_generation,
                        candidate_sha=r.current_candidate_sha,
                        candidate_sha_short=_short_sha(r.current_candidate_sha),
                        started_at=_format_dt(r.created_at),
                        updated_at=_format_dt(r.updated_at),
                        latest_progress="IN_PROGRESS",
                    )
                )
            elif r.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE or r.current_stage == OrchestrationStage.PR_PREPARED:
                # Check PR info if exists
                actions = self.uow.orchestration_external_actions.list_by_run(r.run_id)
                pr_num = None
                pr_url = None
                for a in actions:
                    if a.result_payload and "pr_number" in a.result_payload:
                        pr_num = a.result_payload["pr_number"]
                        pr_url = a.result_payload.get("pr_url")

                # Review verdict & Audit risk strictly bound to current candidate SHA
                rev = self.uow.reviews.get_by_job_id(r.active_job_id) if r.active_job_id else None
                aud = self.uow.audits.get_by_job_id(r.active_job_id) if r.active_job_id else None

                rev_verdict = rev.verdict.value if (rev and rev.verdict and rev.candidate_sha == r.current_candidate_sha) else None
                reviewer = rev.reviewer_role if (rev and rev.candidate_sha == r.current_candidate_sha) else None
                aud_risk = aud.risk.value if (aud and aud.risk and aud.candidate_sha == r.current_candidate_sha) else None

                recent_completions.append(
                    RecentCompletionDTO(
                        project_id=r.project_id,
                        change_name=r.change_name,
                        run_id=r.run_id,
                        job_id=r.active_job_id,
                        generation=r.current_generation,
                        candidate_sha=r.current_candidate_sha,
                        candidate_sha_short=_short_sha(r.current_candidate_sha),
                        completed_at=_format_dt(r.updated_at),
                        reviewer_role=reviewer,
                        review_verdict=rev_verdict,
                        audit_risk=aud_risk,
                        github_pr_number=pr_num,
                        github_pr_url=pr_url,
                    )
                )

        # 6. Change Summaries
        change_summaries: list[ChangeSummaryDTO] = []
        for change in all_changes:
            key = (change.project_id, change.name)
            runs = runs_by_change.get(key, [])
            latest_run = runs[0] if runs else None

            binding = self.uow.bindings.get_by_project_and_change(change.project_id, change.name)

            # Determine composite canonical status
            status_val = self._derive_canonical_change_status(change, latest_run)

            job_for_latest = jobs_map.get(latest_run.active_job_id) if (latest_run and latest_run.active_job_id) else None
            executor = (job_for_latest.current_executor or job_for_latest.implementer_role) if job_for_latest else None

            change_summaries.append(
                ChangeSummaryDTO(
                    project_id=change.project_id,
                    change_name=change.name,
                    status=status_val,
                    schema_name=change.schema_name,
                    current_run_id=latest_run.run_id if latest_run else None,
                    active_job_id=latest_run.active_job_id if latest_run else None,
                    current_stage=latest_run.current_stage.value if (latest_run and latest_run.current_stage) else None,
                    stop_outcome=latest_run.stop_outcome.value if (latest_run and latest_run.stop_outcome) else None,
                    human_gate=latest_run.human_gate.value if (latest_run and latest_run.human_gate) else None,
                    current_executor=executor,
                    generation=latest_run.current_generation if latest_run else None,
                    candidate_sha=latest_run.current_candidate_sha if latest_run else None,
                    candidate_sha_short=_short_sha(latest_run.current_candidate_sha) if latest_run else None,
                    github_issue_number=binding.github_issue_number if binding else None,
                    github_pr_number=binding.github_pr_number if binding else None,
                    updated_at=_format_dt(latest_run.updated_at if latest_run else change.updated_at),
                )
            )

        # Check GitHub provider health
        github_health_status = "HEALTHY"
        for h in prov_health:
            if h.provider.lower() == "github":
                github_health_status = h.status.value if hasattr(h.status, "value") else str(h.status)
                break

        is_overall_healthy = (
            github_health_status not in {"FAILED", "DEGRADED"}
            and all(
                (h.status.value if hasattr(h.status, "value") else str(h.status)) not in {"FAILED", "DEGRADED"}
                for h in prov_health
            )
        )

        system_status = SystemStatusDTO(
            healthy=is_overall_healthy,
            database_engine="PostgreSQL",
            database_healthy=True,
            database_message="PostgreSQL operational",
            scheduler_mode=sched_status.mode.value,
            queue_depth=sum(1 for c in all_changes if c.status == ChangeStatus.READY),
            github_app_health=github_health_status,
            active_runs_count=len(active_executions),
            total_changes_count=len(change_summaries),
            attention_runs_count=len(attention_items),
            providers=prov_dtos,
        )

        return DashboardOverviewResponse(
            system_status=system_status,
            attention_items=attention_items,
            active_executions=active_executions,
            recent_completions=recent_completions,
            changes=change_summaries,
        )

    def get_change_detail(
        self, project_id: str, change_name: str, run_id: str | None = None
    ) -> DashboardChangeDetailResponse:
        """Construct comprehensive detail for a specific change and its latest/selected run."""
        change = self.uow.changes.get_by_name(project_id, change_name)
        runs = self.uow.orchestration_runs.list_runs(project_id=project_id, change_name=change_name)
        if not change and not runs:
            raise ValueError(f"Change '{change_name}' not found in project '{project_id}'")
        runs.sort(key=lambda x: x.created_at, reverse=True)

        selected_run: OrchestrationRun | None = None
        if run_id:
            for r in runs:
                if r.run_id == run_id:
                    selected_run = r
                    break
        if not selected_run and runs:
            selected_run = runs[0]

        binding = self.uow.bindings.get_by_project_and_change(project_id, change_name)

        status_val = self._derive_canonical_change_status(change, selected_run)

        project = self.uow.projects.get_by_id(project_id)
        job = self.uow.jobs.get_by_id(selected_run.active_job_id) if (selected_run and selected_run.active_job_id) else None
        target_branch = project.base_branch if project else None
        current_executor = (job.current_executor or job.implementer_role) if job else None

        # Pipeline phases & details
        candidate_authority, candidate_history = self._project_candidate_authority(selected_run)
        pipeline_phases = self._project_pipeline_phases(change, selected_run, candidate_authority)
        checks = self._project_checks(selected_run, candidate_authority)
        review = self._project_review(selected_run, candidate_authority)
        audit = self._project_audit(selected_run, candidate_authority)
        github = self._project_github_binding(binding, selected_run)
        timeline = self._project_timeline(project_id, change_name, selected_run)
        blockers = self._project_blockers(selected_run)

        return DashboardChangeDetailResponse(
            project_id=project_id,
            change_name=change_name,
            status=status_val,
            run_id=selected_run.run_id if selected_run else None,
            job_id=selected_run.active_job_id if selected_run else None,
            current_stage=selected_run.current_stage.value if (selected_run and selected_run.current_stage) else None,
            target_branch=target_branch,
            current_executor=current_executor,
            stop_outcome=selected_run.stop_outcome.value if (selected_run and selected_run.stop_outcome) else None,
            human_gate=selected_run.human_gate.value if (selected_run and selected_run.human_gate) else None,
            pipeline=pipeline_phases,
            candidate_authority=candidate_authority,
            candidate_history=candidate_history,
            checks=checks,
            review=review,
            audit=audit,
            github=github,
            timeline=timeline,
            blocker_details=blockers,
        )

    def get_run_detail(self, run_id: str) -> DashboardChangeDetailResponse:
        """Construct detail for a specific orchestration run."""
        run = self.uow.orchestration_runs.get_by_id(run_id)
        if not run:
            raise ValueError(f"Orchestration run '{run_id}' not found")
        return self.get_change_detail(run.project_id, run.change_name, run_id=run_id)

    def get_events_timeline(
        self,
        project_id: str | None = None,
        change_name: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[TimelineEventDTO]:
        """Construct chronological, sanitized event sequence."""
        return self._project_timeline(project_id, change_name, run_id=run_id, limit=limit)

    # -------------------------------------------------------------------------
    # Internal Projections & Isolation
    # -------------------------------------------------------------------------

    def _derive_canonical_change_status(
        self, change: Change | None, run: OrchestrationRun | None
    ) -> str:
        """Derive the canonical high-level status for a change."""
        if not run:
            if not change:
                return "DISCOVERED"
            if change.status == ChangeStatus.DONE:
                return "COMPLETED"
            if change.last_readiness_status == ReadinessState.READY:
                return "READY"
            return "NOT_READY"

        if run.is_active:
            return "RUNNING"

        if run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN:
            return "NEEDS_HUMAN"
        if run.stop_outcome in {
            OrchestrationStopOutcome.WAITING_CAPACITY,
            OrchestrationStopOutcome.WAITING_EXTERNAL,
        }:
            return "WAITING"
        if (
            run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE
            or run.current_stage == OrchestrationStage.PR_PREPARED
        ):
            return "COMPLETED"
        if run.current_stage in {OrchestrationStage.ADMITTED, OrchestrationStage.PREPARING_EXECUTION}:
            return "READY"

        return "FAILED"

    def _project_pipeline_phases(
        self,
        change: Change | None,
        run: OrchestrationRun | None,
        candidate_authority: CandidateAuthorityDTO | None = None,
    ) -> list[PipelinePhaseDTO]:
        """Expose 6 major pipeline phases: readiness, implementation, checks, review, audit, pr_merge."""
        phases: list[PipelinePhaseDTO] = []

        # 1. Readiness
        readiness_status = "not_started"
        readiness_summary = "Not evaluated"
        if change and change.last_readiness_status == ReadinessState.READY:
            readiness_status = "passed"
            readiness_summary = "Definition of Ready satisfied"
        elif change and change.last_readiness_status == ReadinessState.NOT_READY:
            readiness_status = "failed"
            readiness_summary = "; ".join(change.last_readiness_reasons) if change.last_readiness_reasons else "DoR criteria unmet"
        elif run:
            readiness_status = "passed"
            readiness_summary = "Admission verified"
        phases.append(PipelinePhaseDTO(name="readiness", display_name="Readiness", status=readiness_status, summary=readiness_summary))

        if not run:
            for name, disp in [
                ("implementation", "Implementation"),
                ("checks", "Deterministic Checks"),
                ("review", "Complementary Review"),
                ("audit", "DeepSeek Audit"),
                ("pr_merge", "PR & Merge"),
            ]:
                phases.append(PipelinePhaseDTO(name=name, display_name=disp, status="not_started", summary="Awaiting admission"))
            return phases

        # Evaluate remaining phases based on stage and persistent state
        stage = run.current_stage
        job: Job | None = None
        if run.active_job_id:
            job = self.uow.jobs.get_by_id(run.active_job_id)
        executor = (job.current_executor or job.implementer_role) if job else None
        authoritative_sha = (
            candidate_authority.candidate_sha
            if candidate_authority
            else (run.current_candidate_sha if run else None)
        )

        # 2. Implementation
        impl_status = "not_started"
        impl_summary = "Not started"
        if stage in {OrchestrationStage.PREPARING_EXECUTION, OrchestrationStage.IMPLEMENTING}:
            impl_status = "running"
            impl_summary = f"Executing under {executor or 'primary implementer'}"
        elif stage in {
            OrchestrationStage.EVALUATING_ATTEMPT,
            OrchestrationStage.RUNNING_CHECKS,
            OrchestrationStage.FREEZING_CANDIDATE,
            OrchestrationStage.COMPLEMENTARY_REVIEW,
            OrchestrationStage.REVIEW_REMEDIATION,
            OrchestrationStage.INDEPENDENT_AUDIT,
            OrchestrationStage.AUDIT_REMEDIATION,
            OrchestrationStage.PREPARING_PR,
            OrchestrationStage.PR_PREPARED,
        }:
            if authoritative_sha:
                impl_status = "passed"
                impl_summary = f"Candidate {_short_sha(authoritative_sha)} generated by {executor or 'implementer'}"
            else:
                impl_status = "running"
                impl_summary = f"Candidate generation in progress under {executor or 'implementer'}"
        elif run.stop_outcome in {OrchestrationStopOutcome.WAITING_CAPACITY, OrchestrationStopOutcome.WAITING_EXTERNAL}:
            impl_status = "waiting"
            impl_summary = "Waiting for capacity or external event"
        elif run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN and stage == OrchestrationStage.IMPLEMENTING:
            impl_status = "blocked"
            impl_summary = "Implementation blocked"
        impl_details = {
            "attempts_count": run.current_generation,
            "latest_progress": f"Generation {run.current_generation}",
            "is_mixed_authorship": False,
        }
        phases.append(PipelinePhaseDTO(name="implementation", display_name="Implementation", status=impl_status, summary=impl_summary, details=impl_details))

        # 3. Deterministic Checks
        checks_status = "not_started"
        checks_summary = "Not executed"
        if stage == OrchestrationStage.RUNNING_CHECKS:
            checks_status = "running"
            checks_summary = "Executing deterministic checks"
        elif stage in {
            OrchestrationStage.FREEZING_CANDIDATE,
            OrchestrationStage.COMPLEMENTARY_REVIEW,
            OrchestrationStage.REVIEW_REMEDIATION,
            OrchestrationStage.INDEPENDENT_AUDIT,
            OrchestrationStage.AUDIT_REMEDIATION,
            OrchestrationStage.PREPARING_PR,
            OrchestrationStage.PR_PREPARED,
        }:
            # Verify if checks passed on job
            if job and job.status == JobStatus.CHECKS_FAILED:
                checks_status = "failed"
                checks_summary = "One or more deterministic checks failed"
            else:
                checks_status = "passed"
                checks_summary = "All deterministic checks passed"
        elif run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN and stage == OrchestrationStage.RUNNING_CHECKS:
            checks_status = "failed"
            checks_summary = "Checks failed"
        passed_count = 0
        failed_count = 0
        if job:
            cr_list = self.uow.check_results.list_by_job(job.job_id)
            passed_count = sum(1 for c in cr_list if c.exit_code == 0)
            failed_count = sum(1 for c in cr_list if c.exit_code != 0)
        checks_details = {"passed_count": passed_count, "failed_count": failed_count}
        phases.append(PipelinePhaseDTO(name="checks", display_name="Deterministic Checks", status=checks_status, summary=checks_summary, details=checks_details))

        # 4. Complementary Review
        rev_status = "not_started"
        rev_summary = "Not started"
        if checks_status == "failed":
            rev_status = "blocked"
            rev_summary = "Blocked by failing deterministic checks"
        elif stage == OrchestrationStage.COMPLEMENTARY_REVIEW:
            rev_status = "running"
            rev_summary = "Complementary review in progress"
        elif stage in {
            OrchestrationStage.REVIEW_REMEDIATION,
            OrchestrationStage.INDEPENDENT_AUDIT,
            OrchestrationStage.AUDIT_REMEDIATION,
            OrchestrationStage.PREPARING_PR,
            OrchestrationStage.PR_PREPARED,
        }:
            rev = self.uow.reviews.get_by_job_id(job.job_id) if job else None
            if rev:
                if rev.candidate_sha != authoritative_sha:
                    rev_status = "running"
                    rev_summary = "Review pending for updated candidate"
                elif rev.verdict == ReviewVerdict.READY_TO_MERGE:
                    rev_status = "passed"
                    rev_summary = f"Approved by {rev.reviewer_role}"
                elif rev.verdict == ReviewVerdict.CHANGES_REQUIRED:
                    rev_status = "failed"
                    rev_summary = "Changes required by reviewer"
                else:
                    rev_status = "running"
                    rev_summary = f"Review verdict: {rev.verdict.value if rev.verdict else 'pending'}"
            else:
                rev_status = "not_started"
                rev_summary = "No review record found"
        elif run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN and stage == OrchestrationStage.COMPLEMENTARY_REVIEW:
            rev_status = "blocked"
            rev_summary = "Review blocked"
        phases.append(PipelinePhaseDTO(name="review", display_name="Complementary Review", status=rev_status, summary=rev_summary))

        # 5. DeepSeek Audit
        audit_status = "not_started"
        audit_summary = "Not started"
        if checks_status == "failed" or rev_status in {"failed", "blocked"}:
            audit_status = "blocked"
            audit_summary = "Blocked by upstream check or review failure"
        elif stage == OrchestrationStage.INDEPENDENT_AUDIT:
            audit_status = "running"
            audit_summary = "DeepSeek Direct audit in progress"
        elif stage in {
            OrchestrationStage.AUDIT_REMEDIATION,
            OrchestrationStage.PREPARING_PR,
            OrchestrationStage.PR_PREPARED,
        }:
            aud = self.uow.audits.get_by_job_id(job.job_id) if job else None
            if aud:
                if aud.candidate_sha != authoritative_sha:
                    audit_status = "running"
                    audit_summary = "Audit pending for updated candidate"
                elif aud.status == AuditStatus.AUDIT_COMPLETED:
                    if aud.risk is None or aud.risk == AuditRiskLevel.LOW:
                        audit_status = "passed"
                        audit_summary = f"Audit passed (risk: {aud.risk.value if aud.risk else 'low'})"
                    else:
                        audit_status = "failed"
                        audit_summary = f"Audit completed with {aud.risk.value} risk findings"
                elif aud.status == AuditStatus.AUDIT_BLOCKED:
                    audit_status = "failed"
                    audit_summary = "Audit blocked by security/integrity finding"
                else:
                    audit_status = "running"
                    audit_summary = "Audit in progress"
            else:
                audit_status = "not_started"
                audit_summary = "No audit record found"
        elif run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN and stage == OrchestrationStage.INDEPENDENT_AUDIT:
            audit_status = "blocked"
            audit_summary = "Audit blocked"
        phases.append(PipelinePhaseDTO(name="audit", display_name="DeepSeek Audit", status=audit_status, summary=audit_summary))

        # 6. PR & Merge
        pr_status = "not_started"
        pr_summary = "Not prepared"
        pr_details = {}
        if run:
            actions = self.uow.orchestration_external_actions.list_by_run(run.run_id)
            for a in actions:
                if a.result_payload and "merge_commit_sha" in a.result_payload:
                    pr_details["merge_commit_sha"] = a.result_payload["merge_commit_sha"]

        if checks_status == "failed" or rev_status in {"failed", "blocked"} or audit_status in {"failed", "blocked"}:
            pr_status = "blocked"
            pr_summary = "Blocked by upstream pipeline failure"
        elif stage == OrchestrationStage.PREPARING_PR:
            pr_status = "running"
            pr_summary = "Preparing Pull Request"
        elif "merge_commit_sha" in pr_details or (change and change.status == ChangeStatus.DONE):
            pr_status = "passed"
            pr_summary = f"Merged into target branch ({_short_sha(pr_details.get('merge_commit_sha')) or 'complete'})"
        elif stage == OrchestrationStage.PR_PREPARED or run.stop_outcome == OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE:
            if rev_status == "passed" and audit_status == "passed":
                pr_status = "passed"
                pr_summary = "Ready for human merge"
            else:
                pr_status = "not_started"
                pr_summary = "Waiting for review and audit completion"

        phases.append(PipelinePhaseDTO(name="pr_merge", display_name="PR & Merge", status=pr_status, summary=pr_summary, details=pr_details))

        return phases

    def _project_candidate_authority(
        self, run: OrchestrationRun | None
    ) -> tuple[CandidateAuthorityDTO | None, list[CandidateAuthorityDTO]]:
        """Project candidate authority and monotonic candidate history with stale isolation."""
        if not run:
            return None, []

        candidates = self.uow.orchestration_candidates.list_by_run(run.run_id)
        candidates.sort(key=lambda c: c.generation)

        dtos: list[CandidateAuthorityDTO] = []
        for c in candidates:
            # Manifest info
            manifest = (
                self.uow.candidate_manifests.get_by_candidate_sha(run.active_job_id, c.candidate_sha)
                if (run.active_job_id and hasattr(self.uow.candidate_manifests, "get_by_candidate_sha"))
                else None
            )
            changed_files = list(manifest.file_manifest.keys()) if (manifest and hasattr(manifest, "file_manifest") and manifest.file_manifest) else []
            is_superseded = bool(c.superseded_by_id)
            dtos.append(
                CandidateAuthorityDTO(
                    generation=c.generation,
                    candidate_sha=c.candidate_sha,
                    candidate_sha_short=_short_sha(c.candidate_sha) or "",
                    base_sha=c.base_sha,
                    base_sha_short=_short_sha(c.base_sha) or "",
                    manifest_hash=manifest.manifest_hash if manifest else c.manifest_hash,
                    is_frozen=c.is_frozen,
                    is_superseded=is_superseded,
                    changed_files=changed_files,
                    created_at=_format_dt(c.created_at),
                )
            )

        # Current candidate authority is latest non-superseded candidate
        current: CandidateAuthorityDTO | None = None
        for dto in reversed(dtos):
            if not dto.is_superseded:
                current = dto
                break

        if not current and run.current_candidate_sha:
            current = CandidateAuthorityDTO(
                generation=run.current_generation,
                candidate_sha=run.current_candidate_sha,
                candidate_sha_short=_short_sha(run.current_candidate_sha) or "",
                base_sha=run.base_sha,
                base_sha_short=_short_sha(run.base_sha) or "",
                is_frozen=True,
                is_superseded=False,
                created_at=_format_dt(run.updated_at),
            )

        return current, dtos

    def _project_checks(
        self, run: OrchestrationRun | None, candidate: CandidateAuthorityDTO | None
    ) -> list[CheckResultItemDTO]:
        """Project deterministic checks bound to current candidate."""
        if not run or not run.active_job_id:
            return []

        check_results = self.uow.check_results.list_by_job(run.active_job_id)
        diagnostics = self.uow.evidence_diagnostics.list_by_job(run.active_job_id)
        diag_map = {d.check_name: d for d in diagnostics if d.check_name}

        dtos: list[CheckResultItemDTO] = []
        current_sha = candidate.candidate_sha if candidate else run.current_candidate_sha
        for cr in check_results:
            if cr.candidate_sha and current_sha and cr.candidate_sha != current_sha:
                continue
            diag = diag_map.get(cr.check_name)
            diag_snippet = None
            if diag and hasattr(diag, "reproducible_command") and diag.reproducible_command:
                diag_snippet = redact_secrets(diag.reproducible_command)
            elif diag and hasattr(diag, "reason") and diag.reason:
                diag_snippet = redact_secrets(diag.reason)
            elif cr.exit_code != 0:
                diag_snippet = f"Exited with code {cr.exit_code}"

            dtos.append(
                CheckResultItemDTO(
                    check_name=cr.check_name,
                    command=cr.command,
                    status="PASS" if cr.exit_code == 0 else "FAIL",
                    exit_code=cr.exit_code,
                    duration_ms=cr.duration_ms,
                    candidate_sha=current_sha,
                    diagnostic_snippet=diag_snippet,
                )
            )
        return dtos

    def _project_review(
        self, run: OrchestrationRun | None, candidate: CandidateAuthorityDTO | None
    ) -> ReviewSummaryDTO:
        """Project complementary review with stale candidate isolation."""
        if not run or not run.active_job_id:
            return ReviewSummaryDTO()

        rev = self.uow.reviews.get_by_job_id(run.active_job_id)
        if not rev:
            return ReviewSummaryDTO()

        findings = self.uow.review_findings.list_by_review(rev.review_id)
        material_count = sum(1 for f in findings if f.severity.value in {"BLOCKER", "MAJOR"})

        # Stale isolation check
        is_stale = False
        if candidate and rev.candidate_sha and rev.candidate_sha != candidate.candidate_sha:
            is_stale = True

        clean_summary = redact_secrets(rev.summary or "") if rev.summary else None
        clean_findings = [
            {
                "finding_id": f.finding_id,
                "severity": f.severity.value,
                "location": f.location,
                "violated_requirement": redact_secrets(f.violated_requirement or ""),
                "expected_correction": redact_secrets(f.expected_correction or ""),
                "created_at": _format_dt(f.created_at),
            }
            for f in findings
        ]

        model_name = rev.model_name if hasattr(rev, "model_name") else None
        return ReviewSummaryDTO(
            review_id=rev.review_id,
            reviewer_role=rev.reviewer_role,
            model=model_name,
            status=rev.status.value,
            verdict=rev.verdict.value if rev.verdict else None,
            candidate_sha=rev.candidate_sha,
            is_stale_to_current_candidate=is_stale,
            is_mixed_authorship=rev.is_mixed_authorship if hasattr(rev, "is_mixed_authorship") else False,
            material_findings_count=material_count,
            summary=clean_summary,
            findings=clean_findings,
        )

    def _project_audit(
        self, run: OrchestrationRun | None, candidate: CandidateAuthorityDTO | None
    ) -> AuditSummaryDTO:
        """Project DeepSeek Direct audit with stale candidate isolation."""
        if not run or not run.active_job_id:
            return AuditSummaryDTO()

        aud = self.uow.audits.get_by_job_id(run.active_job_id)
        if not aud:
            return AuditSummaryDTO()

        findings = self.uow.audit_findings.list_by_audit(aud.audit_id)
        material_count = sum(1 for f in findings if f.severity.value in {"critical", "high", "medium"})

        is_stale = False
        if candidate and aud.candidate_sha and aud.candidate_sha != candidate.candidate_sha:
            is_stale = True

        clean_summary = redact_secrets(aud.summary or "") if aud.summary else None
        clean_findings = [
            {
                "finding_id": f.finding_id,
                "severity": f.severity.value,
                "category": f.category,
                "message": redact_secrets(f.message or ""),
                "file": f.file,
                "location": f.location,
                "created_at": _format_dt(f.created_at),
            }
            for f in findings
        ]

        return AuditSummaryDTO(
            audit_id=aud.audit_id,
            provider=aud.provider,
            model=aud.model,
            status=aud.status.value,
            risk=aud.risk.value if aud.risk else None,
            candidate_sha=aud.candidate_sha,
            is_stale_to_current_candidate=is_stale,
            material_findings_count=material_count,
            summary=clean_summary,
            findings=clean_findings,
        )

    def _project_github_binding(
        self, binding: Any | None, run: OrchestrationRun | None
    ) -> GitHubPRSummaryDTO:
        """Project GitHub Issue and PR integration details."""
        if not binding:
            return GitHubPRSummaryDTO()

        pr_num = binding.github_pr_number
        pr_url = binding.github_pr_url
        pr_state = "open" if pr_num else None
        is_merged = False

        if run:
            actions = self.uow.orchestration_external_actions.list_by_run(run.run_id)
            for a in actions:
                if a.result_payload and "pr_number" in a.result_payload:
                    pr_num = a.result_payload["pr_number"]
                    pr_url = a.result_payload.get("pr_url", pr_url)
                    pr_state = a.result_payload.get("state", pr_state)
                    is_merged = a.result_payload.get("merged", is_merged)

        return GitHubPRSummaryDTO(
            issue_number=binding.github_issue_number,
            issue_url=f"https://github.com/{binding.repository}/issues/{binding.github_issue_number}"
            if binding.github_issue_number and binding.repository
            else None,
            pr_number=pr_num,
            pr_url=pr_url,
            pr_state=pr_state,
            is_merged=is_merged,
            candidate_bound=bool(run and run.current_candidate_sha),
        )

    def _project_timeline(
        self,
        project_id: str | None = None,
        change_name: str | None = None,
        run: OrchestrationRun | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[TimelineEventDTO]:
        """Project chronological timeline of stage events and lifecycle transitions."""
        events: list[TimelineEventDTO] = []

        target_run_id = run.run_id if run else run_id

        # 1. Stage events from orchestration_stage_events
        target_runs: list[str] = []
        if target_run_id:
            target_runs = [target_run_id]
        elif project_id and change_name:
            change_runs = self.uow.orchestration_runs.list_runs(project_id=project_id, change_name=change_name)
            target_runs = [r.run_id for r in change_runs]

        for rid in target_runs:
            stage_events = self.uow.orchestration_stage_events.list_by_run(rid)
            for se in stage_events:
                summary = f"Transitioned from {se.from_stage.value if se.from_stage else 'INITIAL'} to {se.to_stage.value}"
                details = se.evidence_references or {}
                if "reason" in details:
                    summary += f": {details['reason']}"

                events.append(
                    TimelineEventDTO(
                        event_id=se.event_id,
                        timestamp=_format_dt(se.created_at) or "",
                        event_type="STAGE_TRANSITION",
                        from_stage=se.from_stage.value if se.from_stage else None,
                        to_stage=se.to_stage.value,
                        actor=se.actor or "orchestrator",
                        summary=redact_secrets(summary),
                        details={k: _sanitize_obj(v) for k, v in details.items()},
                    )
                )

        # 2. General events from events repository (only if run_id not specified or if matching project/change provided)
        if not target_run_id or project_id or change_name:
            general_events = self.uow.events.list_events(project_id=project_id, change_id=change_name, limit=limit)
            for ge in general_events:
                summary = ge.event_type.value.replace("_", " ").title() if hasattr(ge.event_type, "value") else str(ge.event_type).replace("_", " ").title()
                if ge.payload and "reason" in ge.payload:
                    summary += f": {ge.payload['reason']}"

                events.append(
                    TimelineEventDTO(
                        event_id=ge.event_id,
                        timestamp=_format_dt(ge.timestamp) or "",
                        event_type=ge.event_type.value if hasattr(ge.event_type, "value") else str(ge.event_type),
                        actor="system",
                        summary=redact_secrets(summary),
                        details={k: _sanitize_obj(v) for k, v in ge.payload.items()} if ge.payload else {},
                    )
                )

        # Deduplicate events by event_id
        seen_ids: set[str] = set()
        deduped_events: list[TimelineEventDTO] = []
        for e in events:
            if e.event_id not in seen_ids:
                seen_ids.add(e.event_id)
                deduped_events.append(e)

        # Sort all events chronologically newest first
        deduped_events.sort(key=lambda e: e.timestamp, reverse=True)
        return deduped_events[:limit]

    def _project_blockers(self, run: OrchestrationRun | None) -> list[dict[str, Any]]:
        """Project blocker claims and recovery blockers."""
        if not run:
            return []

        blockers: list[dict[str, Any]] = []
        if run.active_job_id:
            claims = self.uow.blocker_claims.list_by_job(run.active_job_id)
            for c in claims:
                blockers.append(
                    {
                        "claim_id": c.claim_id,
                        "claim_type": c.claim_type,
                        "description": redact_secrets(c.description),
                        "is_validated": c.is_validated,
                        "verdict": c.validation_verdict.value if c.validation_verdict else None,
                        "created_at": _format_dt(c.created_at),
                    }
                )

        if run.stop_reason:
            blockers.append(
                {
                    "type": "STOP_OUTCOME",
                    "stop_outcome": run.stop_outcome.value if run.stop_outcome else None,
                    "reason": redact_secrets(run.stop_reason),
                    "human_gate": run.human_gate.value if run.human_gate else None,
                    "created_at": _format_dt(run.updated_at),
                }
            )

        return blockers
