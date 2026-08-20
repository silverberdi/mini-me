"""FastAPI application for mini me daemon."""

from __future__ import annotations

from typing import Annotated, Any, Generator

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from minime.adapters.openspec import OpenSpecAdapter
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.domain.models import Change, Job, JobLog, Project
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.project_service import ProjectService
from minime.services.readiness_service import ReadinessService
from minime.services.status_service import StatusService

app = FastAPI(
    title="mini me API",
    version="0.1.0",
    description="Control plane and operational status API for mini me.",
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")
    return _job_summary(uow, job)


@app.get("/jobs/{job_id}/logs")
def get_job_logs(job_id: str, uow: UowDep) -> list[JobLog]:
    if not uow.jobs.get_by_id(job_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")
    return uow.job_logs.list_by_job(job_id)


def _job_summary(uow: PostgresPersistenceUnitOfWork, job: Job) -> dict[str, Any]:
    checks = uow.check_results.list_by_job(job.job_id)
    return {
        "job_id": job.job_id,
        "project_id": job.project_id,
        "change_name": job.change_name,
        "status": job.status.value,
        "implementer": job.implementer_role,
        "candidate_sha": job.candidate_sha,
        "base_sha": job.base_sha,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "checks": [
            {
                "check_name": c.check_name,
                "command": c.command,
                "exit_code": c.exit_code,
                "duration_ms": c.duration_ms,
            }
            for c in checks
        ],
    }
