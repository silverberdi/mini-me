"""FastAPI application for mini me daemon."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Generator
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from minime.adapters.provider_adapter import (
    PROVIDER_DIAGNOSTIC_TIMEOUT_SECONDS,
    ProviderConnectionDiagnostic,
    get_provider_adapter,
)
from minime.config import load_config
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.domain.enums import (
    AuthEventType,
    EventType,
    HumanGate,
    OperatorActionType,
    OperatorAuthDecision,
    OrchestrationStopOutcome,
    ProjectType,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    AuthorizedOperator,
    AuthStatusDTO,
    ContextDiscoveryReport,
    Event,
    OperatorActionRecord,
    OperatorIdentityDTO,
    ProjectConfigurationInput,
    ProjectConfigurationPatch,
    ProviderHealth,
    SchedulerStatus,
    get_active_human_payload,
)
from minime.logging import redact_secrets
from minime.services.apply_checkpoint_recovery import (
    PRESERVE_RESPONSE as APPLY_RECOVERY_PRESERVE_RESPONSE,
)
from minime.services.apply_checkpoint_recovery import (
    REBASELINE_RESPONSE as APPLY_RECOVERY_REBASELINE_RESPONSE,
)
from minime.services.apply_checkpoint_recovery import (
    diagnose_lost_apply_checkpoint,
    recovery_gate_payload,
)
from minime.services.auth_service import (
    AuthorizedOperatorService,
    GoogleOidcService,
    SessionManager,
    generate_state_token,
)
from minime.services.budget_service import BudgetService
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
from minime.services.context_discovery_service import ContextDiscoveryService
from minime.services.dashboard_service import DashboardOverviewResponse, OperationsDashboardService
from minime.services.event_broker import event_broker
from minime.services.greenfield_bootstrap import (
    GreenfieldBootstrapCoordinator,
    GreenfieldBootstrapError,
)
from minime.services.postgres_run_event_listener import PostgresRunEventListener
from minime.services.project_catalog_service import ProjectCatalogService
from minime.services.project_connection_service import ProjectConnectionService
from minime.services.project_service import ProjectService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.provider_registry import (
    CanonicalProfileResolver,
    CustomModelRequest,
    ModelEnablementRequest,
    SafeCliHarness,
    catalog_payload,
    classify_discovered_model,
    reject_secret_payload,
)
from minime.services.quota_telemetry import quota_telemetry
from minime.services.run_cancellation_service import RunCancellationError, RunCancellationService
from minime.services.run_recovery import RunRecoveryService
from minime.services.status_service import StatusService
from minime.services.web_push_service import web_push_service

logger = logging.getLogger(__name__)

_RUN_WORKER_LIMIT = 2
_run_worker_semaphore = asyncio.Semaphore(_RUN_WORKER_LIMIT)
_run_tasks: set[asyncio.Task[None]] = set()
_accepted_operations: dict[tuple[str, str], str] = {}


def _run_notification_fingerprint(result: Any, run: Any) -> str:
    """Identify one observable Run outcome without using wall-clock polling."""
    details = getattr(run, "stop_details", {}) or {}
    stage = getattr(result, "current_stage", None)
    stage_value = getattr(stage, "value", stage)
    stage_attempt = details.get(str(stage_value).lower()) if isinstance(details, dict) else None
    if not isinstance(stage_attempt, dict):
        stage_attempt = details.get("proposal_review") if isinstance(details, dict) else None
    payload = {
        "run_id": getattr(result, "run_id", None),
        "status": getattr(result, "status", None),
        "stage": stage_value,
        "message": getattr(result, "message", None),
        "human_payload": getattr(result, "human_payload", None),
        "attempt_id": stage_attempt.get("attempt_id") if isinstance(stage_attempt, dict) else None,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _should_publish_run_notification(uow: Any, result: Any) -> bool:
    """Publish only a new durable Run outcome; preserve explicit re-entry paths."""
    run_id = getattr(result, "run_id", None)
    runs = getattr(uow, "orchestration_runs", None)
    if not run_id or runs is None or not hasattr(runs, "get_by_id"):
        return True
    run = runs.get_by_id(run_id)
    if run is None:
        return True
    fingerprint = _run_notification_fingerprint(result, run)
    details = dict(getattr(run, "stop_details", {}) or {})
    if details.get("last_notification_fingerprint") == fingerprint:
        return False
    details["last_notification_fingerprint"] = fingerprint
    run.stop_details = details
    if hasattr(runs, "save"):
        runs.save(run)
    if hasattr(uow, "commit"):
        uow.commit()
    return True


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
        # Recovery is discovery + fenced claim only; provider work is scheduled after
        # the startup transaction and therefore never shares this session.
        try:
            recovered = RunRecoveryService(uow).discover_and_claim()
            for project_id, run_id in recovered:
                task = asyncio.create_task(
                    _execute_request_in_fresh_session(
                        project_id, ProjectRequestRunPayload(target_run_id=run_id), target_run_id=run_id
                    )
                )
                _run_tasks.add(task)
                task.add_done_callback(_run_tasks.discard)
                await event_broker.publish("run.recovered", {"project_id": project_id, "run_id": run_id})
        except Exception as exc:
            logger.warning("Run startup recovery unavailable: %s", type(exc).__name__)
    except Exception as exc:
        logger.warning(f"Error during startup reconciliation: {exc}")
    finally:
        if sess:
            sess.close()
    listener = None
    try:
        database_url = db_manager.engine.url.set(drivername="postgresql").render_as_string(
            hide_password=False
        )
        listener = PostgresRunEventListener(database_url, event_broker.publish)
        await listener.start()
    except Exception as exc:
        logger.warning("PostgreSQL Run event listener could not start: %s", type(exc).__name__)
    try:
        yield
    finally:
        if listener is not None:
            await listener.stop()


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


STATIC_DIR = Path(__file__).parent.parent / "static"

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
    "/favicon.svg",
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
        return await call_next(request)

    path = request.url.path
    clean_path = path.lstrip("/")
    target_static = (STATIC_DIR / clean_path).resolve() if STATIC_DIR.exists() and clean_path else None
    is_static_file = (
        target_static is not None
        and STATIC_DIR.resolve() in target_static.parents
        and target_static.is_file()
    )

    if (
        path in PUBLIC_EXEMPT_PATHS
        or any(path.startswith(prefix) for prefix in PUBLIC_EXEMPT_PREFIXES)
        or is_static_file
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

    return await call_next(request)


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


def _validate_live_canonical_profiles(profiles: dict[str, Any], uow: Any) -> None:
    """Validate new canonical selections before any project write or dispatch."""
    data_by_name = {
        name: profile.model_dump() if hasattr(profile, "model_dump") else dict(profile)
        for name, profile in profiles.items()
    }
    canonical_selected = any(
        data.get("provider_id") is not None or data.get("harness_id") is not None
        for data in data_by_name.values()
    )
    if not canonical_selected:
        return
    missing = [
        name for name, data in data_by_name.items()
        if not data.get("provider_id") or not data.get("harness_id")
    ]
    if missing:
        raise ValueError(
            "Canonical provider and harness are required for every role: "
            + ", ".join(sorted(missing))
        )
    selections = {}
    role_names = {"thinking": "thinker", "execution": "implementer", "independent_review": "reviewer", "fallback": "backup"}
    for name, data in data_by_name.items():
        selections[role_names[name]] = {
            "provider_id": data.get("provider_id") or data.get("agent_id"),
            "harness_id": data.get("harness_id") or data.get("agent_id"),
            "canonical_model_id": data.get("model_id"),
            "effort": data.get("effort"),
            "route": data.get("route"),
        }
    resolver = CanonicalProfileResolver(uow.provider_model_registry, freshness=None)
    for role_name, sel in selections.items():
        prov = str(sel.get("provider_id", "")).strip().lower()
        harn = str(sel.get("harness_id", "")).strip().lower()
        if harn in {"codex", "antigravity"} or prov in {"codex", "antigravity"}:
            continue
        resolver.resolve(role_name, sel)


@app.get("/api/v1/admin/providers/catalog", tags=["admin-providers"])
def administrative_provider_catalog(
    _operator: AuthenticatedOperatorDep, uow: UowDep
) -> dict[str, Any]:
    """Return the durable non-secret provider/model catalog."""
    return catalog_payload(uow.provider_model_registry.list())


@app.post("/api/v1/admin/providers/{provider}/test", tags=["admin-providers"])
async def test_administrative_provider_connection(
    provider: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Run a bounded non-inference diagnostic for a configured catalog provider."""
    config = load_config()
    catalog_provider_ids = {
        row.provider_id for row in uow.provider_model_registry.list()
    }
    if provider not in catalog_provider_ids or provider not in config.providers:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configured catalog provider was not found.",
        )

    try:
        adapter = get_provider_adapter(provider, config)
    except ValueError:
        diagnostic = ProviderConnectionDiagnostic(
            status="unavailable",
            latency_ms=None,
            code="diagnostic_unsupported",
            detail="A bounded non-inference connection check is not available for this provider.",
        )
    else:
        try:
            diagnostic = await asyncio.wait_for(
                adapter.diagnose_connection(),
                timeout=PROVIDER_DIAGNOSTIC_TIMEOUT_SECONDS + 1,
            )
        except TimeoutError:
            diagnostic = ProviderConnectionDiagnostic(
                status="failure",
                latency_ms=round((PROVIDER_DIAGNOSTIC_TIMEOUT_SECONDS + 1) * 1000),
                code="provider_timeout",
                detail="The provider did not answer within the diagnostic time limit.",
            )
        except Exception:
            diagnostic = ProviderConnectionDiagnostic(
                status="failure",
                latency_ms=None,
                code="diagnostic_failed",
                detail="The provider connection diagnostic could not be completed.",
            )

    return {"provider": provider, **asdict(diagnostic)}


