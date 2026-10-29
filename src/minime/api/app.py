"""FastAPI application for mini me daemon."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Generator

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from minime.config import load_config
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.domain.enums import (
    AuthEventType,
    OperatorActionType,
    OperatorAuthDecision,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    ActionDescriptor,
    AuthorizedOperator,
    AuthStatusDTO,
    Change,
    ContextDiscoveryReport,
    EfficiencyTelemetryView,
    Job,
    JobLog,
    OperatorActionRecord,
    OperatorActionRequest,
    OperatorActionResult,
    OperatorIdentityDTO,
    ProjectConfigurationInput,
    ProjectConfigurationPatch,
    ProviderEfficiencyMetrics,
    ProviderHealth,
    SchedulerStatus,
)
from minime.logging import redact_secrets
from minime.services.auth_service import (
    AuthorizedOperatorService,
    GoogleOidcService,
    SessionManager,
    generate_state_token,
)
from minime.services.budget_service import BudgetService
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
from minime.services.context_discovery_service import ContextDiscoveryService
from minime.services.current_check_batch import validate_current_checks_batch
from minime.services.greenfield_bootstrap import (
    GreenfieldBootstrapCoordinator,
    GreenfieldBootstrapError,
)
from minime.services.legacy_unavailable import unavailable_payload
from minime.services.project_catalog_service import ProjectCatalogService
from minime.services.project_connection_service import ProjectConnectionService
from minime.services.project_service import ProjectService
from minime.services.provider_health_service import ProviderHealthService
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
        # F1 deliberately has no autonomous recovery or execution on API startup.

        # Seed authorized operators from configuration or environment
        try:
            config = load_config()
            op_svc = AuthorizedOperatorService(uow)
            if config.auth.authorized_operators:
                for op_data in config.auth.authorized_operators:
                    if isinstance(op_data, dict) and "email" in op_data:
                        op_svc.seed_operator(
                            email=op_data["email"],
                            display_name=op_data.get("display_name"),
                            google_sub=op_data.get("google_sub"),
                            is_active=op_data.get("is_active", True),
                        )
                    elif isinstance(op_data, str) and op_data.strip():
                        op_svc.seed_operator(
                            email=op_data.strip(),
                            display_name="Authorized Operator",
                            is_active=True,
                        )

            env_operators = (
                os.environ.get(config.auth.authorized_operators_env)
                or os.environ.get("MINIME_AUTHORIZED_OPERATORS")
                or os.environ.get("MINIME_AUTHORIZED_OPERATOR_EMAIL")
            )
            if env_operators:
                import json

                try:
                    parsed = json.loads(env_operators)
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, str) and item.strip():
                                op_svc.seed_operator(
                                    email=item.strip(),
                                    display_name="Authorized Operator",
                                    is_active=True,
                                )
                            elif isinstance(item, dict) and "email" in item:
                                op_svc.seed_operator(
                                    email=item["email"],
                                    display_name=item.get("display_name", "Authorized Operator"),
                                    google_sub=item.get("google_sub"),
                                    is_active=item.get("is_active", True),
                                )
                    elif isinstance(parsed, dict) and "email" in parsed:
                        op_svc.seed_operator(
                            email=parsed["email"],
                            display_name=parsed.get("display_name", "Authorized Operator"),
                            google_sub=parsed.get("google_sub"),
                            is_active=parsed.get("is_active", True),
                        )
                except Exception:
                    for email in env_operators.split(","):
                        email = email.strip()
                        if email:
                            op_svc.seed_operator(
                                email=email,
                                display_name="Authorized Operator",
                                is_active=True,
                            )
        except Exception as exc:
            logger.warning(f"Error initializing authorized operators: {exc}")
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


@app.exception_handler(RequestValidationError)
async def redact_request_validation_details(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Do not echo request input (which can contain credential material) in 422 bodies."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": [
                {"type": error.get("type"), "loc": error.get("loc"), "msg": error.get("msg")}
                for error in exc.errors()
            ]
        },
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


def _run_greenfield_bootstrap_in_session(
    configuration: ProjectConfigurationInput,
    archive: bytes,
    operator_email: str,
) -> dict[str, Any]:
    """Run blocking bootstrap work with a session owned by the worker thread."""
    session = db_manager.sessionmaker()
    try:
        uow = PostgresPersistenceUnitOfWork(session)
        return GreenfieldBootstrapCoordinator(
            uow,
            trusted_managed_root=load_config().paths.repos_root,
        ).bootstrap(configuration, archive, operator_email=operator_email)
    finally:
        session.close()


def _run_incremental_context_in_session(project_id: str, archive: bytes) -> dict[str, Any]:
    """Run blocking context publication with a session owned by the worker thread."""
    session = db_manager.sessionmaker()
    try:
        uow = PostgresPersistenceUnitOfWork(session)
        return GreenfieldBootstrapCoordinator(
            uow,
            trusted_managed_root=load_config().paths.repos_root,
        ).add_context(project_id, archive)
    finally:
        session.close()


def get_context_service(uow: UowDep) -> ContextDiscoveryService:
    return ContextDiscoveryService(uow)


ContextServiceDep = Annotated[ContextDiscoveryService, Depends(get_context_service)]



PUBLIC_EXEMPT_PATHS = {
    "/health",
    "/",
    "/dashboard",
    "/trabajo",
    "/trabajo-actual",
    "/proyectos",
    "/backlog",
    "/sw.js",
    "/manifest.webmanifest",
    "/favicon.ico",
    "/api/v1/auth/google/login",
    "/api/v1/auth/google/callback",
    "/api/v1/auth/logout",
    "/api/v1/auth/me",
}
PUBLIC_EXEMPT_PREFIXES = ("/static/",)


def extract_token_from_request(request: Request) -> str | None:
    cookie_token = request.cookies.get("minime_session")
    if cookie_token and len(cookie_token.strip()) >= 16:
        return cookie_token.strip()
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and len(auth_header[7:].strip()) >= 16:
        return auth_header[7:].strip()
    return None


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    config = load_config()
    auth_enabled_env = os.environ.get("MINIME_AUTH_ENABLED")
    auth_enabled = (
        auth_enabled_env.lower() in ("true", "1")
        if auth_enabled_env is not None
        else config.auth.enabled
    )
    if not auth_enabled:
        unavailable = _legacy_operation_for_path(request.url.path)
        if unavailable is not None:
            operation, phase = unavailable
            return JSONResponse(status_code=status.HTTP_410_GONE, content=unavailable_payload(operation, phase))
        return await call_next(request)

    path = request.url.path
    if (
        path in PUBLIC_EXEMPT_PATHS
        or any(path.startswith(prefix) for prefix in PUBLIC_EXEMPT_PREFIXES)
        or request.method == "OPTIONS"
    ):
        return await call_next(request)

    token = extract_token_from_request(request)
    if not token:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Authentication required", "code": "AUTH_REQUIRED"},
        )

    sess = None
    try:
        uow_override = app.dependency_overrides.get(get_uow)
        if uow_override:
            uow = uow_override()
        else:
            sess = db_manager.sessionmaker()
            uow = PostgresPersistenceUnitOfWork(sess)

        session_mgr = SessionManager(uow)
        operator_svc = AuthorizedOperatorService(uow)

        auth_session = session_mgr.validate_session_pure(token)
        if not auth_session:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Session expired or invalid", "code": "SESSION_EXPIRED"},
            )

        decision, operator = operator_svc.evaluate_operator_pure(
            auth_session.operator_email, auth_session.google_sub
        )
        if decision == OperatorAuthDecision.IDENTITY_NOT_ALLOWLISTED:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": "Operator identity is not allowlisted",
                    "code": "IDENTITY_NOT_ALLOWLISTED",
                },
            )
        if decision == OperatorAuthDecision.IDENTITY_DISABLED:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": "Operator identity is disabled",
                    "code": "IDENTITY_DISABLED",
                },
            )

        request.state.operator = operator
        request.state.session = auth_session
    except Exception as exc:
        logger.error(f"Error evaluating request authentication: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Authentication evaluation failed"},
        )
    finally:
        if sess:
            sess.close()

    unavailable = _legacy_operation_for_path(request.url.path)
    if unavailable is not None:
        operation, phase = unavailable
        return JSONResponse(status_code=status.HTTP_410_GONE, content=unavailable_payload(operation, phase))
    return await call_next(request)


LEGACY_UNAVAILABLE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/scheduler", "F3"),
    ("/api/v1/scheduler", "F3"),
    ("/api/v1/queue", "F3"),
    ("/api/v1/orchestration", "F3"),
    ("/api/v1/dashboard", "F5"),
)

READ_ONLY_ORCHESTRATION_PATHS = {
    "/api/v1/orchestration/runs",
}


def _legacy_operation_for_path(path: str) -> tuple[str, str] | None:
    """Map only retired mutation/execution routes to an explicit F1 denial."""
    if path in READ_ONLY_ORCHESTRATION_PATHS:
        return None
    if (path.startswith("/api/") and "/backlog" in path) or path.endswith("/discover") or "/readiness" in path:
        return ("legacy_intake_or_readiness", "F2")
    if path.startswith("/projects/") and path.endswith("/jobs"):
        return ("legacy_job_execution", "F3")
    if path.startswith("/jobs/"):
        return ("legacy_job_execution", "F3")
    if path.startswith("/api/v1/projects/") and (
        path.endswith("/context/discover") or "/backlog" in path
    ):
        return ("legacy_intake_or_readiness", "F2")
    for prefix, phase in LEGACY_UNAVAILABLE_PREFIXES:
        if path.startswith(prefix):
            return ("legacy_operation", phase)
    return None


def get_current_operator(
    request: Request,
    uow: UowDep,
) -> AuthorizedOperator:
    if hasattr(request.state, "operator") and request.state.operator:
        return request.state.operator

    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    session_mgr = SessionManager(uow)
    operator_svc = AuthorizedOperatorService(uow)

    auth_session = session_mgr.validate_session_pure(token)
    if not auth_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )

    decision, operator = operator_svc.evaluate_operator_pure(
        auth_session.operator_email, auth_session.google_sub
    )
    if decision == OperatorAuthDecision.IDENTITY_NOT_ALLOWLISTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator identity is not allowlisted",
        )
    if decision == OperatorAuthDecision.IDENTITY_DISABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator identity is disabled",
        )
    return operator


AuthenticatedOperatorDep = Annotated[AuthorizedOperator, Depends(get_current_operator)]


@app.get("/api/v1/catalogs/providers", tags=["catalogs"])
def project_provider_catalog(_operator: AuthenticatedOperatorDep) -> list[dict[str, Any]]:
    """Return provider metadata only; project connections and secrets are never included."""
    return ProjectCatalogService().provider_catalog()


@app.get("/api/v1/catalogs/agents", tags=["catalogs"])
async def project_agent_catalog(
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Expose locally configured, read-only discovered agent capabilities."""
    project_root = (
        ProjectService(uow).verified_managed_workspace_root(project_id) if project_id else None
    )
    if project_id and project_root is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project workspace binding is unavailable or does not match its repository identity",
        )
    return await ProjectCatalogService().agent_catalog(project_root)


