"""FastAPI application for mini me daemon."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Generator

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from minime.adapters.openspec import OpenSpecAdapter
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.domain.enums import (
    EventType,
    OperatorActionType,
    PreviewStatus,
    ValidationVerdict,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    ActionDescriptor,
    Change,
    Event,
    Job,
    JobLog,
    OperatorActionRecord,
    OperatorActionRequest,
    OperatorActionResult,
    PreviewSession,
    Project,
    ProviderHealth,
    QueueExplainReport,
    SchedulerDecisionRecord,
    SchedulerStatus,
    SchedulerStatusView,
    WorkQueueItem,
    utc_now,
)
from minime.logging import redact_secrets
from minime.services.budget_service import BudgetService
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
from minime.services.container_preview_service import ContainerPreviewService
from minime.services.control_plane_service import ControlPlaneService
from minime.services.dashboard_service import (
    DashboardChangeDetailResponse,
    DashboardOverviewResponse,
    OperationsDashboardService,
    TimelineEventDTO,
)
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.orchestration_service import OrchestrationService
from minime.services.project_service import ProjectService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.readiness_service import ReadinessService
from minime.services.restart_recovery_service import RestartRecoveryService
from minime.services.scheduler_service import SchedulerService
from minime.services.status_service import StatusService
from minime.services.validation_authority_service import ValidationAuthorityService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: reconcile active jobs and clean abandoned locks
    sess = None
    try:
        sess = db_manager.sessionmaker()
        uow = PostgresPersistenceUnitOfWork(sess)
        recovery_service = RestartRecoveryService(uow, project_root=".")
        orchestration_service = OrchestrationService(uow, project_root=".")
        reconciled = recovery_service.reconcile_on_startup(
            orchestration_service=orchestration_service
        )
        if reconciled:
            logger.info(f"Reconciled {len(reconciled)} jobs on startup.")
    except Exception as exc:
        logger.warning(f"Error during startup reconciliation: {exc}")
    finally:
        if sess:
            sess.close()
    yield


app = FastAPI(
    title="mini me API",
    version="0.1.0",
    description="Control plane and operational status API for mini me.",
    lifespan=lifespan,
)


def get_uow() -> Generator[PostgresPersistenceUnitOfWork, None, None]:
    """Dependency that yields a persistence unit of work backed by a database session."""
    sess = db_manager.sessionmaker()
    try:
        uow = PostgresPersistenceUnitOfWork(sess)
        yield uow
    finally:
        sess.close()


UowDep = Annotated[PostgresPersistenceUnitOfWork, Depends(get_uow)]


class ProjectCreateRequest(BaseModel):
    project_id: str
    display_name: str
    repository: str
    base_branch: str = "main"
    openspec_path: str = "openspec"
    implementer: str = "codex"
    reviewer: str = "antigravity"
    checks: list[dict[str, Any]] = Field(default_factory=list)
    external_providers_allowed: list[str] = Field(
        default_factory=lambda: ["codex", "antigravity", "deepseek"]
    )
    openrouter_drain_allowed: bool = False
    deployment_preview: dict[str, Any] = Field(default_factory=dict)
    deployment_production: dict[str, Any] = Field(default_factory=dict)


class JobRunRequest(BaseModel):
    change_name: str
    project_root: str = "."


@app.get("/health")
def get_health() -> dict[str, Any]:
    healthy, message = db_manager.check_health()
    return {
        "status": "healthy" if healthy else "unhealthy",
        "database": {
            "engine": "PostgreSQL",
            "healthy": healthy,
            "message": message,
        },
        "version": "0.1.0",
    }


@app.get("/status")
def get_status(uow: UowDep) -> dict[str, Any]:
    service = StatusService(uow)
    return service.get_system_status()


@app.get("/scheduler/status")
def get_scheduler_status(uow: UowDep) -> SchedulerStatus:
    service = CapacityLifecycleService(uow)
    return service.get_scheduler_status()


@app.get("/providers/health")
def get_providers_health(uow: UowDep) -> list[ProviderHealth]:
    service = ProviderHealthService(uow)
    return service.list_all_health()


@app.get("/budget/usage")
@app.get("/projects/{project_id}/budget")
def get_budget_usage(uow: UowDep, project_id: str | None = None) -> dict[str, Any]:
    service = BudgetService(uow)
    if not project_id:
        projects = uow.projects.list_all()
        project_id = projects[0].project_id if projects else ""
    policy = uow.budget_policies.get_for_update(project_id) if project_id else None
    if not policy:
        return {
            "project_id": project_id,
            "policy": None,
            "headroom": None,
            "reservations": [],
            "ledger": [],
            "token_usage_by_model": {},
        }
    headroom = service._compute_headroom(project_id, policy)
    reservations = [r.model_dump() for r in uow.budget_reservations.list_by_project(project_id)]
    ledger = [e.model_dump() for e in uow.budget_ledger.list_by_project(project_id)]
    token_usage = service.get_token_usage_breakdown(project_id)
    return {
        "project_id": project_id,
        "policy": policy.model_dump(),
        "headroom": headroom.__dict__,
        "unresolved_settlements_count": headroom.unresolved_count,
        "unresolved_settlements_usd": headroom.unresolved_usd,
        "reservations": reservations,
        "ledger": ledger,
        "token_usage_by_model": token_usage,
    }


@app.get("/providers/openrouter/status")
def get_openrouter_status(uow: UowDep, project_id: str | None = None) -> dict[str, Any]:
    service = BudgetService(uow)
    if not project_id:
        projects = uow.projects.list_all()
        project_id = projects[0].project_id if projects else ""
    policy = uow.budget_policies.get_for_update(project_id) if project_id else None
    if not policy:
        return {
            "project_id": project_id,
            "enabled": False,
            "is_breached": False,
            "policy": None,
            "headroom": None,
            "allowed_models": {
                "implementer": ["anthropic/claude-3.5-sonnet", "qwen/qwen-2.5-coder-32b-instruct"],
                "reviewer": [
                    "openai/gpt-4o",
                    "meta-llama/llama-3.3-70b-instruct",
                    "mistralai/mistral-large",
                ],
            },
        }
    headroom = service._compute_headroom(project_id, policy)
    return {
        "project_id": project_id,
        "enabled": policy.enabled,
        "is_breached": policy.is_breached,
        "daily_cap_usd": policy.daily_cap_usd,
        "monthly_cap_usd": policy.monthly_cap_usd,
        "currency": policy.currency,
        "policy_version": policy.policy_version,
        "headroom": headroom.__dict__,
        "allowed_models": {
            "implementer": ["anthropic/claude-3.5-sonnet", "qwen/qwen-2.5-coder-32b-instruct"],
            "reviewer": [
                "openai/gpt-4o",
                "meta-llama/llama-3.3-70b-instruct",
                "mistralai/mistral-large",
            ],
        },
    }


@app.get("/projects")
def list_projects(
    uow: UowDep,
) -> list[Project]:
    service = ProjectService(uow)
    return service.list_projects()


@app.post("/projects", status_code=status.HTTP_201_CREATED)
def register_project(
    req: ProjectCreateRequest,
    uow: UowDep,
) -> Project:
    try:
        service = ProjectService(uow)
        return service.register_project(
            project_id=req.project_id,
            display_name=req.display_name,
            repository=req.repository,
            base_branch=req.base_branch,
            openspec_path=req.openspec_path,
            implementer=req.implementer,
            reviewer=req.reviewer,
            checks=req.checks,
            external_providers_allowed=req.external_providers_allowed,
            openrouter_drain_allowed=req.openrouter_drain_allowed,
            deployment_preview=req.deployment_preview,
            deployment_production=req.deployment_production,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.get("/projects/{project_id}")
def get_project(
    project_id: str,
    uow: UowDep,
) -> Project:
    service = ProjectService(uow)
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    return project


@app.get("/projects/{project_id}/changes")
def list_project_changes(
    project_id: str,
    uow: UowDep,
) -> list[Change]:
    changes = uow.changes.list_by_project(project_id)
    return changes


@app.post("/projects/{project_id}/discover")
def discover_project_changes(
    project_id: str,
    project_root: str,
    uow: UowDep,
) -> list[Change]:
    service = ProjectService(uow)
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )

    adapter = OpenSpecAdapter()
    discovered = adapter.discover_changes(project, project_root)
    for change in discovered:
        uow.changes.save(change)
    uow.commit()
    return discovered


@app.get("/projects/{project_id}/changes/{change_name}/readiness")
def evaluate_readiness(
    project_id: str,
    change_name: str,
    project_root: str,
    uow: UowDep,
    current_active_change: str | None = None,
) -> dict[str, Any]:
    service = ReadinessService(uow)
    eval_result = service.evaluate_change_readiness(
        project_id=project_id,
        change_name=change_name,
        project_root=project_root,
        current_active_change=current_active_change,
    )
    return eval_result.model_dump()


@app.post("/projects/{project_id}/jobs", status_code=status.HTTP_202_ACCEPTED)
async def run_project_job(
    project_id: str,
    req: JobRunRequest,
    uow: UowDep,
) -> Job:
    try:
        service = ExecutionPipelineService(uow, project_root=req.project_root)
        return await service.run_job(project_id, req.change_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.get("/projects/{project_id}/jobs")
def list_project_jobs(project_id: str, uow: UowDep) -> list[dict[str, Any]]:
    jobs = uow.jobs.list_by_project(project_id)
    return [_job_summary(uow, job) for job in jobs]


@app.get("/jobs/{job_id}")
def get_job(job_id: str, uow: UowDep) -> dict[str, Any]:
    job = uow.jobs.get_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found"
        )
    return _job_summary(uow, job)


@app.get("/jobs/{job_id}/logs")
def get_job_logs(job_id: str, uow: UowDep) -> list[JobLog]:
    if not uow.jobs.get_by_id(job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found"
        )
    return uow.job_logs.list_by_job(job_id)


@app.get("/jobs/{job_id}/review")
def get_job_review(job_id: str, uow: UowDep) -> dict[str, Any]:
    job = uow.jobs.get_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found"
        )
    review = uow.reviews.get_by_job_id(job_id)
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No review found for job '{job_id}'",
        )
    findings = uow.review_findings.list_by_review(review.review_id)
    return {
        "review_id": review.review_id,
        "job_id": review.job_id,
        "project_id": review.project_id,
        "change_name": review.change_name,
        "reviewer": review.reviewer_role,
        "candidate_sha": review.candidate_sha,
        "base_sha": review.base_sha,
        "status": review.status.value,
        "verdict": review.verdict.value if review.verdict else None,
        "summary": review.summary,
        "error_message": review.error_message,
        "created_at": review.created_at.isoformat(),
        "updated_at": review.updated_at.isoformat(),
        "findings": [
            {
                "finding_id": f.finding_id,
                "severity": f.severity.value,
                "location": f.location,
                "violated_requirement": f.violated_requirement,
                "expected_correction": f.expected_correction,
                "created_at": f.created_at.isoformat(),
            }
            for f in findings
        ],
    }


@app.get("/jobs/{job_id}/audit")
def get_job_audit(job_id: str, uow: UowDep) -> dict[str, Any]:
    job = uow.jobs.get_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found"
        )
    audit = uow.audits.get_by_job_id(job_id)
    if not audit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No audit found for job '{job_id}'",
        )
    findings = uow.audit_findings.list_by_audit(audit.audit_id)
    return {
        "audit_id": audit.audit_id,
        "job_id": audit.job_id,
        "project_id": audit.project_id,
        "change_name": audit.change_name,
        "provider": audit.provider,
        "model": audit.model,
        "candidate_sha": audit.candidate_sha,
        "base_sha": audit.base_sha,
        "review_id": audit.review_id,
        "review_verdict": audit.review_verdict.value if audit.review_verdict else None,
        "status": audit.status.value,
        "risk": audit.risk.value if audit.risk else None,
        "summary": redact_secrets(audit.summary or "") if audit.summary else None,
        "error_message": redact_secrets(audit.error_message or "") if audit.error_message else None,
        "created_at": audit.created_at.isoformat(),
        "updated_at": audit.updated_at.isoformat(),
        "findings": [
            {
                "finding_id": f.finding_id,
                "severity": f.severity.value,
                "category": f.category,
                "message": redact_secrets(f.message),
                "file": f.file,
                "location": f.location,
                "created_at": f.created_at.isoformat(),
            }
            for f in findings
        ],
    }


@app.get("/jobs/{job_id}/attempts")
def get_job_attempts(job_id: str, uow: UowDep) -> list[dict[str, Any]]:
    if not uow.jobs.get_by_id(job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found"
        )
    attempts = uow.job_attempts.list_by_job(job_id)
    return [a.model_dump() for a in attempts]


@app.get("/jobs/{job_id}/blockers")
def get_job_blockers(job_id: str, uow: UowDep) -> list[dict[str, Any]]:
    if not uow.jobs.get_by_id(job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found"
        )
    claims = uow.blocker_claims.list_by_job(job_id)
    return [c.model_dump() for c in claims]


@app.get("/jobs/{job_id}/handoffs")
def get_job_handoffs(job_id: str, uow: UowDep) -> list[dict[str, Any]]:
    if not uow.jobs.get_by_id(job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found"
        )
    handoffs = uow.job_handoffs.list_by_job(job_id)
    return [h.model_dump() for h in handoffs]


@app.get("/jobs/{job_id}/manifest")
def get_job_manifest(job_id: str, uow: UowDep) -> dict[str, Any]:
    if not uow.jobs.get_by_id(job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found"
        )
    manifest = uow.candidate_manifests.get_latest_manifest(job_id)
    if not manifest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No candidate manifest found for job '{job_id}'",
        )
    return manifest.model_dump()


@app.get("/jobs/{job_id}/diagnostics")
def get_job_diagnostics(job_id: str, uow: UowDep) -> list[dict[str, Any]]:
    if not uow.jobs.get_by_id(job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found"
        )
    diags = uow.evidence_diagnostics.list_by_job(job_id)
    return [d.model_dump() for d in diags]


def _job_summary(uow: PersistenceUnitOfWork, job: Job) -> dict[str, Any]:
    checks = uow.check_results.list_by_job(job.job_id)
    review = uow.reviews.get_by_job_id(job.job_id)
    audit = uow.audits.get_by_job_id(job.job_id)
    attempts = uow.job_attempts.list_by_job(job.job_id)
    manifest = uow.candidate_manifests.get_latest_manifest(job.job_id)
    diagnostics = uow.evidence_diagnostics.list_by_job(job.job_id)
    return {
        "job_id": job.job_id,
        "project_id": job.project_id,
        "change_name": job.change_name,
        "status": job.status.value,
        "implementer": job.implementer_role,
        "current_executor": job.current_executor,
        "attempt_count": job.attempt_count,
        "reassignment_count": job.reassignment_count,
        "is_mixed_authorship": job.is_mixed_authorship,
        "latest_outcome": job.latest_outcome.value if job.latest_outcome else None,
        "latest_progress": job.latest_progress.value if job.latest_progress else None,
        "continuation_decision": job.continuation_decision.value
        if job.continuation_decision
        else None,
        "escalation_reason": job.escalation_reason,
        "candidate_sha": job.candidate_sha,
        "base_sha": job.base_sha,
        "waiting_provider": job.waiting_provider,
        "capacity_block_reason": job.capacity_block_reason,
        "recovery_blocked_reason": job.recovery_blocked_reason,
        "expected_reset_at": job.expected_reset_at.isoformat() if job.expected_reset_at else None,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "attempts_count": len(attempts),
        "manifest_hash": manifest.manifest_hash if manifest else None,
        "diagnostics_count": len(diagnostics),
        "checks": [
            {
                "check_name": c.check_name,
                "command": c.command,
                "exit_code": c.exit_code,
                "duration_ms": c.duration_ms,
            }
            for c in checks
        ],
        "review": {
            "review_id": review.review_id,
            "reviewer": review.reviewer_role,
            "status": review.status.value,
            "verdict": review.verdict.value if review.verdict else None,
            "summary": review.summary,
        }
        if review
        else None,
        "audit": {
            "audit_id": audit.audit_id,
            "status": audit.status.value,
            "risk": audit.risk.value if audit.risk else None,
            "summary": redact_secrets(audit.summary or "") if audit.summary else None,
        }
        if audit
        else None,
    }


class OrchestrationAdmitRequest(BaseModel):
    project_id: str
    change_name: str
    project_root: str | None = None


class OrchestrationStartRequest(BaseModel):
    project_id: str
    change_name: str
    project_root: str | None = None


class OrchestrationResumeRequest(BaseModel):
    run_id: str
    project_root: str | None = None


@app.post("/api/v1/orchestration/admit", tags=["orchestration"])
def admit_orchestration(
    req: OrchestrationAdmitRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    """Admit a single change into autonomous orchestration after verifying DoR and bindings."""
    service = OrchestrationService(
        uow,
        project_root=req.project_root or ".",
        github_adapter=getattr(app.state, "github_adapter", None),
    )
    result = service.admit_change(req.project_id, req.change_name, project_root=req.project_root)
    return result.model_dump()


@app.post("/api/v1/orchestration/start", tags=["orchestration"])
def start_orchestration(
    req: OrchestrationStartRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    """Start autonomous orchestration for a single READY change."""
    service = OrchestrationService(
        uow,
        project_root=req.project_root or ".",
        github_adapter=getattr(app.state, "github_adapter", None),
    )
    try:
        run = service.start(req.project_id, req.change_name, project_root=req.project_root)
        status_view = service.get_status(run.run_id)
        return status_view.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error during orchestration start: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Orchestration failed: {e}",
        )


@app.post("/api/v1/orchestration/resume", tags=["orchestration"])
def resume_orchestration(
    req: OrchestrationResumeRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    """Resume an existing orchestration run from its persisted checkpoint."""
    service = OrchestrationService(uow, project_root=req.project_root or ".")
    try:
        run = service.resume(req.run_id, project_root=req.project_root)
        status_view = service.get_status(run.run_id)
        return status_view.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error during orchestration resume: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Orchestration resume failed: {e}",
        )


@app.get("/api/v1/orchestration/{run_id}/status", tags=["orchestration"])
def get_orchestration_status(
    run_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    """Get secret-redacted operational status for an orchestration run."""
    service = OrchestrationService(uow)
    try:
        status_view = service.get_status(run_id)
        return status_view.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@app.get("/api/v1/orchestration/runs", tags=["orchestration"])
def list_orchestration_runs(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str | None = None,
    change_name: str | None = None,
    is_active: bool | None = None,
) -> list[dict[str, Any]]:
    """List historical and active orchestration runs."""
    runs = uow.orchestration_runs.list_runs(
        project_id=project_id,
        change_name=change_name,
        is_active=is_active,
    )
    return [r.model_dump() for r in runs]


# -----------------------------------------------------------------------------
# Operations Dashboard Endpoints
# -----------------------------------------------------------------------------


@app.get("/api/v1/dashboard/overview", tags=["dashboard"])
def get_dashboard_overview(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> DashboardOverviewResponse:
    """Get high-level operations dashboard overview."""
    service = OperationsDashboardService(uow)
    return service.get_overview()


@app.get("/api/v1/dashboard/changes/{project_id}/{change_name}", tags=["dashboard"])
def get_dashboard_change_detail(
    project_id: str,
    change_name: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    run_id: str | None = None,
) -> DashboardChangeDetailResponse:
    """Get comprehensive execution detail for a specific change and its latest/selected run."""
    service = OperationsDashboardService(uow)
    try:
        return service.get_change_detail(project_id, change_name, run_id=run_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@app.get("/api/v1/dashboard/runs/{run_id}", tags=["dashboard"])
def get_dashboard_run_detail(
    run_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> DashboardChangeDetailResponse:
    """Get comprehensive execution detail for an exact orchestration run."""
    service = OperationsDashboardService(uow)
    try:
        return service.get_run_detail(run_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@app.get("/api/v1/dashboard/events", tags=["dashboard"])
def get_dashboard_events(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str | None = None,
    change_name: str | None = None,
    run_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TimelineEventDTO]:
    """Get chronological event timeline for the operations dashboard."""
    service = OperationsDashboardService(uow)
    return service.get_events_timeline(
        project_id=project_id,
        change_name=change_name,
        run_id=run_id,
        limit=limit,
    )


# -----------------------------------------------------------------------------
# Preview & Validation Endpoints
# -----------------------------------------------------------------------------


class PreviewBuildRequest(BaseModel):
    project_id: str
    change_name: str
    run_id: str | None = None
    job_id: str | None = None
    candidate_generation: int = 1
    head_sha: str
    base_sha: str
    worktree_path: str = "."
    dockerfile: str = "Dockerfile"
    tag: str | None = None


class PreviewStartRequest(BaseModel):
    preview_id: str
    internal_port: int = 8787
    env_vars: dict[str, str] = Field(default_factory=dict)
    probe_health: bool = True
    health_path: str = "/api/v1/health"


class ValidationSubmitRequest(BaseModel):
    project_id: str
    change_name: str
    head_sha: str
    base_sha: str
    image_digest: str
    verdict: str = "PASS"
    scenario_results: list[dict[str, Any]] = Field(default_factory=list)
    run_id: str | None = None
    preview_id: str | None = None
    candidate_generation: int = 1
    notes: str | None = None
    operator: str = "operator"


@app.post("/api/v1/previews/build", tags=["previews"])
async def build_preview_image(
    req: PreviewBuildRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    project = uow.projects.get_by_id(req.project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{req.project_id}' not found.",
        )

    preview_svc = ContainerPreviewService(uow)
    tag = (
        req.tag
        or f"minime-preview:{req.project_id}-{req.change_name}-gen{req.candidate_generation}"
    )
    try:
        image_digest = await preview_svc.build_image(
            worktree_path=req.worktree_path,
            tag=tag,
            dockerfile=req.dockerfile,
        )
    except Exception as e:
        logger.error(f"Preview build failed: {e}")
        session = PreviewSession(
            project_id=req.project_id,
            change_name=req.change_name,
            run_id=req.run_id,
            job_id=req.job_id,
            candidate_generation=req.candidate_generation,
            head_sha=req.head_sha,
            base_sha=req.base_sha,
            image_digest="",
            status=PreviewStatus.FAILED,
            failure_reason=str(e),
            failure_code="BUILD_FAILED",
        )
        uow.preview_sessions.save(session)
        uow.events.save(
            Event(
                project_id=req.project_id,
                change_id=req.change_name,
                event_type=EventType.PREVIEW_FAILED,
                payload={"error": str(e), "head_sha": req.head_sha},
            )
        )
        uow.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Preview build failed: {e}",
        )

    session = PreviewSession(
        project_id=req.project_id,
        change_name=req.change_name,
        run_id=req.run_id,
        job_id=req.job_id,
        candidate_generation=req.candidate_generation,
        head_sha=req.head_sha,
        base_sha=req.base_sha,
        image_digest=image_digest,
        status=PreviewStatus.BUILDING,
    )
    uow.preview_sessions.save(session)
    uow.events.save(
        Event(
            project_id=req.project_id,
            change_id=req.change_name,
            event_type=EventType.PREVIEW_BUILDING,
            payload={"preview_id": session.preview_id, "image_digest": image_digest, "tag": tag},
        )
    )
    uow.commit()
    return {
        "preview_id": session.preview_id,
        "image_digest": image_digest,
        "tag": tag,
        "status": session.status.value,
    }


@app.post("/api/v1/previews/start", tags=["previews"])
async def start_preview_container(
    req: PreviewStartRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    session = uow.preview_sessions.get_by_id(req.preview_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preview session '{req.preview_id}' not found.",
        )

    preview_svc = ContainerPreviewService(uow)
    image_target = session.image_digest
    try:
        session.status = PreviewStatus.STARTING
        uow.preview_sessions.save(session)
        uow.commit()

        container_id, preview_url, host_port = await preview_svc.start_preview_container(
            preview_session=session,
            image_tag_or_digest=image_target,
            internal_port=req.internal_port,
            env_vars=req.env_vars,
        )
        session.container_id = container_id
        session.preview_url = preview_url
        session.allocated_port = host_port
        session.status = PreviewStatus.PROBING
        uow.preview_sessions.save(session)
        uow.commit()

        if req.probe_health:
            is_healthy = await preview_svc.probe_health(
                preview_url=preview_url,
                health_path=req.health_path,
            )
            if not is_healthy:
                session.status = PreviewStatus.FAILED
                session.failure_reason = "Health probe timed out."
                session.failure_code = "HEALTH_PROBE_FAILED"
                uow.preview_sessions.save(session)
                uow.commit()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Preview container launched but health probe failed.",
                )

        session.status = PreviewStatus.READY
        session.ready_at = utc_now()
        uow.preview_sessions.save(session)
        uow.events.save(
            Event(
                project_id=session.project_id,
                change_id=session.change_name,
                event_type=EventType.PREVIEW_READY,
                payload={
                    "preview_id": session.preview_id,
                    "preview_url": preview_url,
                    "port": host_port,
                },
            )
        )
        uow.commit()
        return {
            "preview_id": session.preview_id,
            "status": session.status.value,
            "preview_url": preview_url,
            "allocated_port": host_port,
            "container_id": container_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        session.status = PreviewStatus.FAILED
        session.failure_reason = str(e)
        session.failure_code = "START_FAILED"
        uow.preview_sessions.save(session)
        uow.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/v1/previews/{preview_id}", tags=["previews"])
def get_preview_session(
    preview_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    session = uow.preview_sessions.get_by_id(preview_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preview session not found.",
        )
    return {
        "preview_id": session.preview_id,
        "project_id": session.project_id,
        "change_name": session.change_name,
        "run_id": session.run_id,
        "candidate_generation": session.candidate_generation,
        "head_sha": session.head_sha,
        "base_sha": session.base_sha,
        "image_digest": session.image_digest,
        "status": session.status.value,
        "preview_url": session.preview_url,
        "allocated_port": session.allocated_port,
        "container_id": session.container_id,
        "container_name": session.container_name,
        "failure_reason": session.failure_reason,
        "failure_code": session.failure_code,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "ready_at": session.ready_at.isoformat() if session.ready_at else None,
        "terminated_at": session.terminated_at.isoformat() if session.terminated_at else None,
    }


@app.get("/api/v1/previews/changes/{project_id}/{change_name}", tags=["previews"])
def get_latest_preview_for_change(
    project_id: str,
    change_name: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    previews = uow.preview_sessions.list_by_change(project_id, change_name)
    if not previews:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No preview session found for change.",
        )
    latest = previews[0]
    return {
        "preview_id": latest.preview_id,
        "status": latest.status.value,
        "head_sha": latest.head_sha,
        "base_sha": latest.base_sha,
        "image_digest": latest.image_digest,
        "preview_url": latest.preview_url,
        "allocated_port": latest.allocated_port,
        "created_at": latest.created_at.isoformat() if latest.created_at else None,
        "ready_at": latest.ready_at.isoformat() if latest.ready_at else None,
    }


@app.post("/api/v1/previews/{preview_id}/teardown", tags=["previews"])
async def teardown_preview_session(
    preview_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    session = uow.preview_sessions.get_by_id(preview_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preview session not found.",
        )
    preview_svc = ContainerPreviewService(uow)
    await preview_svc.teardown_preview(session)
    return {"preview_id": preview_id, "status": PreviewStatus.TERMINATED.value}


@app.post("/api/v1/previews/reconcile", tags=["previews"])
async def reconcile_orphan_previews(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    preview_svc = ContainerPreviewService(uow)
    cleaned = await preview_svc.reconcile_orphan_previews()
    return {"cleaned_containers": cleaned, "count": len(cleaned)}


@app.get("/api/v1/validations/scenarios/{project_id}/{change_name}", tags=["validations"])
def get_validation_scenarios_endpoint(
    project_id: str,
    change_name: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> list[dict[str, Any]]:
    project = uow.projects.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    val_svc = ValidationAuthorityService(uow)
    scenarios = val_svc.get_validation_scenarios(project, change_name)
    return [
        {
            "scenario_id": s.scenario_id,
            "title": s.title,
            "description": s.description,
            "ordered_steps": s.ordered_steps,
            "expected_result": s.expected_result,
            "viewport": s.viewport,
            "required": s.required,
        }
        for s in scenarios
    ]


@app.post("/api/v1/validations/submit", tags=["validations"])
def submit_validation(
    req: ValidationSubmitRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    verdict = ValidationVerdict.PASS if req.verdict.upper() == "PASS" else ValidationVerdict.FAIL
    val_svc = ValidationAuthorityService(uow)
    validation = val_svc.record_validation(
        project_id=req.project_id,
        change_name=req.change_name,
        head_sha=req.head_sha,
        base_sha=req.base_sha,
        image_digest=req.image_digest,
        verdict=verdict,
        scenario_results=req.scenario_results,
        run_id=req.run_id,
        preview_id=req.preview_id,
        generation=req.candidate_generation,
        notes=req.notes,
        operator=req.operator,
    )
    return {
        "validation_id": validation.validation_id,
        "verdict": validation.verdict.value,
        "head_sha": validation.head_sha,
        "base_sha": validation.base_sha,
        "image_digest": validation.image_digest,
        "created_at": validation.created_at.isoformat(),
    }


@app.get("/api/v1/validations/authority/{project_id}/{change_name}", tags=["validations"])
def get_candidate_validation_authority_endpoint(
    project_id: str,
    change_name: str,
    head_sha: str,
    base_sha: str,
    image_digest: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    project = uow.projects.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )
    val_svc = ValidationAuthorityService(uow)
    is_required = val_svc.is_preview_required(project, change_name)
    is_authorized, latest_val, is_stale = val_svc.evaluate_candidate_validation_authority(
        project_id=project_id,
        change_name=change_name,
        head_sha=head_sha,
        base_sha=base_sha,
        image_digest=image_digest,
    )
    return {
        "is_preview_required": is_required,
        "is_authorized": is_authorized,
        "is_stale": is_stale,
        "latest_validation_id": latest_val.validation_id if latest_val else None,
        "latest_verdict": latest_val.verdict.value if latest_val else None,
    }


# -----------------------------------------------------------------------------
# Operator Control Plane Endpoints (015)
# -----------------------------------------------------------------------------


@app.get(
    "/api/v1/runs/{run_id}/actions",
    tags=["control-plane"],
    response_model=list[ActionDescriptor],
)
def discover_actions_endpoint(
    run_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> list[ActionDescriptor]:
    """Discover available operator actions for a run with enabled/disabled explanations."""
    run = uow.orchestration_runs.get_by_id(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Orchestration run '{run_id}' not found.",
        )
    cp_service = ControlPlaneService(uow)
    return cp_service.get_available_actions(run_id)


@app.get(
    "/api/v1/control-plane/actions/available",
    tags=["control-plane"],
    response_model=list[ActionDescriptor],
)
def discover_control_plane_actions_endpoint(
    run_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> list[ActionDescriptor]:
    """Stable control-plane discovery route for presentation clients."""
    return discover_actions_endpoint(run_id, uow)


@app.post(
    "/api/v1/runs/{run_id}/actions/{action_type}",
    tags=["control-plane"],
    response_model=OperatorActionResult,
)
def execute_action_endpoint(
    run_id: str,
    action_type: OperatorActionType,
    request_body: OperatorActionRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> OperatorActionResult:
    """Execute a governed operator action with optimistic concurrency and idempotency."""
    if request_body.run_id != run_id or request_body.action_type != action_type:
        request_body = request_body.model_copy(
            update={"run_id": run_id, "action_type": action_type}
        )
    cp_service = ControlPlaneService(uow)
    return cp_service.execute_action(request_body)


@app.post(
    "/api/v1/runs/{run_id}/actions",
    tags=["control-plane"],
    response_model=OperatorActionResult,
)
def execute_action_generic_endpoint(
    run_id: str,
    request_body: OperatorActionRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> OperatorActionResult:
    """Execute a governed operator action."""
    if request_body.run_id != run_id:
        request_body = request_body.model_copy(update={"run_id": run_id})
    cp_service = ControlPlaneService(uow)
    return cp_service.execute_action(request_body)


@app.post(
    "/api/v1/control-plane/actions/execute",
    tags=["control-plane"],
    response_model=OperatorActionResult,
)
def execute_control_plane_action_endpoint(
    request_body: OperatorActionRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> OperatorActionResult:
    """Stable mutation route for presentation clients."""
    return execute_action_generic_endpoint(request_body.run_id, request_body, uow)


@app.get(
    "/api/v1/runs/{run_id}/actions/history",
    tags=["control-plane"],
    response_model=list[OperatorActionRecord],
)
def get_action_history_endpoint(
    run_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    limit: int = 50,
) -> list[OperatorActionRecord]:
    """Fetch audit trail of operator actions executed for a run."""
    run = uow.orchestration_runs.get_by_id(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Orchestration run '{run_id}' not found.",
        )
    cp_service = ControlPlaneService(uow)
    return cp_service.list_action_history(run_id, limit=limit)


# -----------------------------------------------------------------------------
# Queue and Scheduler Endpoints
# -----------------------------------------------------------------------------


@app.get(
    "/api/v1/queue",
    tags=["queue"],
    response_model=list[WorkQueueItem],
)
def list_queue_items_endpoint(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str | None = None,
    ready_only: bool = False,
) -> list[WorkQueueItem]:
    """List candidate work items in the scheduler queue."""
    scheduler = SchedulerService(uow)
    if ready_only:
        items = uow.work_queue.list_ready(project_id)
    else:
        items = uow.work_queue.list_all(project_id)
    return scheduler.rank_candidates(items)


@app.get(
    "/api/v1/queue/{change_name}/explain",
    tags=["queue"],
    response_model=QueueExplainReport,
)
def explain_queue_item_endpoint(
    change_name: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str = "mini-me",
) -> QueueExplainReport:
    """Get detailed explainability report for a work item's priority and blockers."""
    scheduler = SchedulerService(uow)
    try:
        return scheduler.explain_item_priority(project_id, change_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@app.get(
    "/api/v1/scheduler/status",
    tags=["scheduler"],
    response_model=SchedulerStatusView,
)
def get_scheduler_status_endpoint(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str | None = None,
) -> SchedulerStatusView:
    """Get operational status view of the autonomous scheduler and queue."""
    scheduler = SchedulerService(uow)
    return scheduler.get_status(project_id)


@app.post(
    "/api/v1/scheduler/tick",
    tags=["scheduler"],
    response_model=list[SchedulerDecisionRecord],
)
def trigger_scheduler_tick_endpoint(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str | None = None,
) -> list[SchedulerDecisionRecord]:
    """Trigger a single scheduler evaluation and admission tick."""
    scheduler = SchedulerService(uow)
    return scheduler.tick(project_id)


# -----------------------------------------------------------------------------
# Static UI Mounting & Index
# -----------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent.parent / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
else:
    logger.warning("Dashboard static directory '%s' does not exist.", STATIC_DIR)


@app.get("/", tags=["dashboard-ui"], response_model=None)
@app.get("/dashboard", tags=["dashboard-ui"], response_model=None)
def get_dashboard_page() -> Response:
    """Serve the operations dashboard single-page web interface."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    logger.error("Dashboard index.html not found at '%s'.", index_file)
    return HTMLResponse(
        "<!DOCTYPE html><html><head><title>mini me dashboard</title></head><body>"
        "<h1>mini me operations dashboard</h1>"
        "<p>Dashboard UI static assets not found. Verify package installation or static asset directory.</p>"
        "</body></html>",
        status_code=404,
    )