@app.post("/api/v1/admin/providers/models", status_code=status.HTTP_200_OK, tags=["admin-providers"])
def administrative_custom_model(
    payload: CustomModelRequest,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Create or update one custom route with optimistic versioning."""
    try:
        reject_secret_payload(payload.model_dump())
        row = uow.provider_model_registry.upsert_custom(payload)
        uow.flush()
        result = catalog_payload([row])["models"][0]
        uow.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.patch("/api/v1/admin/providers/models/{model_id}/enabled", tags=["admin-providers"])
def set_administrative_model_enabled(
    model_id: str,
    payload: ModelEnablementRequest,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    try:
        row = uow.provider_model_registry.set_enabled(model_id, payload)
        uow.flush()
        result = catalog_payload([row])["models"][0]
        uow.commit()
        return result
    except LookupError as exc:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.post("/api/v1/admin/providers/refresh", tags=["admin-providers"])
async def refresh_administrative_provider_catalog(
    _operator: AuthenticatedOperatorDep, uow: UowDep
) -> dict[str, Any]:
    """Run bounded, read-only configured harness discovery; never dispatches work."""
    results: list[dict[str, Any]] = []
    config = load_config()
    for harness_id in ("opencode", "ollama"):
        provider = config.providers.get(harness_id)
        executable = (provider.command if provider else None) or harness_id
        credential_env = provider.api_key_env if provider else None
        result = await SafeCliHarness(
            harness_id,
            executable,
            credential_env=credential_env,
        ).inspect()
        uow.provider_model_registry.record_harness_diagnostic(harness_id, result)
        results.append({"harness_id": result.harness_id, "status": result.status, "code": result.code, "summary": result.summary})
        for model_id in result.models:
            provider_id, canonical_harness, route = classify_discovered_model(harness_id, model_id)
            uow.provider_model_registry.upsert_observation({
                "provider_id": provider_id,
                "harness_id": canonical_harness,
                "canonical_model_id": model_id,
                "origin": "discovered",
                "capabilities": {
                    "model_route": route,
                    "thinking": True,
                    "workflow": True,
                    "file_edit": True,
                    "read_only_review": True,
                },
                "discovery_status": "available",
                "diagnostic_code": result.code,
                "diagnostic_summary": result.summary,
                "observed_cli_version": result.cli_version,
                "last_observed_at": datetime.now(UTC),
            })
    uow.flush()
    response = {"results": results, "catalog": catalog_payload(uow.provider_model_registry.list())}
    uow.commit()
    return response


@app.get("/api/v1/catalogs/providers", tags=["catalogs"])
def project_provider_catalog(_operator: AuthenticatedOperatorDep) -> list[dict[str, Any]]:
    """Return provider metadata only; project connections and secrets are never included."""
    return ProjectCatalogService().provider_catalog()


@app.get("/api/v1/catalogs/agents", tags=["catalogs"])
async def project_agent_catalog(
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    project_id: str | None = None,
    only_enabled: bool = True,
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
    catalog = await ProjectCatalogService().agent_catalog(project_root)
    if only_enabled:
        registry = getattr(uow, "provider_model_registry", None)
        if registry is not None:
            registry_models = registry.list()
            if registry_models:
                enabled_models = {
                    row.canonical_model_id.lower()
                    for row in registry_models
                    if row.is_enabled
                }
                filtered_agents = []
                for agent in catalog.get("agents", []):
                    harness_id = (agent.get("id") or "").lower()
                    harness_entries = [
                        row for row in registry_models
                        if row.harness_id.lower() == harness_id or row.provider_id.lower() == harness_id
                    ]
                    if not harness_entries:
                        filtered_agents.append(agent)
                        continue

                    new_models = {
                        m_key: efforts
                        for m_key, efforts in (agent.get("models") or {}).items()
                        if m_key.lower() in enabled_models
                    }
                    new_agent = dict(agent)
                    new_agent["models"] = new_models
                    filtered_agents.append(new_agent)
                catalog = dict(catalog)
                catalog["agents"] = filtered_agents
    return catalog


@app.get("/api/v1/projects", tags=["projects"])
def list_project_configurations(
    _operator: AuthenticatedOperatorDep, uow: UowDep
) -> list[dict[str, Any]]:
    service = ProjectService(uow)
    return [service.public_project_payload(project) for project in service.list_projects()]


@app.post("/api/v1/projects", status_code=status.HTTP_201_CREATED, tags=["projects"])
async def create_project_configuration(
    configuration: ProjectConfigurationInput,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Create an atomic multi-stage Brownfield registration; Greenfield needs ZIP bootstrap."""
    try:
        _validate_live_canonical_profiles(configuration.agent_profiles, uow)
        await ProjectCatalogService().validate_project_profiles(configuration.agent_profiles)
        service = ProjectService(uow)
        should_validate_live = os.environ.get("MINIME_AUTH_ENABLED", "true").lower() != "false"
        project = service.create_configured_project(configuration, validate_grants=should_validate_live)
        if should_validate_live and configuration.project_type != ProjectType.GREENFIELD:
            from minime.services.project_onboarding_service import ProjectOnboardingService
            onboarding_service = ProjectOnboardingService(uow)
            operator_email = getattr(_operator, "email", "operator")
            try:
                onboarding_service.onboard_project(project, operator_email=operator_email)
            except Exception as onboarding_exc:
                try:
                    import shutil
                    trusted_root = os.environ.get("MINIME_MANAGED_ROOT", "/opt/minime/repos")
                    managed_root = os.path.realpath(f"{trusted_root}/{project.project_id}")
                    if os.path.exists(managed_root):
                        shutil.rmtree(managed_root, ignore_errors=True)
                    uow.projects.delete(project.project_id)
                    uow.commit()
                except Exception:
                    pass
                raise ValueError(f"Fallo en la preparación del repositorio: {onboarding_exc}") from onboarding_exc
        return service.public_project_payload(project)
    except ValueError as exc:
        logger.warning("Error de validación al crear proyecto: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error inesperado al crear proyecto: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error inesperado al crear proyecto: {exc}",
        ) from exc


@app.post(
    "/api/v1/projects/greenfield/bootstrap", status_code=status.HTTP_202_ACCEPTED, tags=["projects"]
)
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
        _validate_live_canonical_profiles(configuration.agent_profiles, uow)
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
            _validate_live_canonical_profiles(patch.agent_profiles, uow)
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
        code = (
            status.HTTP_404_NOT_FOUND
            if message.endswith("not found")
            else status.HTTP_400_BAD_REQUEST
        )
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
        code = (
            status.HTTP_404_NOT_FOUND if message.endswith("not found") else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=message) from exc


@app.post(
    "/api/v1/projects/{project_id}/context", status_code=status.HTTP_202_ACCEPTED, tags=["projects"]
)
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
        code = (
            status.HTTP_404_NOT_FOUND if message.endswith("not found") else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=message) from exc


@app.post("/api/v1/projects/{project_id}/pause", tags=["projects"])
def pause_project(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    background_tasks: BackgroundTasks,
    defer_if_active: bool = Query(True, description="Defer pause if an active run is in progress"),
) -> dict[str, Any]:
    try:
        service = ProjectService(uow)
        has_active_run = False
        if hasattr(uow, "orchestration_runs"):
            runs = (
                uow.orchestration_runs.list_by_project(project_id)
                if hasattr(uow.orchestration_runs, "list_by_project")
                else []
            )
            has_active_run = any(getattr(r, "is_active", False) for r in runs)

        if has_active_run and defer_if_active:
            result = service.pause_project(project_id, defer_if_active=True)
            background_tasks.add_task(
                event_broker.publish,
                "project.pause_changed",
                {"scope": "project", "project_id": project_id},
            )
            return result

        service.pause_project(project_id, defer_if_active=False)
        result = service.public_project_payload(service.set_lifecycle(project_id, active=False))
        background_tasks.add_task(
            event_broker.publish,
            "project.pause_changed",
            {"scope": "project", "project_id": project_id},
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/resume", tags=["projects"])
def resume_project(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    try:
        service = ProjectService(uow)
        result = service.resume_project(project_id)
        background_tasks.add_task(
            event_broker.publish,
            "project.pause_changed",
            {"scope": "project", "project_id": project_id},
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@app.post("/api/v1/system/pause", tags=["system"])
def pause_system(
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    background_tasks: BackgroundTasks,
    defer_if_active: bool = Query(True, description="Defer pause if an active run is in progress"),
) -> dict[str, Any]:
    service = ProjectService(uow)
    result = service.pause_global(defer_if_active=defer_if_active)
    background_tasks.add_task(
        event_broker.publish,
        "project.pause_changed",
        {"scope": "global"},
    )
    return result


@app.post("/api/v1/system/resume", tags=["system"])
def resume_system(
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    service = ProjectService(uow)
    result = service.resume_global()
    background_tasks.add_task(
        event_broker.publish,
        "project.pause_changed",
        {"scope": "global"},
    )
    return result


class DocumentContextUpdateRequest(BaseModel):
    path: str = Field(..., description="Relative path within project repository")
    content: str = Field(..., description="New file content")
    expected_version: str | None = Field(
        None, description="SHA256 hex digest of existing content for optimistic concurrency"
    )


@app.patch("/api/v1/projects/{project_id}/context/document", tags=["projects"])
def update_project_document_context(
    project_id: str,
    payload: DocumentContextUpdateRequest,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    target_project = uow.projects.get_by_id(project_id)
    if target_project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    rel_path = payload.path.strip()
    if not rel_path or rel_path.startswith("/") or ".." in Path(rel_path).parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid document path: path traversal or absolute path detected",
        )

    norm_path = Path(rel_path)
    allowed_extensions = {".md", ".yaml", ".yml", ".json", ".txt"}
    if norm_path.suffix.lower() not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File extension {norm_path.suffix} is not authorized for document context editing",
        )

    first_part = norm_path.parts[0] if norm_path.parts else ""
    if first_part not in ("docs", "openspec", "README.md", "AGENTS.md"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document context editing restricted to docs/, openspec/, or project documentation files",
        )

    base_dir = Path("/opt/minime/repos") / project_id
    if not base_dir.exists():
        import tempfile
        base_dir = Path(tempfile.gettempdir()) / "minime_repos" / project_id
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    target_file = (base_dir / norm_path).resolve()
    if not str(target_file).startswith(str(base_dir.resolve())):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path escapes project repository boundary",
        )

    current_content = ""
    current_sha = hashlib.sha256(b"").hexdigest()
    if target_file.exists():
        try:
            current_content = target_file.read_text(encoding="utf-8")
            current_sha = hashlib.sha256(current_content.encode("utf-8")).hexdigest()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read existing document: {exc}",
            ) from exc

    if payload.expected_version and payload.expected_version != current_sha:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Optimistic concurrency conflict: expected {payload.expected_version}, found {current_sha}",
        )

    try:
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(payload.content, encoding="utf-8")
        new_sha = hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write document content: {exc}",
        ) from exc

    if hasattr(uow, "events"):
        evt = Event(
            event_type=EventType.PROJECT_UPDATED,
            project_id=project_id,
            payload={
                "action": "document_context_edit",
                "path": rel_path,
                "previous_version": current_sha,
                "new_version": new_sha,
                "operator": getattr(_operator, "username", getattr(_operator, "email", "operator")),
            },
        )
        uow.events.save(evt)
        uow.commit()

    return {
        "status": "UPDATED",
        "project_id": project_id,
        "path": rel_path,
        "version": new_sha,
        "updated_at": datetime.now(UTC).isoformat(),
    }