@app.get("/api/v1/projects", tags=["projects"])
def list_project_configurations(_operator: AuthenticatedOperatorDep, uow: UowDep) -> list[dict[str, Any]]:
    service = ProjectService(uow)
    return [service.public_project_payload(project) for project in service.list_projects()]


@app.post("/api/v1/projects", status_code=status.HTTP_201_CREATED, tags=["projects"])
async def create_project_configuration(
    configuration: ProjectConfigurationInput,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Create a configuration-only Brownfield registration; Greenfield needs ZIP bootstrap."""
    try:
        await ProjectCatalogService().validate_project_profiles(
            configuration.agent_profiles
        )
        service = ProjectService(uow)
        return service.public_project_payload(service.create_configured_project(configuration))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/v1/projects/greenfield/bootstrap", status_code=status.HTTP_202_ACCEPTED, tags=["projects"])
async def bootstrap_greenfield_project(
    operator: AuthenticatedOperatorDep,
    uow: UowDep,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Bootstrap a Greenfield project through its first human-reviewed PR.

    The archive is supplied as base64 in ``context_zip_base64`` so the API keeps
    its existing JSON-only dependency surface; the ZIP is still validated before
    any project or repository mutation.
    """

    import base64

    try:
        configuration = ProjectConfigurationInput.model_validate(payload.get("configuration"))
        if configuration.project_type.value != "GREENFIELD":
            raise ValueError("project_type must be GREENFIELD")
        encoded_archive = payload.get("context_zip_base64")
        if not isinstance(encoded_archive, str):
            raise ValueError("context_zip_base64 is required")
        archive = base64.b64decode(encoded_archive, validate=True)
        await ProjectCatalogService().validate_project_profiles(configuration.agent_profiles)
        result = await run_in_threadpool(
            _run_greenfield_bootstrap_in_session,
            configuration,
            archive,
            operator.email if operator else "operator",
        )
        return result
    except (ValueError, GreenfieldBootstrapError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.patch("/api/v1/projects/{project_id}", tags=["projects"])
async def update_project_configuration(
    project_id: str,
    patch: ProjectConfigurationPatch,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    try:
        service = ProjectService(uow)
        if service.get_project(project_id) is None:
            raise ValueError(f"Project '{project_id}' not found")
        if patch.agent_profiles is not None:
            workspace_root = service.verified_managed_workspace_root(project_id)
            binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
            if binding is not None and workspace_root is None:
                raise ValueError(
                    "Project agent profiles cannot be changed while its managed workspace identity is invalid"
                )
            await ProjectCatalogService().validate_project_profiles(
                patch.agent_profiles, project_root=workspace_root
            )
        return service.public_project_payload(service.update_configuration(project_id, patch))
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_404_NOT_FOUND if message.endswith("not found") else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=message) from exc


@app.get("/api/v1/projects/{project_id}/onboarding", tags=["projects"])
def get_project_onboarding_state(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    project = ProjectService(uow).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectService.public_onboarding_state(project)


@app.post("/api/v1/projects/{project_id}/onboarding/observe-merge", tags=["projects"])
def observe_project_bootstrap_merge(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Read the exact recorded bootstrap PR and persist PREPARED only after merge proof."""
    try:
        return ProjectService(uow).observe_bootstrap_merge(project_id)
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_404_NOT_FOUND if message.endswith("not found") else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=message) from exc


@app.post("/api/v1/projects/{project_id}/context", status_code=status.HTTP_202_ACCEPTED, tags=["projects"])
async def add_project_context(
    project_id: str,
    payload: dict[str, Any],
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Publish incremental context on a new PR; approved main remains authoritative."""
    import base64

    try:
        encoded_archive = payload.get("context_zip_base64")
        if not isinstance(encoded_archive, str):
            raise ValueError("context_zip_base64 is required")
        archive = base64.b64decode(encoded_archive, validate=True)
        return await run_in_threadpool(_run_incremental_context_in_session, project_id, archive)
    except (ValueError, GreenfieldBootstrapError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/context/observe-merge", tags=["projects"])
def observe_project_context_merge(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Advance effective context only after exact incremental PR merge proof."""
    try:
        return ProjectService(uow).observe_context_merge(project_id)
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_404_NOT_FOUND if message.endswith("not found") else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=message) from exc


@app.post("/api/v1/projects/{project_id}/pause", tags=["projects"])
def pause_project(project_id: str, _operator: AuthenticatedOperatorDep, uow: UowDep) -> dict[str, Any]:
    try:
        service = ProjectService(uow)
        return service.public_project_payload(service.set_lifecycle(project_id, active=False))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/activate", tags=["projects"])
def activate_project(project_id: str, _operator: AuthenticatedOperatorDep, uow: UowDep) -> dict[str, Any]:
    try:
        service = ProjectService(uow)
        return service.public_project_payload(service.set_lifecycle(project_id, active=True))
    except ValueError as exc:
        message = str(exc)
        code = status.HTTP_404_NOT_FOUND if message.endswith("not found") else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=message) from exc


@app.post("/api/v1/projects/{project_id}/connections/verify", tags=["projects"])
def verify_project_connections(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Read-only verification of repository identity and project-scoped App grants."""
    project = uow.projects.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {
        "project_id": project_id,
        "connections": ProjectConnectionService().verify(project),
    }


class ProjectRequestRunPayload(BaseModel):
    operator_ack: bool = False
    operator_response: str | None = None
    operator_clarification: str | None = None
    thinker_provider: str | None = None
    implementer_provider: str | None = None
    reviewer_provider: str | None = None


@app.get("/api/v1/projects/{project_id}/requests", tags=["requests"])
def list_project_requests(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """List eligible remote requests for a project in FIFO order."""
    from minime.adapters.github import GitHubAdapter
    from minime.services.remote_request_intake import RemoteRequestIntakeService

    project = uow.projects.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    intake = RemoteRequestIntakeService(github_adapter=GitHubAdapter(), uow=uow)
    eligible = intake.get_eligible_requests(project.repository)
    return {
        "project_id": project_id,
        "repository": project.repository,
        "eligible_requests": eligible,
    }


@app.post("/api/v1/projects/{project_id}/requests/run", tags=["requests"])
async def run_project_request(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    payload: ProjectRequestRunPayload | None = None,
) -> dict[str, Any]:
    """Execute or continue the active remote request for a project."""
    from minime.adapters.github import GitHubAdapter
    from minime.services.agent_runner import CliAgentRunner
    from minime.services.budget_service import BudgetService
    from minime.services.capacity_lifecycle_service import CapacityLifecycleService
    from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
    from minime.services.worktree_manager import WorktreeManager

    project = uow.projects.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    body = payload or ProjectRequestRunPayload()
    binding = None
    if hasattr(uow, "project_managed_repository_bindings"):
        binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
    if binding is None or not binding.managed_repository_root:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Verified managed repository binding is required")
    repo_root = Path(binding.managed_repository_root)

    wt_manager = WorktreeManager(project_root=repo_root, uow=uow)
    github = GitHubAdapter()
    try:
        agent_runner = CliAgentRunner.for_project_profiles(
            project.agent_profiles,
            capacity_service=CapacityLifecycleService(uow),
            budget_service=BudgetService(uow),
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Verified F2 agent profiles unavailable: {exc}") from exc

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=github,
        worktree_manager=wt_manager,
        agent_runner=agent_runner,
        semantic_pr_agent=True,
    )
    clarification = body.operator_clarification or body.operator_response
    res = await coordinator.execute_project_request(
        project_id,
        operator_ack=body.operator_ack,
        operator_clarification=clarification,
        thinker_provider=agent_runner.provider_for_role("thinker"),
        implementer_provider=agent_runner.provider_for_role("implementer"),
        reviewer_provider=agent_runner.provider_for_role("reviewer"),
    )
    return {
        "status": res.status,
        "run_id": res.run_id,
        "current_stage": res.current_stage.value if res.current_stage else None,
        "message": res.message,
        "pr1_url": res.pr1_url,
        "pr2_url": res.pr2_url,
        "human_payload": res.human_payload,
    }


@app.post("/api/v1/projects/{project_id}/requests/ack", tags=["requests"])
async def ack_project_request(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Acknowledge («Estoy enterado») high-complexity PR merge and continue."""
    from minime.adapters.github import GitHubAdapter
    from minime.services.agent_runner import CliAgentRunner
    from minime.services.budget_service import BudgetService
    from minime.services.capacity_lifecycle_service import CapacityLifecycleService
    from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
    from minime.services.worktree_manager import WorktreeManager

    project = uow.projects.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
    if binding is None or not binding.managed_repository_root:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Verified managed repository binding is required")
    wt_manager = WorktreeManager(project_root=Path(binding.managed_repository_root), uow=uow)
    github = GitHubAdapter()
    try:
        agent_runner = CliAgentRunner.for_project_profiles(
            project.agent_profiles,
            capacity_service=CapacityLifecycleService(uow),
            budget_service=BudgetService(uow),
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Verified F2 agent profiles unavailable: {exc}") from exc

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=github,
        worktree_manager=wt_manager,
        agent_runner=agent_runner,
        semantic_pr_agent=True,
    )
    res = await coordinator.execute_project_request(
        project_id,
        operator_ack=True,
    )
    return {
        "status": res.status,
        "run_id": res.run_id,
        "current_stage": res.current_stage.value if res.current_stage else None,
        "message": res.message,
        "pr1_url": res.pr1_url,
        "pr2_url": res.pr2_url,
        "human_payload": res.human_payload,
    }


class JobRunRequest(BaseModel):
    change_name: str
    project_root: str = "."


@app.api_route("/health", methods=["GET", "HEAD"])
def get_health() -> dict[str, Any]:
    healthy, message = db_manager.check_health()
    return {
        "status": "healthy" if healthy else "unhealthy",
        "observed_at": datetime.now(UTC).isoformat(),
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
    policy = uow.budget_policies.get_by_project_id(project_id) if project_id else None
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
    policy = uow.budget_policies.get_by_project_id(project_id) if project_id else None
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
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> list[dict[str, Any]]:
    service = ProjectService(uow)
    return [service.public_project_payload(project) for project in service.list_projects()]


@app.post("/projects", status_code=status.HTTP_201_CREATED)
def register_project() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_project_registration", "F2"),
    )


@app.get("/projects/{project_id}")
def get_project(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    service = ProjectService(uow)
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    return ProjectService.public_project_payload(project)


@app.get("/api/v1/projects/{project_id}", tags=["projects"])
def get_project_configuration(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    project = ProjectService(uow).get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectService.public_project_payload(project)


@app.patch("/projects/{project_id}")
def update_project_endpoint(
    project_id: str,
    uow: UowDep,
) -> None:
    del project_id, uow
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_project_update", "F2"),
    )


# -----------------------------------------------------------------------------
# 021 Project Onboarding and Backlog Intake Endpoints
# -----------------------------------------------------------------------------


@app.post("/api/v1/projects/onboard", tags=["projects"])
def onboard_project_endpoint() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_project_onboarding", "F2"),
    )


@app.get("/api/v1/projects/{project_id}/context", tags=["projects"])
def get_project_context_endpoint(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    context_service: ContextServiceDep,
) -> ContextDiscoveryReport:
    """Get categorized context report (discovered facts, inferred structure, missing context)."""
    if uow.projects.get_by_id(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        return context_service.discover_context_pure(project_id)
    except ValueError as e:
        code = status.HTTP_404_NOT_FOUND if str(e).endswith("not found.") else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=str(e)) from e


@app.post("/api/v1/projects/{project_id}/context/discover", tags=["projects"])
def discover_project_context_endpoint(project_id: str) -> None:
    del project_id
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_context_discovery", "F2"),
    )


@app.get("/api/v1/projects/{project_id}/backlog", tags=["backlog"])
def list_backlog_items_endpoint(
    project_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """The local backlog projection was retired; F2 owns its replacement."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_intake_or_readiness", "F2"),
    )


@app.post(
    "/api/v1/projects/{project_id}/backlog", status_code=status.HTTP_201_CREATED, tags=["backlog"]
)
def create_backlog_item_endpoint(
    project_id: str,
    request: Request,
) -> dict[str, Any]:
    """The local backlog projection was retired; F2 owns its replacement."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_intake_or_readiness", "F2"),
    )


@app.get("/api/v1/projects/{project_id}/backlog/{item_key}", tags=["backlog"])
def get_backlog_item_endpoint(
    project_id: str,
    item_key: str,
) -> dict[str, Any]:
    """The local backlog projection was retired; F2 owns its replacement."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_intake_or_readiness", "F2"),
    )


@app.patch("/api/v1/projects/{project_id}/backlog/{item_key}", tags=["backlog"])
def update_backlog_item_endpoint(
    project_id: str,
    item_key: str,
    request: Request,
) -> dict[str, Any]:
    """The local backlog projection was retired; F2 owns its replacement."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_intake_or_readiness", "F2"),
    )


@app.post("/api/v1/projects/{project_id}/backlog/{item_key}/prepare", tags=["backlog"])
def prepare_backlog_item_endpoint(
    project_id: str,
    item_key: str,
    request: Request,
) -> dict[str, Any]:
    """Prepare canonical execution artifacts (GitHub Issue, Project Item, OpenSpec change)."""
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_intake", "F2"))


@app.post("/api/v1/projects/{project_id}/backlog/{item_key}/answer", tags=["backlog"])
def answer_backlog_item_question_endpoint(
    project_id: str,
    item_key: str,
    request: Request,
) -> dict[str, Any]:
    """The local backlog projection was retired; F2 owns its replacement."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_intake_or_readiness", "F2"),
    )


@app.post("/api/v1/projects/{project_id}/backlog/{item_key}/start", tags=["backlog"])
def start_backlog_item_endpoint(
    project_id: str,
    item_key: str,
    request: Request,
) -> dict[str, Any]:
    """The local backlog projection was retired; F2 owns its replacement."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_intake_or_readiness", "F2"),
    )


@app.delete(
    "/api/v1/projects/{project_id}/backlog/{item_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["backlog"],
)
def delete_backlog_item_endpoint(
    project_id: str,
    item_key: str,
    request: Request,
) -> Response:
    """The local backlog projection was retired; F2 owns its replacement."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_intake_or_readiness", "F2"),
    )


