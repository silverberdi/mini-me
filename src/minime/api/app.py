"""FastAPI application for mini me daemon."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Generator

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from minime.adapters.openspec import OpenSpecAdapter
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import Change, Job, JobLog, Project, ProviderHealth, SchedulerStatus
from minime.logging import redact_secrets
from minime.services.budget_service import BudgetService
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
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
from minime.services.status_service import StatusService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: reconcile active jobs and clean abandoned locks
    sess = db_manager.sessionmaker()
    try:
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
        uow, project_root=req.project_root or ".", github_adapter=getattr(app.state, "github_adapter", None)
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
        uow, project_root=req.project_root or ".", github_adapter=getattr(app.state, "github_adapter", None)
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
    return service.get_change_detail(project_id, change_name, run_id=run_id)


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
    limit: int = 100,
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
# Static UI Mounting & Index
# -----------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent.parent / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", tags=["dashboard-ui"], response_model=None)
@app.get("/dashboard", tags=["dashboard-ui"], response_model=None)
def get_dashboard_page() -> Response:
    """Serve the operations dashboard single-page web interface."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>mini me dashboard not found</h1>", status_code=404)