@app.post("/api/v1/projects/{project_id}/executor", tags=["projects"])
def set_project_executor(
    project_id: str, _operator: AuthenticatedOperatorDep, uow: UowDep
) -> dict[str, Any]:
    try:
        service = ProjectService(uow)
        return service.set_executor_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/activate", tags=["projects"])
def activate_project(
    project_id: str, _operator: AuthenticatedOperatorDep, uow: UowDep
) -> dict[str, Any]:
    try:
        service = ProjectService(uow)
        service.set_lifecycle(project_id, active=True)
        service.resume_project(project_id)
        return service.public_project_payload(service.get_project(project_id))
    except ValueError as exc:
        message = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND if message.endswith("not found") else status.HTTP_409_CONFLICT
        )
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
    idempotency_key: str | None = None
    target_run_id: str | None = None
    operator_ack: bool = False
    operator_response: str | None = None
    operator_clarification: str | None = None
    explore_recovery_authorization_id: str | None = None
    propose_recovery_authorization_id: str | None = None
    proposal_review_recovery_authorization_id: str | None = None
    code_review_recovery_authorization_id: str | None = None
    thinker_provider: str | None = None
    implementer_provider: str | None = None
    reviewer_provider: str | None = None


def _diagnose_apply_checkpoint_recovery(uow: Any, run: Any) -> dict[str, Any] | None:
    """Project only the persisted legacy no-op Update sequence; never infer task state."""
    stage = getattr(getattr(run, "current_stage", None), "value", getattr(run, "current_stage", None))
    details = getattr(run, "stop_details", None) or {}
    gate = details.get("human_payload") or {}
    checkpoint = details.get("apply_gate_update") or {}
    persisted = details.get("apply_checkpoint_recovery") or {}
    if persisted.get("status") == "BLOCKED":
        return dict(persisted)
    if (
        not getattr(run, "is_active", False)
        or stage != "IMPLEMENTING"
        or gate.get("gate") not in {"apply_escalation", "apply_checkpoint_recovery"}
        or checkpoint.get("status") != "VALIDATED"
        or checkpoint.get("changed") is not False
        or checkpoint.get("reclassified_tasks") != []
    ):
        return None
    actions_repo = getattr(uow, "operator_actions", None)
    events_repo = getattr(uow, "orchestration_stage_events", None)
    actions = actions_repo.list_by_run(run.run_id) if actions_repo is not None else []
    events = events_repo.list_by_run(run.run_id) if events_repo is not None else []
    return diagnose_lost_apply_checkpoint(run, actions, events)


def _persist_projected_human_gate(
    uow: Any, run: Any, payload: dict[str, Any], *, commit: bool = True
) -> None:
    details = dict(run.stop_details or {})
    details["human_payload"] = payload
    run.stop_details = details
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
    run.stop_reason = payload.get("question")
    uow.orchestration_runs.save(run)
    if commit:
        uow.commit()


class RunCancellationPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("reason", "idempotency_key")
    @classmethod
    def require_non_whitespace(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Value must not be blank.")
        return cleaned


async def _execute_request_in_fresh_session(
    project_id: str,
    body: ProjectRequestRunPayload,
    intent_key: str | None = None,
    target_run_id: str | None = None,
) -> None:
    """Run long provider work after the HTTP transaction has closed."""
    async with _run_worker_semaphore:
        await event_broker.publish("run.accepted", {"project_id": project_id})
        session = db_manager.sessionmaker()
        worker_uow = PostgresPersistenceUnitOfWork(session)
        try:
            project = worker_uow.projects.get_by_id(project_id)
            if project is None:
                return
            binding = worker_uow.project_managed_repository_bindings.get_by_project_id(project_id)
            if binding is None or not binding.managed_repository_root:
                return
            from minime.adapters.github import GitHubAdapter
            from minime.services.agent_runner import CliAgentRunner
            from minime.services.budget_service import BudgetService
            from minime.services.capacity_lifecycle_service import CapacityLifecycleService
            from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
            from minime.services.worktree_manager import WorktreeManager

            runner = CliAgentRunner.for_project_profiles(
                project.agent_profiles,
                capacity_service=CapacityLifecycleService(worker_uow),
            )
            result = await NativeOrchestrationCoordinator(
                uow_factory=lambda: worker_uow,
                github_adapter=GitHubAdapter(),
                worktree_manager=WorktreeManager(
                    project_root=Path(binding.managed_repository_root), uow=worker_uow
                ),
                agent_runner=runner,
                semantic_pr_agent=True,
            ).execute_project_request(
                project_id,
                operator_ack=body.operator_ack,
                operator_clarification=body.operator_clarification or body.operator_response,
                explore_recovery_authorization_id=body.explore_recovery_authorization_id,
                propose_recovery_authorization_id=body.propose_recovery_authorization_id,
                proposal_review_recovery_authorization_id=body.proposal_review_recovery_authorization_id,
                code_review_recovery_authorization_id=body.code_review_recovery_authorization_id,
                operator_action_id=(
                    intent_key
                    if body.operator_clarification or body.operator_response or body.operator_ack
                    else None
                ),
                thinker_provider=runner.provider_for_role("thinker"),
                implementer_provider=runner.provider_for_role("implementer"),
                reviewer_provider=runner.provider_for_role("reviewer"),
                target_run_id=target_run_id or getattr(body, "target_run_id", None),
            )
            accepted_action = (
                worker_uow.operator_actions.get_by_request_id(intent_key)
                if intent_key and hasattr(worker_uow, "operator_actions")
                else None
            )
            if accepted_action is not None and accepted_action.action_type == OperatorActionType.RESOLVE_GATE:
                accepted_action.status = "COMPLETED"
                accepted_action.summary = "Accepted gate response processed by the coordinator."
                accepted_action.result_payload_json = {
                    "status": result.status,
                    "run_id": result.run_id,
                    "current_stage": result.current_stage.value if result.current_stage else None,
                    "message": result.message,
                    "human_payload": result.human_payload,
                }
                worker_uow.operator_actions.save(accepted_action)
            session.commit()
            if _should_publish_run_notification(worker_uow, result):
                await event_broker.publish(
                    "run.transition",
                    {"project_id": project_id, "run_id": result.run_id, "status": result.status},
                )
                # Web Push: Human Attention Required
                if result.human_payload:
                    await event_broker.publish(
                        "human.gate",
                        {"project_id": project_id, "run_id": result.run_id, "payload": result.human_payload},
                    )
                    try:
                        prompt_preview = (
                            result.human_payload.get("prompt")
                            or result.human_payload.get("message")
                            or "Se requiere atención para continuar."
                        )[:100]
                        web_push_service.broadcast_to_active_operators(
                            uow=worker_uow,
                            title="Atención Requerida — mini me",
                            body=f"[{project_id}] {prompt_preview}",
                            data={"url": f"/trabajo-actual?run={result.run_id}&project={project_id}"},
                            category="human_required",
                        )
                    except Exception as push_err:
                        logger.debug("Failed sending human_required push: %s", push_err)
                elif result.status in ("COMPLETED", "FAILED", "BLOCKED"):
                    try:
                        web_push_service.broadcast_to_active_operators(
                            uow=worker_uow,
                            title=f"Ejecución {result.status} — mini me",
                            body=f"Proyecto {project_id}: la ejecución finalizó en estado {result.status}.",
                            data={"url": f"/trabajo-actual?run={result.run_id}&project={project_id}"},
                            category="terminal_outcomes",
                        )
                    except Exception as push_err:
                        logger.debug("Failed sending terminal_outcomes push: %s", push_err)
                else:
                    try:
                        stage_name = getattr(result, "current_stage", result.status)
                        web_push_service.broadcast_to_active_operators(
                            uow=worker_uow,
                            title="Avance de Etapa — mini me",
                            body=f"[{project_id}] Etapa actual: {stage_name}",
                            data={"url": f"/trabajo-actual?run={result.run_id}&project={project_id}"},
                            category="stage_transitions",
                        )
                    except Exception as push_err:
                        logger.debug("Failed sending stage_transitions push: %s", push_err)
            # Persist subscription mutations (deactivation on 404/410, last_success_at)
            # applied by the broadcast above; the worker's earlier commit predates them.
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.exception("Asynchronous run worker failed: %s", type(exc).__name__)
            await event_broker.publish(
                "run.failed", {"project_id": project_id, "reason": type(exc).__name__}
            )
            try:
                web_push_service.broadcast_to_active_operators(
                    uow=worker_uow,
                    title="Ejecución FAILED — mini me",
                    body=f"[{project_id}] Fallo en ejecución asíncrona: {type(exc).__name__}",
                    data={"url": f"/trabajo-actual?project={project_id}"},
                    category="terminal_outcomes",
                )
            except Exception as push_err:
                logger.debug("Failed sending run.failed push: %s", push_err)
        finally:
            session.close()
            if intent_key is not None:
                _accepted_operations.pop((project_id, intent_key), None)


def _schedule_request_worker(project_id: str, body: ProjectRequestRunPayload, intent_key: str) -> str:
    task = asyncio.create_task(_execute_request_in_fresh_session(project_id, body, intent_key))
    _run_tasks.add(task)
    task.add_done_callback(_run_tasks.discard)
    return str(uuid4())


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

    github_adapter = GitHubAdapter()
    intake = RemoteRequestIntakeService(github_adapter=github_adapter, uow=uow)
    all_reqs = intake.get_all_requests(project.repository)
    eligible = [r for r in all_reqs if r.get("status") == "ELIGIBLE"]

    # Fetch closed issues to calculate project progress in PWA dashboard
    closed_res = github_adapter.list_issues(project.repository, state="closed", limit=100)
    closed_items = []
    if closed_res.data:
        for item in closed_res.data:
            c = dict(item)
            c["status"] = "COMPLETED"
            closed_items.append(c)

    return {
        "project_id": project_id,
        "repository": project.repository,
        "eligible_requests": eligible,
        "all_requests": all_reqs,
        "closed_requests": closed_items,
    }


class CreateProjectRequestPayload(BaseModel):
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    acceptance_criteria: str = Field(..., min_length=1)


class EditProjectRequestPayload(BaseModel):
    title: str | None = None
    body: str | None = None
    expected_version: str | None = None
    idempotency_key: str | None = None


class MutateProjectRequestPayload(BaseModel):
    expected_version: str | None = None
    idempotency_key: str | None = None


@app.post(
    "/api/v1/projects/{project_id}/requests", status_code=status.HTTP_201_CREATED, tags=["requests"]
)
def create_project_request(
    project_id: str,
    payload: CreateProjectRequestPayload,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Create a new human request governed by F4 normalization."""
    from minime.domain.exceptions import RequestMutationNotAllowedError
    from minime.services.request_lifecycle_service import RequestLifecycleService

    svc = RequestLifecycleService(uow=uow)
    try:
        res = svc.create_request(
            project_id=project_id,
            title=payload.title,
            description=payload.description,
            acceptance_criteria=payload.acceptance_criteria,
        )
        request_id = res.get("number") or res.get("issue_number") or res.get("id")
        event_payload = {"project_id": project_id}
        if request_id is not None:
            event_payload["request_id"] = request_id
        background_tasks.add_task(event_broker.publish, "request.created", event_payload)
        return {"project_id": project_id, "request": res}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except RequestMutationNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.patch("/api/v1/projects/{project_id}/requests/{issue_number}", tags=["requests"])
def edit_project_request(
    project_id: str,
    issue_number: int,
    payload: EditProjectRequestPayload,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Edit an unadmitted request with optimistic concurrency."""
    from minime.domain.exceptions import RequestMutationNotAllowedError
    from minime.services.request_lifecycle_service import RequestLifecycleService

    svc = RequestLifecycleService(uow=uow)
    try:
        res = svc.edit_request(
            project_id=project_id,
            issue_number=issue_number,
            title=payload.title,
            body=payload.body,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
        )
        return {"project_id": project_id, "issue_number": issue_number, "request": res}
    except RequestMutationNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.post("/api/v1/projects/{project_id}/requests/{issue_number}/deactivate", tags=["requests"])
def deactivate_project_request(
    project_id: str,
    issue_number: int,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    background_tasks: BackgroundTasks,
    payload: MutateProjectRequestPayload | None = None,
) -> dict[str, Any]:
    """Deactivate an unadmitted request, excluding it from FIFO."""
    from minime.domain.exceptions import RequestMutationNotAllowedError
    from minime.services.request_lifecycle_service import RequestLifecycleService

    svc = RequestLifecycleService(uow=uow)
    p = payload or MutateProjectRequestPayload()
    try:
        res = svc.deactivate_request(
            project_id=project_id,
            issue_number=issue_number,
            expected_version=p.expected_version,
            idempotency_key=p.idempotency_key,
        )
        background_tasks.add_task(
            event_broker.publish,
            "request.deactivated",
            {"project_id": project_id, "issue_number": issue_number},
        )
        return {"project_id": project_id, "issue_number": issue_number, "request": res}
    except RequestMutationNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.post("/api/v1/projects/{project_id}/requests/{issue_number}/reactivate", tags=["requests"])
def reactivate_project_request(
    project_id: str,
    issue_number: int,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    background_tasks: BackgroundTasks,
    payload: MutateProjectRequestPayload | None = None,
) -> dict[str, Any]:
    """Reactivate a previously disabled request."""
    from minime.domain.exceptions import RequestMutationNotAllowedError
    from minime.services.request_lifecycle_service import RequestLifecycleService

    svc = RequestLifecycleService(uow=uow)
    p = payload or MutateProjectRequestPayload()
    try:
        res = svc.reactivate_request(
            project_id=project_id,
            issue_number=issue_number,
            expected_version=p.expected_version,
            idempotency_key=p.idempotency_key,
        )
        background_tasks.add_task(
            event_broker.publish,
            "request.reactivated",
            {"project_id": project_id, "issue_number": issue_number},
        )
        return {"project_id": project_id, "issue_number": issue_number, "request": res}
    except RequestMutationNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@app.delete("/api/v1/projects/{project_id}/requests/{issue_number}", tags=["requests"])
def soft_delete_project_request(
    project_id: str,
    issue_number: int,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    payload: MutateProjectRequestPayload | None = None,
) -> dict[str, Any]:
    """Soft-delete an unadmitted request, preserving audit trail."""
    from minime.domain.exceptions import RequestMutationNotAllowedError
    from minime.services.request_lifecycle_service import RequestLifecycleService

    svc = RequestLifecycleService(uow=uow)
    p = payload or MutateProjectRequestPayload()
    try:
        res = svc.soft_delete_request(
            project_id=project_id,
            issue_number=issue_number,
            expected_version=p.expected_version,
            idempotency_key=p.idempotency_key,
        )
        return {"project_id": project_id, "issue_number": issue_number, "request": res}
    except RequestMutationNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))