@app.get("/projects/{project_id}/changes")
def list_project_changes(
    project_id: str,
    uow: UowDep,
) -> list[Change]:
    changes = uow.changes.list_by_project(project_id)
    return changes


@app.post("/projects/{project_id}/discover")
def discover_project_changes(project_id: str) -> None:
    del project_id
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_context_discovery", "F2"),
    )


@app.get("/projects/{project_id}/changes/{change_name}/readiness")
def evaluate_readiness(
    project_id: str,
    change_name: str,
    project_root: str,
    uow: UowDep,
    current_active_change: str | None = None,
) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_readiness", "F2"))


@app.post("/projects/{project_id}/jobs", status_code=status.HTTP_202_ACCEPTED)
async def run_project_job(
    project_id: str,
    req: JobRunRequest,
    uow: UowDep,
) -> Job:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_job_execution", "F3"))


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
    matching_runs = uow.orchestration_runs.list_runs(
        project_id=job.project_id, change_name=job.change_name
    )
    run = next((item for item in matching_runs if item.active_job_id == job.job_id), None)
    project = uow.projects.get_by_id(job.project_id)
    configured_checks = [
        check
        for check in (project.checks if project else [])
        if isinstance(check, dict) and check.get("name")
    ]
    current_check_batch: dict[str, Any]
    if not run or not project:
        current_check_batch = {
            "status": "UNKNOWN",
            "candidate_sha": job.candidate_sha,
            "generation": run.current_generation if run else None,
            "check_result_ids": [],
            "reason": "Run or project authority is unavailable.",
        }
    elif not configured_checks:
        current_check_batch = {
            "status": "NOT_CONFIGURED",
            "candidate_sha": job.candidate_sha,
            "generation": run.current_generation,
            "check_result_ids": [],
            "reason": "No deterministic checks are configured for this project.",
        }
    else:
        valid, reason, batch = validate_current_checks_batch(
            check_results=checks,
            job=job,
            run=run,
            project=project,
            require_configured_checks=True,
        )
        current_check_batch = {
            "status": "PASSED" if valid else "BLOCKED",
            "candidate_sha": job.candidate_sha,
            "generation": run.current_generation,
            "check_result_ids": [item.result_id for item in batch],
            "reason": reason,
        }
    code_review = uow.reviews.get_by_job_stage(job.job_id, "CODE_REVIEW")
    code_review_authorization = (
        uow.operator_actions.get_by_request_id(code_review.budget_authorization_id)
        if code_review and code_review.budget_authorization_id
        else None
    )
    code_review_action_key = (
        f"deepseek-code-review:{code_review.budget_authorization_id}"
        if code_review and code_review.budget_authorization_id
        else None
    )
    code_review_dispatch = (
        uow.orchestration_external_actions.get_by_action_key(code_review_action_key)
        if code_review_action_key
        else None
    )
    code_review_attempts = (
        uow.external_action_attempts.list_by_action_key(code_review_action_key)
        if code_review_action_key
        else []
    )
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
                "result_id": c.result_id,
                "check_name": c.check_name,
                "command": c.command,
                "exit_code": c.exit_code,
                "duration_ms": c.duration_ms,
                "candidate_sha": c.candidate_sha,
                "candidate_generation": c.candidate_generation,
            }
            for c in checks
        ],
        "current_check_batch": current_check_batch,
        "code_review_checkpoint": {
            "review_id": code_review.review_id if code_review else None,
            "status": code_review.status.value if code_review else "NOT_STARTED",
            "verdict": code_review.verdict.value if code_review and code_review.verdict else None,
            "candidate_sha": code_review.candidate_sha if code_review else None,
            "base_sha": code_review.base_sha if code_review else None,
            "generation": code_review.candidate_generation if code_review else None,
            "manifest_id": code_review.manifest_id if code_review else None,
            "manifest_hash": code_review.manifest_hash if code_review else None,
            "authorization_id": code_review.budget_authorization_id if code_review else None,
            "authorization_status": code_review_authorization.status.value
            if code_review_authorization
            else "NOT_LINKED",
            "dispatch_status": code_review_dispatch.status.value
            if code_review_dispatch
            else "NOT_DISPATCHED",
            "dispatch_intent_present": bool(
                code_review_dispatch and code_review_dispatch.last_dispatch_intent_id
            ),
            "dispatch_attempt_count": len(code_review_attempts),
            "gate_code": (run.stop_details or {}).get("code") if run else None,
        },
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
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_orchestration", "F3"))


@app.get("/api/v1/openspec/integrity", tags=["openspec"])
def get_openspec_integrity(
    project_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    """Return the most recent OpenSpec integrity audit for a project."""
    audit = uow.integrity_findings.get_latest(project_id)
    if not audit:
        return {
            "project_id": project_id,
            "overall_status": "UNKNOWN",
            "findings": [],
            "evidence_gaps": ["No integrity audit has been recorded for this project."],
        }
    return audit.model_dump()


@app.post("/api/v1/openspec/integrity/audit", tags=["openspec"])
def run_openspec_integrity_audit(
    project_id: str,
) -> dict[str, Any]:
    """F1 retains inspection only; agent-produced native validation belongs to F3."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("openspec_integrity_audit", "F3"),
    )


@app.post("/api/v1/orchestration/start", tags=["orchestration"])
def start_orchestration(
    req: OrchestrationStartRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_orchestration", "F3"))


@app.post("/api/v1/orchestration/resume", tags=["orchestration"])
def resume_orchestration(
    req: OrchestrationResumeRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    """Resume an existing orchestration run from its persisted checkpoint."""
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_orchestration", "F3"))


@app.get("/api/v1/orchestration/{run_id}/status", tags=["orchestration"])
def get_orchestration_status(
    run_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_orchestration", "F3"))


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
) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_dashboard", "F5"))


@app.get("/api/v1/dashboard/changes/{project_id}/{change_name}", tags=["dashboard"])
def get_dashboard_change_detail(
    project_id: str,
    change_name: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    run_id: str | None = None,
) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_dashboard", "F5"))


@app.get("/api/v1/dashboard/runs/{run_id}", tags=["dashboard"])
def get_dashboard_run_detail(
    run_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_dashboard", "F5"))


@app.get("/api/v1/dashboard/events", tags=["dashboard"])
def get_dashboard_events(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str | None = None,
    change_name: str | None = None,
    run_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_dashboard", "F5"))


# -----------------------------------------------------------------------------
# Provider Efficiency & Telemetry Endpoints
# -----------------------------------------------------------------------------


@app.get(
    "/api/v1/efficiency/{project_id}/{change_name}",
    tags=["efficiency"],
)
@app.get(
    "/projects/{project_id}/changes/{change_name}/efficiency",
    tags=["efficiency"],
)
def get_change_efficiency_telemetry(
    project_id: str,
    change_name: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> EfficiencyTelemetryView:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_dashboard", "F5"))


@app.get(
    "/api/v1/efficiency/{project_id}",
    tags=["efficiency"],
)
@app.get(
    "/projects/{project_id}/efficiency",
    tags=["efficiency"],
)
def list_project_efficiency_metrics(
    project_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ProviderEfficiencyMetrics]:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_dashboard", "F5"))


# -----------------------------------------------------------------------------
# Preview & Validation Endpoints
# -----------------------------------------------------------------------------


@app.post("/api/v1/previews/build", tags=["previews"])
async def build_preview_image() -> dict[str, Any]:
    """F1 does not build or persist preview artifacts; that UI flow belongs to F5."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("container_preview", "F5"),
    )