@app.post("/api/v1/projects/{project_id}/requests/run", status_code=status.HTTP_202_ACCEPTED, tags=["requests"])
async def run_project_request(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    payload: ProjectRequestRunPayload | None = None,
) -> dict[str, Any]:
    """Execute or continue the active remote request for a project."""
    project = uow.projects.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    body = payload or ProjectRequestRunPayload()
    active_runs = uow.orchestration_runs.list_runs(project_id=project_id, is_active=True)
    accepted_action = None
    response_text = body.operator_clarification or body.operator_response
    client_idempotency_key = body.idempotency_key
    if body.operator_ack:
        response_text = response_text or "Estoy enterado"
    if response_text and body.idempotency_key:
        action_repo = getattr(uow, "operator_actions", None)
        if action_repo is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Durable operator-action storage is unavailable")
        token_action_id = hashlib.sha256(
            f"gate-response-token:{body.idempotency_key}".encode()
        ).hexdigest()
        accepted_action = action_repo.get_by_request_id(body.idempotency_key)
        if accepted_action is None:
            accepted_action = action_repo.get_by_request_id(token_action_id)
        action_request_id = (
            accepted_action.action_request_id if accepted_action is not None else token_action_id
        )
        if accepted_action is not None:
            response_fingerprint = hashlib.sha256(response_text.strip().encode()).hexdigest()
            if (
                accepted_action.action_type != OperatorActionType.RESOLVE_GATE
                or accepted_action.project_id != project_id
                or accepted_action.parameters_json.get("response_fingerprint") != response_fingerprint
                or (body.target_run_id and accepted_action.run_id != body.target_run_id)
            ):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The idempotency key is bound to a different gate response")
            body.target_run_id = body.target_run_id or accepted_action.run_id
            if accepted_action.status == "COMPLETED":
                return {
                    **dict(accepted_action.result_payload_json or {}),
                    "operation_id": accepted_action.action_request_id,
                    "idempotency_key": client_idempotency_key,
                }
            current_run = next(
                (item for item in active_runs if item.run_id == accepted_action.run_id), None
            )
            if current_run is None:
                return {
                    "status": "ACCEPTED",
                    "operation_id": accepted_action.action_request_id,
                    "idempotency_key": client_idempotency_key,
                    "run_id": accepted_action.run_id,
                    "message": "The gate response already has a durable accepted action.",
                }
            current_payload = (
                (current_run.stop_details or {}).get("human_payload") if current_run else None
            )
            current_gate_fingerprint = None
            if isinstance(current_payload, dict):
                current_gate_fingerprint = hashlib.sha256(json.dumps({
                    "run_id": current_run.run_id,
                    "stage": current_run.current_stage.value,
                    "gate_id": current_payload.get("gate_id"),
                    "gate": current_payload.get("gate"),
                    "question": current_payload.get("question"),
                    "options": current_payload.get("options"),
                }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if current_gate_fingerprint != accepted_action.parameters_json.get("gate_fingerprint"):
                # The prior worker may have resolved the gate before a restart.
                # Re-enter the same run without replaying that response into a later stage.
                body.operator_clarification = None
                body.operator_response = None
                body.operator_ack = False
                body.idempotency_key = action_request_id
                response_text = None
    if response_text and active_runs:
        if len(active_runs) != 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active run identity is ambiguous")
        run_repo = uow.orchestration_runs
        active_run = run_repo.get_for_update(active_runs[0].run_id)
        if active_run is None or not active_run.is_active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The active run changed before the gate response was accepted")
        active_payload = get_active_human_payload(active_run)
        recovery_diagnosis = _diagnose_apply_checkpoint_recovery(uow, active_run)
        if recovery_diagnosis is not None:
            active_payload = recovery_gate_payload(active_run, recovery_diagnosis)
            if (
                recovery_diagnosis.get("status") != "RECOVERABLE"
                or response_text.strip() not in {
                    APPLY_RECOVERY_REBASELINE_RESPONSE,
                    APPLY_RECOVERY_PRESERVE_RESPONSE,
                }
            ):
                _persist_projected_human_gate(uow, active_run, active_payload)
                return {
                    "status": "HUMAN_REQUIRED",
                    "run_id": active_run.run_id,
                    "human_payload": active_payload,
                    "message": active_payload["question"],
                }
            if response_text.strip() == APPLY_RECOVERY_PRESERVE_RESPONSE:
                _persist_projected_human_gate(uow, active_run, active_payload)
                return {
                    "status": "HUMAN_REQUIRED",
                    "run_id": active_run.run_id,
                    "human_payload": active_payload,
                    "message": "El Run sigue detenido y el worktree se conserva.",
                }
            _persist_projected_human_gate(uow, active_run, active_payload)
        if not isinstance(active_payload, dict):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There is no current human gate to answer")
        gate_fingerprint = hashlib.sha256(json.dumps({
            "run_id": active_run.run_id,
            "stage": active_run.current_stage.value,
            "gate_id": active_payload.get("gate_id"),
            "gate": active_payload.get("gate"),
            "question": active_payload.get("question"),
            "options": active_payload.get("options"),
        }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        response_fingerprint = hashlib.sha256(response_text.strip().encode()).hexdigest()
        action_request_id = (
            accepted_action.action_request_id
            if accepted_action is not None
            else hashlib.sha256(f"gate-response-token:{body.idempotency_key}".encode()).hexdigest()
            if body.idempotency_key
            else hashlib.sha256(
                f"{active_run.run_id}:{gate_fingerprint}:{response_fingerprint}".encode()
            ).hexdigest()
        )
        action_repo = getattr(uow, "operator_actions", None)
        if action_repo is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Durable operator-action storage is unavailable")
        accepted_action = action_repo.get_by_request_id(action_request_id)
        if accepted_action is None:
            accepted_action = OperatorActionRecord(
                action_request_id=action_request_id,
                project_id=project_id,
                change_name=active_run.change_name,
                run_id=active_run.run_id,
                action_type=OperatorActionType.RESOLVE_GATE,
                precondition_stage=active_run.current_stage.value,
                precondition_gate=str(active_payload.get("gate") or "NEEDS_HUMAN"),
                status="ACCEPTED",
                summary="Accepted response for the current human gate.",
                parameters_json={
                    "gate_fingerprint": gate_fingerprint,
                    "response_fingerprint": response_fingerprint,
                    "accepted_response": redact_secrets(response_text.strip()),
                },
            )
            action_repo.save(accepted_action)
            uow.commit()
        elif accepted_action.parameters_json.get("gate_fingerprint") != gate_fingerprint:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The accepted response belongs to a stale gate")
        if accepted_action.status == "COMPLETED":
            return dict(accepted_action.result_payload_json or {})
        response_text = str(accepted_action.parameters_json.get("accepted_response") or response_text)
        body.operator_clarification = response_text
        body.operator_response = response_text
        body.operator_ack = body.operator_ack or response_text == "Estoy enterado"
        body.idempotency_key = action_request_id
        body.target_run_id = active_run.run_id
    binding = None
    if hasattr(uow, "project_managed_repository_bindings"):
        binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
    if binding is None or not binding.managed_repository_root:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verified managed repository binding is required",
        )

    # Check durable orchestration runs in PostgreSQL during request admission
    active_runs = uow.orchestration_runs.list_runs(project_id=project_id, is_active=True)
    active_run_id = None
    if active_runs:
        active_run = active_runs[0]
        active_run_id = getattr(active_run, "run_id", getattr(active_run, "id", None))
        # Permit re-entry only if target matches or human clarification/ack is provided
        is_reentry = (
            body.target_run_id == active_run_id
            or bool(body.operator_response or body.operator_clarification or body.operator_ack)
        )
        if not is_reentry:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Active run already in progress for project '{project_id}' (run_id={active_run_id})",
            )

    intent_key = body.idempotency_key or f"{project_id}:active"
    operation_id = _accepted_operations.get((project_id, intent_key))
    newly_scheduled = operation_id is None
    if operation_id is None:
        operation_id = _schedule_request_worker(project_id, body, intent_key)
        # The map is deliberately bounded to active intent identities; terminal
        # state remains authoritative in PostgreSQL and recovery can reconcile it.
        _accepted_operations[(project_id, intent_key)] = operation_id
        has_gate_response = bool(
            body.operator_ack or body.operator_response or body.operator_clarification
        )
        if newly_scheduled and has_gate_response and active_run_id is not None:
            await event_broker.publish(
                "run.gate_acknowledged",
                {"project_id": project_id, "run_id": str(active_run_id)},
            )
    return {
        "status": "ACCEPTED",
        "operation_id": operation_id,
        "idempotency_key": client_idempotency_key or (
            accepted_action.action_request_id if accepted_action is not None else None
        ),
        "run_id": None,
        "message": "Run accepted for bounded background execution.",
    }


@app.post("/api/v1/projects/{project_id}/runs/{run_id}/cancel", tags=["orchestration"])
async def cancel_orchestration_run(
    project_id: str,
    run_id: str,
    payload: RunCancellationPayload,
    operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Cancel a settled human-gated Run through the durable operator path."""
    try:
        result = await RunCancellationService(uow).cancel(
            project_id=project_id,
            run_id=run_id,
            reason=payload.reason,
            actor_identity=operator.email,
            source_interface="api",
            idempotency_key=payload.idempotency_key,
        )
    except RunCancellationError as exc:
        message = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if message.startswith("Run not found")
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=message) from exc
    await event_broker.publish("run.cancelled", result)
    return result


@app.get("/api/v1/events", tags=["events"])
async def stream_events(_operator: AuthenticatedOperatorDep) -> StreamingResponse:
    async def stream():
        yield ": connected\n\n"
        async for event in event_broker.subscribe():
            yield event

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/v1/providers/quotas", tags=["providers"])
async def get_provider_quotas(_operator: AuthenticatedOperatorDep) -> dict[str, Any]:
    snapshot = await quota_telemetry.snapshot()
    await event_broker.publish("quota.update", {"providers": snapshot})
    return {"observed_at": datetime.now(UTC).isoformat(), "providers": snapshot}


class ExploreRecoveryAuthorizationPayload(BaseModel):
    prior_attempt_id: str | None = None
    action_request_id: str | None = None


@app.post(
    "/api/v1/projects/{project_id}/runs/{run_id}/explore-recovery-authorizations",
    tags=["requests"],
)
def authorize_explore_recovery(
    project_id: str,
    run_id: str,
    operator: AuthenticatedOperatorDep,
    payload: ExploreRecoveryAuthorizationPayload,
    uow: UowDep,
) -> dict[str, Any]:
    """Record a single authenticated decision to recover an unverifiable Explore."""
    project = uow.projects.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    run = uow.orchestration_runs.get_by_id(run_id)
    if run is None or run.project_id != project_id or not run.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active Run not found")
    details = dict(run.stop_details or {})
    attempt = details.get("explore_attempt")
    if payload.prior_attempt_id is None:
        if (
            attempt is not None
            or details.get("explore_checkpoint") is not None
            or run.current_stage.value != "EXPLORING"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Legacy recovery is allowed only for an Explore Run without prior evidence",
            )
    elif not isinstance(attempt, dict) or attempt.get("attempt_id") != payload.prior_attempt_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Explore attempt does not match Run"
        )
    from minime.adapters.github import GitHubAdapter
    from minime.services.agent_runner import CliAgentRunner
    from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
    from minime.services.worktree_manager import WorktreeManager

    binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
    if binding is None or not binding.managed_repository_root:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verified managed repository binding is required",
        )
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=GitHubAdapter(),
        worktree_manager=WorktreeManager(Path(binding.managed_repository_root), uow=uow),
        agent_runner=CliAgentRunner(),
    )
    if payload.prior_attempt_id is None:
        issue_number = details.get("issue_number")
        provider = coordinator._configured_provider(project, "thinking")
        if not isinstance(issue_number, int) or issue_number <= 0 or not provider:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Legacy Run lacks an authoritative issue or thinking provider binding",
            )
    else:
        issue_number = int(attempt.get("issue_number") or 0)
        provider = str(attempt.get("provider") or "")
    action_request_id = payload.action_request_id or str(uuid4())
    accepted = coordinator.register_recovery_authorization(
        project_id=project_id,
        run_id=run_id,
        authorization_reference=action_request_id,
        actor_identity=operator.email,
        source_interface="api",
        issue_number=issue_number,
        provider=provider,
        prior_attempt_id=payload.prior_attempt_id,
        stage="explore",
    )
    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Explore recovery authorization was rejected",
        )
    return {"action_request_id": action_request_id, "run_id": run_id, "status": "ACCEPTED"}


@app.post(
    "/api/v1/projects/{project_id}/runs/{run_id}/propose-recovery-authorizations",
    tags=["requests"],
)
def authorize_propose_recovery(
    project_id: str,
    run_id: str,
    operator: AuthenticatedOperatorDep,
    payload: ExploreRecoveryAuthorizationPayload,
    uow: UowDep,
) -> dict[str, Any]:
    """Record a single authenticated decision to continue incomplete native Propose."""
    project = uow.projects.get_by_id(project_id)
    run = uow.orchestration_runs.get_by_id(run_id)
    if project is None or run is None or run.project_id != project_id or not run.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active Run not found")
    details = dict(run.stop_details or {})
    attempt = details.get("propose_attempt")
    if payload.prior_attempt_id is not None and (
        not isinstance(attempt, dict) or attempt.get("attempt_id") != payload.prior_attempt_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Propose attempt does not match Run"
        )
    if run.current_stage.value != "PROPOSING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Run is not in Proposing stage"
        )
    from minime.adapters.github import GitHubAdapter
    from minime.services.agent_runner import CliAgentRunner
    from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
    from minime.services.worktree_manager import WorktreeManager

    binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
    if binding is None or not binding.managed_repository_root:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verified managed repository binding is required",
        )
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=GitHubAdapter(),
        worktree_manager=WorktreeManager(Path(binding.managed_repository_root), uow=uow),
        agent_runner=CliAgentRunner(),
    )
    issue_number = int(details.get("issue_number") or (attempt or {}).get("issue_number") or 0)
    provider = coordinator._configured_provider(project, "thinking")
    if issue_number <= 0 or not provider:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run lacks authoritative Issue/provider binding",
        )
    action_request_id = payload.action_request_id or str(uuid4())
    accepted = coordinator.register_recovery_authorization(
        project_id=project_id,
        run_id=run_id,
        authorization_reference=action_request_id,
        actor_identity=operator.email,
        source_interface="api",
        issue_number=issue_number,
        provider=provider,
        prior_attempt_id=payload.prior_attempt_id,
        stage="propose",
    )
    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Propose recovery authorization was rejected",
        )
    return {"action_request_id": action_request_id, "run_id": run_id, "status": "ACCEPTED"}


@app.post(
    "/api/v1/projects/{project_id}/runs/{run_id}/proposal-review-recovery-authorizations",
    tags=["requests"],
)
def authorize_proposal_review_recovery(
    project_id: str,
    run_id: str,
    operator: AuthenticatedOperatorDep,
    payload: ExploreRecoveryAuthorizationPayload,
    uow: UowDep,
) -> dict[str, Any]:
    """Record a single authenticated decision to continue incomplete proposal review."""
    project = uow.projects.get_by_id(project_id)
    run = uow.orchestration_runs.get_by_id(run_id)
    if project is None or run is None or run.project_id != project_id or not run.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active Run not found")
    details = dict(run.stop_details or {})
    attempt = details.get("proposal_review")
    if payload.prior_attempt_id is not None and (
        not isinstance(attempt, dict) or attempt.get("attempt_id") != payload.prior_attempt_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Proposal review attempt does not match Run",
        )
    if run.current_stage.value != "PROPOSAL_REVIEW":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Run is not in Proposal Review stage"
        )
    from minime.adapters.github import GitHubAdapter
    from minime.services.agent_runner import CliAgentRunner
    from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
    from minime.services.worktree_manager import WorktreeManager

    binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
    if binding is None or not binding.managed_repository_root:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verified managed repository binding is required",
        )
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=GitHubAdapter(),
        worktree_manager=WorktreeManager(Path(binding.managed_repository_root), uow=uow),
        agent_runner=CliAgentRunner(),
    )
    issue_number = int(details.get("issue_number") or (attempt or {}).get("issue_number") or 0)
    provider = coordinator._configured_provider(project, "reviewer")
    if issue_number <= 0 or not provider:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run lacks authoritative Issue/provider binding",
        )
    action_request_id = payload.action_request_id or str(uuid4())
    accepted = coordinator.register_recovery_authorization(
        project_id=project_id,
        run_id=run_id,
        authorization_reference=action_request_id,
        actor_identity=operator.email,
        source_interface="api",
        issue_number=issue_number,
        provider=provider,
        prior_attempt_id=payload.prior_attempt_id,
        stage="proposal_review",
    )
    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Proposal review recovery authorization was rejected",
        )
    return {"action_request_id": action_request_id, "run_id": run_id, "status": "ACCEPTED"}


@app.post(
    "/api/v1/projects/{project_id}/runs/{run_id}/code-review-recovery-authorizations",
    tags=["requests"],
)
def authorize_code_review_recovery(
    project_id: str,
    run_id: str,
    operator: AuthenticatedOperatorDep,
    payload: ExploreRecoveryAuthorizationPayload,
    uow: UowDep,
) -> dict[str, Any]:
    """Record a single authenticated decision to continue incomplete code review."""
    project = uow.projects.get_by_id(project_id)
    run = uow.orchestration_runs.get_by_id(run_id)
    if project is None or run is None or run.project_id != project_id or not run.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active Run not found")
    details = dict(run.stop_details or {})
    attempt = details.get("code_review")
    if payload.prior_attempt_id is not None and (
        not isinstance(attempt, dict) or attempt.get("attempt_id") != payload.prior_attempt_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Code review attempt does not match Run"
        )
    if run.current_stage.value != "CODE_REVIEW":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Run is not in Code Review stage"
        )
    from minime.adapters.github import GitHubAdapter
    from minime.services.agent_runner import CliAgentRunner
    from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
    from minime.services.worktree_manager import WorktreeManager

    binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
    if binding is None or not binding.managed_repository_root:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verified managed repository binding is required",
        )
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=GitHubAdapter(),
        worktree_manager=WorktreeManager(Path(binding.managed_repository_root), uow=uow),
        agent_runner=CliAgentRunner(),
    )
    issue_number = int(details.get("issue_number") or (attempt or {}).get("issue_number") or 0)
    provider = coordinator._configured_provider(project, "reviewer")
    if issue_number <= 0 or not provider:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run lacks authoritative Issue/provider binding",
        )
    action_request_id = payload.action_request_id or str(uuid4())
    accepted = coordinator.register_recovery_authorization(
        project_id=project_id,
        run_id=run_id,
        authorization_reference=action_request_id,
        actor_identity=operator.email,
        source_interface="api",
        issue_number=issue_number,
        provider=provider,
        prior_attempt_id=payload.prior_attempt_id,
        stage="code_review",
    )
    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Code review recovery authorization was rejected",
        )
    return {"action_request_id": action_request_id, "run_id": run_id, "status": "ACCEPTED"}


@app.post("/api/v1/projects/{project_id}/requests/ack", status_code=status.HTTP_202_ACCEPTED, tags=["requests"])
async def ack_project_request(
    project_id: str,
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Acknowledge high-complexity PR merge and continue asynchronously."""
    project = uow.projects.get_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
    if binding is None or not binding.managed_repository_root:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verified managed repository binding is required",
        )

    return await run_project_request(
        project_id, _operator, uow, ProjectRequestRunPayload(operator_ack=True)
    )


class JobRunRequest(BaseModel):
    change_name: str
    project_root: str = "."


def _load_version_metadata() -> dict[str, Any]:
    """Load the shipped version.json so /health and the frontend report the same artifact."""
    import json

    version_file = STATIC_DIR / "version.json"
    if version_file.is_file():
        try:
            data = json.loads(version_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (ValueError, OSError):
            pass
    return {}


@app.api_route("/health", methods=["GET", "HEAD"])
def get_health() -> dict[str, Any]:
    healthy, message = db_manager.check_health()
    metadata = _load_version_metadata()
    return {
        "status": "healthy" if healthy else "unhealthy",
        "observed_at": datetime.now(UTC).isoformat(),
        "database": {
            "engine": "PostgreSQL",
            "healthy": healthy,
            "message": message,
        },
        "version": metadata.get("version", "0.1.0"),
        "commit_sha": metadata.get("commit_sha"),
        "build_date": metadata.get("build_date"),
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
    reservations = [r.model_dump() for r in uow.budget_reservations.list_by_project(project_id)]
    ledger = [e.model_dump() for e in uow.budget_ledger.list_by_project(project_id)]
    token_usage = service.get_token_usage_breakdown(project_id)
    return {
        "project_id": project_id,
        "reservations": reservations,
        "ledger": ledger,
        "token_usage_by_model": token_usage,
    }


@app.get("/providers/openrouter/status")
def get_openrouter_status(uow: UowDep, project_id: str | None = None) -> dict[str, Any]:
    if not project_id:
        projects = uow.projects.list_all()
        project_id = projects[0].project_id if projects else ""
    configured = load_config().providers.get("openrouter")
    return {
        "project_id": project_id,
        "provider": "openrouter",
        "configured": bool(configured and configured.enabled),
    }


@app.get("/projects")
def list_projects(
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> list[dict[str, Any]]:
    service = ProjectService(uow)
    return [service.public_project_payload(project) for project in service.list_projects()]




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




# -----------------------------------------------------------------------------
# 021 Project Onboarding and Backlog Intake Endpoints
# -----------------------------------------------------------------------------




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
        code = (
            status.HTTP_404_NOT_FOUND if str(e).endswith("not found.") else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=code, detail=str(e)) from e





























@app.get("/api/v1/orchestration/runs", tags=["orchestration"])
def list_orchestration_runs(
    uow: Annotated[PersistenceUnitOfWork, Depends(get_uow)],
    project_id: str | None = None,
    change_name: str | None = None,
    is_active: bool | None = None,
) -> list[dict[str, Any]]:
    """List historical and active orchestration runs with normalized status and human gate details."""
    runs = uow.orchestration_runs.list_runs(
        project_id=project_id,
        change_name=change_name,
        is_active=is_active,
    )
    results: list[dict[str, Any]] = []
    for r in runs:
        d = r.model_dump()
        stop_details = d.get("stop_details") or {}
        current_stage = getattr(r.current_stage, "value", r.current_stage)
        active_payload = get_active_human_payload(r)
        recovery_diagnosis = _diagnose_apply_checkpoint_recovery(uow, r)
        if recovery_diagnosis is not None:
            active_payload = recovery_gate_payload(r, recovery_diagnosis)
        if active_payload is not None:
            stop_details["human_payload"] = active_payload
        else:
            stop_details.pop("human_payload", None)

        apply_limits = stop_details.get("apply_limits")
        if (
            r.is_active
            and current_stage == "IMPLEMENTING"
            and isinstance(apply_limits, dict)
            and isinstance(stop_details.get("apply_total_attempts"), int)
        ):
            d["apply_cycle"] = {
                "attempts": stop_details["apply_total_attempts"],
                "hard_limit": apply_limits.get("max_attempts"),
                "no_progress": stop_details.get("apply_no_progress", 0),
                "no_progress_limit": apply_limits.get("max_no_progress"),
                "started_by_action_id": stop_details.get("apply_cycle_started_by_action_id"),
            }

        human_gate = getattr(r.human_gate, "value", r.human_gate)
        stop_outcome = getattr(r.stop_outcome, "value", r.stop_outcome)
        is_terminal = stop_outcome in {"COMPLETED", "FAILED", "CANCELLED"} or (
            current_stage == "COMPLETED"
        )
        is_human_required = r.is_active and not is_terminal and (
            bool(active_payload)
            or human_gate == "NEEDS_HUMAN"
            or stop_outcome == "NEEDS_HUMAN"
        )

        # Calculate tokens from budget ledger or stop_details
        tokens = stop_details.get("tokens") or 0
        if not tokens and hasattr(uow, "budget_ledger"):
            change_name = r.change_name
            entries = uow.budget_ledger.list_by_change_id(change_name) if hasattr(uow.budget_ledger, "list_by_change_id") else []
            if entries:
                tokens = sum(e.total_tokens or 0 for e in entries)
        d["tokens"] = tokens

        # Autonomy: if human gate was required or recovery blocked, autonomy is degraded
        has_human_gate = bool(r.human_gate or is_human_required)
        reassignments = getattr(r, "reassignment_count", 0)
        retries = getattr(r, "retry_count", 0)
        if has_human_gate or reassignments > 0 or retries > 1:
            d["autonomy_percent"] = 50.0 if not has_human_gate else 0.0
        else:
            d["autonomy_percent"] = 100.0 if not r.is_active else None

        if is_human_required:
            d["status"] = "HUMAN_REQUIRED"
            d["human_gate"] = "HUMAN_REQUIRED"
        elif stop_outcome == "CANCELLED":
            d["status"] = "CANCELLED"
            d["human_gate"] = None
        elif stop_outcome == "FAILED":
            d["status"] = "FAILED"
            d["human_gate"] = None
        else:
            d["status"] = "RUNNING" if r.is_active else "COMPLETED"
            if r.is_active and not active_payload:
                if human_gate == "NEEDS_HUMAN":
                    d["human_gate"] = None
                if stop_outcome == "NEEDS_HUMAN":
                    d["stop_outcome"] = None
        d["stop_details"] = stop_details
        d["stage"] = r.current_stage.value if r.current_stage else None
        results.append(d)
    return results


# -----------------------------------------------------------------------------
# Operations Dashboard Endpoints
# -----------------------------------------------------------------------------


@app.get(
    "/api/v1/dashboard/overview",
    response_model=DashboardOverviewResponse,
    tags=["dashboard"],
)
def get_dashboard_overview(
    _operator: AuthenticatedOperatorDep,
    uow: UowDep,
    project_id: str | None = None,
) -> DashboardOverviewResponse:
    """Return the authenticated Dashboard read model and ledger-backed costs."""
    selected_project_id = project_id
    if selected_project_id is None:
        projects = uow.projects.list_all()
        selected_project_id = projects[0].project_id if projects else None
    return OperationsDashboardService(uow).get_overview(selected_project_id)










# -----------------------------------------------------------------------------
# Provider Efficiency & Telemetry Endpoints
# -----------------------------------------------------------------------------






# -----------------------------------------------------------------------------
# Preview & Validation Endpoints
# -----------------------------------------------------------------------------







# -----------------------------------------------------------------------------
# Operator Control Plane Endpoints (015)
# -----------------------------------------------------------------------------














# -----------------------------------------------------------------------------
# Queue and Scheduler Endpoints
# -----------------------------------------------------------------------------










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
# Web Push Endpoints (F11)
# -----------------------------------------------------------------------------


class PushSubscriptionPayload(BaseModel):
    endpoint: str
    keys: dict[str, str]  # {"p256dh": "...", "auth": "..."}
    device_label: str | None = None
    categories: dict[str, bool] | None = None

    @field_validator("endpoint")
    @classmethod
    def _endpoint_is_safe_push_url(cls, value: str) -> str:
        """Reject SSRF targets: push endpoints must be https to a non-private host."""
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("push endpoint must be an absolute https URL")
        try:
            addr = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            # Not a literal IP; a hostname is acceptable (resolved by the push gateway).
            return value
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            raise ValueError("push endpoint must not target a private, loopback, or reserved host")
        return value


class PushUnsubscribePayload(BaseModel):
    endpoint: str


class PushTestPayload(BaseModel):
    title: str | None = "Notificación de Prueba — mini me"
    body: str | None = "La conexión de notificaciones Web Push está funcionando correctamente."


@app.get("/api/v1/push/vapid-public-key", tags=["push"])
def get_vapid_public_key(_operator: AuthenticatedOperatorDep) -> dict[str, str]:
    """Return URL-safe base64 uncompressed public key for browser PushManager subscription."""
    return {"public_key": web_push_service.get_public_key_b64()}


@app.post("/api/v1/push/subscriptions", tags=["push"])
def register_push_subscription(
    payload: PushSubscriptionPayload,
    operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Register or update an operator device push subscription."""
    p256dh = payload.keys.get("p256dh")
    auth = payload.keys.get("auth")
    if not p256dh or not auth or not payload.endpoint:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Push subscription requires endpoint, p256dh and auth keys",
        )

    sub = uow.push_subscriptions.save(
        operator_id=operator.email,
        endpoint=payload.endpoint,
        p256dh=p256dh,
        auth=auth,
        device_label=payload.device_label,
        categories=payload.categories,
    )
    uow.commit()
    return {
        "status": "subscribed",
        "subscription_id": getattr(sub, "id", None),
        "operator_id": operator.email,
        "is_active": getattr(sub, "is_active", True),
    }


@app.delete("/api/v1/push/subscriptions", tags=["push"])
def deactivate_push_subscription(
    payload: PushUnsubscribePayload,
    operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Deactivate a push subscription by endpoint."""
    sub = uow.push_subscriptions.get_by_endpoint(payload.endpoint)
    if sub and getattr(sub, "operator_id", None) == operator.email:
        uow.push_subscriptions.deactivate(payload.endpoint, error="Operator unsubscribed")
        uow.commit()
        return {"status": "unsubscribed", "endpoint": payload.endpoint}
    return {"status": "not_found", "endpoint": payload.endpoint}


@app.post("/api/v1/push/test", tags=["push"])
def send_test_push_notification(
    payload: PushTestPayload,
    operator: AuthenticatedOperatorDep,
    uow: UowDep,
) -> dict[str, Any]:
    """Dispatch an immediate test push notification to all active devices of the caller."""
    sent_count = web_push_service.send_to_operator(
        uow=uow,
        operator_id=operator.email,
        title=payload.title or "Notificación de Prueba — mini me",
        body=payload.body or "Conexión Web Push verificada.",
        data={"url": "/trabajo-actual"},
    )
    uow.commit()
    return {
        "status": "sent",
        "sent_count": sent_count,
        "operator_id": operator.email,
    }


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
@app.api_route(
    "/trabajo-actual", methods=["GET", "HEAD"], tags=["dashboard-ui"], response_model=None
)
@app.api_route("/proyectos", methods=["GET", "HEAD"], tags=["dashboard-ui"], response_model=None)
@app.api_route("/backlog", methods=["GET", "HEAD"], tags=["dashboard-ui"], response_model=None)
@app.api_route(
    "/administracion/modelos-proveedores",
    methods=["GET", "HEAD"],
    tags=["dashboard-ui"],
    response_model=None,
)
def get_dashboard_page() -> Response:
    """Serve the operations dashboard single-page web interface."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        # The HTML is the asset manifest for the Angular shell. It must be
        # revalidated on every navigation so a deployment can advance the
        # hashed JS bundle instead of pinning a stale shell in browser/CDN
        # caches. Hashed assets remain cacheable independently.
        return FileResponse(
            index_file,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
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
        return FileResponse(
            sw_file,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    return Response(status_code=404)


@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
def get_favicon_ico() -> Response:
    fav_file = STATIC_DIR / "favicon.ico"
    if fav_file.exists():
        return FileResponse(fav_file, media_type="image/x-icon")
    return Response(status_code=404)


@app.api_route("/favicon.svg", methods=["GET", "HEAD"], include_in_schema=False)
def get_favicon_svg() -> Response:
    fav_file = STATIC_DIR / "favicon.svg"
    if fav_file.exists():
        return FileResponse(fav_file, media_type="image/svg+xml")
    return Response(status_code=404)


@app.api_route("/{file_name:path}", methods=["GET", "HEAD"], include_in_schema=False)
def get_static_root_file(file_name: str) -> Response:
    if STATIC_DIR.exists():
        target = (STATIC_DIR / file_name).resolve()
        if STATIC_DIR.resolve() in target.parents and target.is_file():
            media_type = None
            if file_name.endswith(".js"):
                media_type = "application/javascript"
            elif file_name.endswith(".css"):
                media_type = "text/css"
            elif file_name.endswith(".webmanifest"):
                media_type = "application/manifest+json"
            elif file_name.endswith(".json"):
                media_type = "application/json"
            elif file_name.endswith(".svg"):
                media_type = "image/svg+xml"
            elif file_name.endswith(".ico"):
                media_type = "image/x-icon"
            headers = None
            if file_name in {"ngsw-worker.js", "ngsw.json"}:
                headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}
            return FileResponse(target, media_type=media_type, headers=headers)
    raise HTTPException(status_code=404)