@app.post("/api/v1/previews/start", tags=["previews"])
async def start_preview_container() -> dict[str, Any]:
    """F1 never launches containers from a compatibility endpoint."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("container_preview", "F5"),
    )

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
) -> dict[str, Any]:
    """F1 does not operate preview containers."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("container_preview", "F5"),
    )

@app.post("/api/v1/previews/reconcile", tags=["previews"])
async def reconcile_orphan_previews() -> dict[str, Any]:
    """F1 must not inspect or mutate Docker state."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("container_preview", "F5"),
    )

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
) -> dict[str, Any]:
    """F1 keeps no candidate-validation writer before the F5 UI exists."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("candidate_validation", "F5"),
    )

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
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_control_plane", "F3"))


@app.get(
    "/api/v1/control-plane/actions/available",
    tags=["control-plane"],
    response_model=list[ActionDescriptor],
)
def discover_control_plane_actions_endpoint(
    run_id: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> list[ActionDescriptor]:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_control_plane", "F3"))


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
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_control_plane", "F3"))


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
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_control_plane", "F3"))


@app.post(
    "/api/v1/control-plane/actions/execute",
    tags=["control-plane"],
    response_model=OperatorActionResult,
)
def execute_control_plane_action_endpoint(
    request_body: OperatorActionRequest,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
) -> OperatorActionResult:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_control_plane", "F3"))


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
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=unavailable_payload("legacy_control_plane", "F3"))


# -----------------------------------------------------------------------------
# Queue and Scheduler Endpoints
# -----------------------------------------------------------------------------


@app.get(
    "/api/v1/queue",
    tags=["queue"],
)
def list_queue_items_endpoint(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str | None = None,
    ready_only: bool = False,
) -> list[dict[str, Any]]:
    """The local work queue was retired; F3 owns selection and execution."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_queue", "F3"),
    )


@app.get(
    "/api/v1/queue/{change_name}/explain",
    tags=["queue"],
)
def explain_queue_item_endpoint(
    change_name: str,
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str = "mini-me",
) -> dict[str, Any]:
    """The local work queue was retired; F3 owns selection and execution."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_queue", "F3"),
    )


@app.get(
    "/api/v1/scheduler/status",
    tags=["scheduler"],
)
def get_scheduler_status_endpoint(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str | None = None,
) -> dict[str, Any]:
    """The scheduler was retired and remains disabled during F1."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_scheduler", "F3"),
    )


@app.post(
    "/api/v1/scheduler/tick",
    tags=["scheduler"],
)
def trigger_scheduler_tick_endpoint(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """The scheduler was retired and remains disabled during F1."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=unavailable_payload("legacy_scheduler", "F3"),
    )


# -----------------------------------------------------------------------------
# Authentication & Authorization Endpoints
# -----------------------------------------------------------------------------


def _resolve_google_credentials() -> tuple[str | None, str | None]:
    config = load_config()
    client_id = os.environ.get(config.auth.client_id_env) or os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get(config.auth.client_secret_env) or os.environ.get(
        "GOOGLE_CLIENT_SECRET"
    )
    if not client_secret and config.auth.client_secret_path:
        secret_file = Path(config.auth.client_secret_path)
        if secret_file.exists():
            try:
                client_secret = secret_file.read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.warning(f"Failed reading Google client secret from '{secret_file}': {exc}")
    return client_id, client_secret


@app.get("/api/v1/auth/me", tags=["auth"], response_model=AuthStatusDTO)
def get_auth_me_endpoint(request: Request, uow: UowDep) -> AuthStatusDTO:
    """Retrieve current operator authentication and authorization status."""
    token = extract_token_from_request(request)
    if not token:
        return AuthStatusDTO(authenticated=False)

    session_mgr = SessionManager(uow)
    operator_svc = AuthorizedOperatorService(uow)

    auth_session = session_mgr.validate_session_pure(token)
    if not auth_session:
        return AuthStatusDTO(authenticated=False)

    decision, operator = operator_svc.evaluate_operator_pure(
        auth_session.operator_email, auth_session.google_sub
    )
    if decision != OperatorAuthDecision.AUTHORIZED or not operator:
        return AuthStatusDTO(authenticated=False)

    return AuthStatusDTO(
        authenticated=True,
        operator=OperatorIdentityDTO(
            email=operator.email,
            display_name=operator.display_name,
            provider="google",
        ),
        session_expires_at=auth_session.expires_at.isoformat(),
    )


@app.get("/api/v1/auth/google/login", tags=["auth"])
def google_login_endpoint(request: Request, return_json: bool = False) -> Response:
    """Initiate Google OAuth 2.0 / OIDC login flow."""
    client_id, _ = _resolve_google_credentials()
    config = load_config()
    redirect_uri = (
        config.auth.redirect_uri
        or os.environ.get("GOOGLE_REDIRECT_URI")
        or str(request.url_for("google_callback_endpoint"))
    )
    if request.headers.get("x-forwarded-proto") == "https" and redirect_uri.startswith("http://"):
        redirect_uri = "https://" + redirect_uri[7:]

    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth client_id is not configured",
        )

    oidc_service = GoogleOidcService(client_id=client_id)
    state = generate_state_token()
    auth_url = oidc_service.get_authorization_url(redirect_uri=redirect_uri, state=state)

    if return_json:
        response = JSONResponse({"auth_url": auth_url, "state": state})
    else:
        response = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)

    is_secure = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
        or config.auth.cookie_secure.lower() == "true"
    )
    response.set_cookie(
        key="minime_oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )
    return response


@app.get("/api/v1/auth/google/callback", tags=["auth"])
def google_callback_endpoint(
    request: Request,
    uow: UowDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    """Handle Google OAuth 2.0 callback, verify ID token, validate operator allowlist, and issue session."""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    operator_svc = AuthorizedOperatorService(uow)
    session_mgr = SessionManager(uow)
    config = load_config()

    if error:
        operator_svc.record_audit(
            event_type=AuthEventType.LOGIN_REJECTED,
            ip_address=client_ip,
            user_agent=user_agent,
            reason=f"Google returned error: {error}",
        )
        return HTMLResponse(
            f"<!DOCTYPE html><html><body><h1>Authentication Error</h1><p>{error}</p><p><a href='/'>Return to Login</a></p></body></html>",
            status_code=400,
        )

    if not code or not state:
        operator_svc.record_audit(
            event_type=AuthEventType.LOGIN_REJECTED,
            ip_address=client_ip,
            user_agent=user_agent,
            reason="Missing code or state parameter in OAuth callback",
        )
        return HTMLResponse(
            "<!DOCTYPE html><html><body><h1>Authentication Error</h1><p>Missing code or state parameter.</p><p><a href='/'>Return to Login</a></p></body></html>",
            status_code=400,
        )

    # Validate state cookie to prevent CSRF
    expected_state = request.cookies.get("minime_oauth_state")
    if not expected_state or expected_state != state:
        operator_svc.record_audit(
            event_type=AuthEventType.LOGIN_REJECTED,
            ip_address=client_ip,
            user_agent=user_agent,
            reason="OAuth state mismatch or missing state cookie",
        )
        return HTMLResponse(
            "<!DOCTYPE html><html><body><h1>Authentication Error</h1><p>Invalid or expired OAuth state token.</p><p><a href='/'>Return to Login</a></p></body></html>",
            status_code=400,
        )

    client_id, client_secret = _resolve_google_credentials()
    redirect_uri = (
        config.auth.redirect_uri
        or os.environ.get("GOOGLE_REDIRECT_URI")
        or str(request.url_for("google_callback_endpoint"))
    )
    if request.headers.get("x-forwarded-proto") == "https" and redirect_uri.startswith("http://"):
        redirect_uri = "https://" + redirect_uri[7:]

    oidc_service = GoogleOidcService(client_id=client_id, client_secret=client_secret)
    try:
        tokens = oidc_service.exchange_code(code=code, redirect_uri=redirect_uri)
        id_token_str = tokens.get("id_token")
        if not id_token_str:
            raise ValueError("Google token response missing id_token")
        claims = oidc_service.verify_id_token(id_token_str)
    except Exception as exc:
        logger.warning(f"Google ID token verification failed: {exc}")
        operator_svc.record_audit(
            event_type=AuthEventType.LOGIN_REJECTED,
            ip_address=client_ip,
            user_agent=user_agent,
            reason=f"Token verification failed: {exc}",
        )
        return HTMLResponse(
            f"<!DOCTYPE html><html><body><h1>Authentication Error</h1><p>Token verification failed: {exc}</p><p><a href='/'>Return to Login</a></p></body></html>",
            status_code=401,
        )

    google_sub = claims.get("sub")
    email = claims.get("email", "").lower().strip()

    # Evaluate operator authorization against local allowlist
    decision, operator = operator_svc.evaluate_operator(email=email, google_sub=google_sub)
    if decision == OperatorAuthDecision.IDENTITY_NOT_ALLOWLISTED:
        operator_svc.record_audit(
            event_type=AuthEventType.AUTHORIZATION_DENIED,
            operator_email=email,
            google_sub=google_sub,
            ip_address=client_ip,
            user_agent=user_agent,
            reason="Google identity not in authorized operators allowlist",
        )
        return HTMLResponse(
            f"<!DOCTYPE html><html><body><h1>Access Denied</h1><p>The Google account <b>{email}</b> is not authorized to access mini me.</p><p><a href='/'>Return to Login</a></p></body></html>",
            status_code=403,
        )
    if decision == OperatorAuthDecision.IDENTITY_DISABLED:
        operator_svc.record_audit(
            event_type=AuthEventType.AUTHORIZATION_DENIED,
            operator_email=email,
            google_sub=google_sub,
            ip_address=client_ip,
            user_agent=user_agent,
            reason="Authorized operator account is disabled",
        )
        return HTMLResponse(
            f"<!DOCTYPE html><html><body><h1>Account Disabled</h1><p>The operator account <b>{email}</b> is disabled.</p><p><a href='/'>Return to Login</a></p></body></html>",
            status_code=403,
        )

    # Issue server-side session
    lifetime = config.auth.session_lifetime_seconds
    raw_token, session = session_mgr.create_session(
        operator_email=email,
        google_sub=google_sub,
        ip_address=client_ip,
        user_agent=user_agent,
        lifetime_seconds=lifetime,
    )
    operator_svc.record_audit(
        event_type=AuthEventType.LOGIN_SUCCEEDED,
        operator_email=email,
        google_sub=google_sub,
        ip_address=client_ip,
        user_agent=user_agent,
        reason="Successful Google OIDC login and authorization",
    )

    is_secure = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
        or config.auth.cookie_secure.lower() == "true"
    )
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="minime_session",
        value=raw_token,
        max_age=lifetime,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )
    response.delete_cookie(key="minime_oauth_state", path="/")
    return response


@app.post("/api/v1/auth/logout", tags=["auth"])
def logout_endpoint(request: Request, uow: UowDep) -> Response:
    """Invalidate active session and clear session cookie."""
    token = extract_token_from_request(request)
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    if token:
        session_mgr = SessionManager(uow)
        operator_svc = AuthorizedOperatorService(uow)
        session = session_mgr.validate_session(token)
        if session:
            operator_svc.record_audit(
                event_type=AuthEventType.LOGOUT,
                operator_email=session.operator_email,
                google_sub=session.google_sub,
                ip_address=client_ip,
                user_agent=user_agent,
                reason="Operator explicitly logged out",
            )
        session_mgr.revoke_session_by_token(token)

    response = JSONResponse({"status": "logged_out", "message": "Session successfully invalidated"})
    response.delete_cookie(key="minime_session", path="/")
    return response


# -----------------------------------------------------------------------------
# Static UI Mounting & Index
# -----------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent.parent / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
else:
    logger.warning("Dashboard static directory '%s' does not exist.", STATIC_DIR)


@app.api_route("/", methods=["GET", "HEAD"], tags=["dashboard-ui"], response_model=None)
@app.api_route("/dashboard", methods=["GET", "HEAD"], tags=["dashboard-ui"], response_model=None)
@app.api_route("/trabajo", methods=["GET", "HEAD"], tags=["dashboard-ui"], response_model=None)
@app.api_route("/trabajo-actual", methods=["GET", "HEAD"], tags=["dashboard-ui"], response_model=None)
@app.api_route("/proyectos", methods=["GET", "HEAD"], tags=["dashboard-ui"], response_model=None)
@app.api_route("/backlog", methods=["GET", "HEAD"], tags=["dashboard-ui"], response_model=None)
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





@app.api_route("/sw.js", methods=["GET", "HEAD"], include_in_schema=False)
def get_service_worker() -> Response:
    sw_file = STATIC_DIR / "sw.js"
    if sw_file.exists():
        return FileResponse(sw_file, media_type="application/javascript")
    return Response(status_code=404)
