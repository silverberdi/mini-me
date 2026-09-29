"""Dynamic route census and integration test suite verifying 100% GET query purity."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from minime.api.app import app, get_uow
from minime.domain.enums import (
    CapacitySignalSource,
    EventType,
    ExternalActionStatus,
    ExternalActionType,
    JobStatus,
    ProjectStatus,
    ProviderHealthStatus,
    WorkItemStatus,
)
from minime.domain.models import (
    AuthorizedOperator,
    AuthSession,
    BacklogItem,
    BudgetLedgerEntry,
    BudgetReservation,
    CapacityWindow,
    Change,
    DurableSaga,
    Event,
    Job,
    MetricFact,
    OpenRouterBudgetPolicy,
    OrchestrationExternalAction,
    OrchestrationRun,
    Project,
    ProviderHealth,
    utc_now,
)
from minime.services.auth_service import hash_token

pytest_plugins = ["pytest_asyncio"]

# Contract-authorized Exclusion Register for protocol GET command routes
EXCLUDED_PROTOCOL_COMMAND_ROUTES = {
    "/api/v1/auth/google/login",
    "/api/v1/auth/google/callback",
}

# Deterministic fixture registry for all registered QUERY GET/HEAD route paths
ROUTE_FIXTURE_MAP = {
    "/": "/",
    "/api/v1/auth/me": "/api/v1/auth/me",
    "/api/v1/control-plane/actions/available": "/api/v1/control-plane/actions/available?run_id=run-cqs-123",
    "/api/v1/dashboard/changes/{project_id}/{change_name}": "/api/v1/dashboard/changes/p-cqs-census/sample-change",
    "/api/v1/dashboard/events": "/api/v1/dashboard/events",
    "/api/v1/dashboard/overview": "/api/v1/dashboard/overview",
    "/api/v1/dashboard/runs/{run_id}": "/api/v1/dashboard/runs/run-cqs-123",
    "/api/v1/efficiency/{project_id}": "/api/v1/efficiency/p-cqs-census",
    "/api/v1/efficiency/{project_id}/{change_name}": "/api/v1/efficiency/p-cqs-census/sample-change",
    "/api/v1/openspec/integrity": "/api/v1/openspec/integrity?project_id=p-cqs-census",
    "/api/v1/orchestration/runs": "/api/v1/orchestration/runs",
    "/api/v1/orchestration/{run_id}/status": "/api/v1/orchestration/run-cqs-123/status",
    "/api/v1/previews/changes/{project_id}/{change_name}": "/api/v1/previews/changes/p-cqs-census/sample-change",
    "/api/v1/previews/{preview_id}": "/api/v1/previews/prev-cqs-123",
    "/api/v1/projects/{project_id}": "/api/v1/projects/p-cqs-census",
    "/api/v1/projects/{project_id}/backlog": "/api/v1/projects/p-cqs-census/backlog",
    "/api/v1/projects/{project_id}/backlog/{item_key}": "/api/v1/projects/p-cqs-census/backlog/item-cqs-123",
    "/api/v1/projects/{project_id}/context": "/api/v1/projects/p-cqs-census/context",
    "/api/v1/queue": "/api/v1/queue",
    "/api/v1/queue/{change_name}/explain": "/api/v1/queue/sample-change/explain",
    "/api/v1/runs/{run_id}/actions": "/api/v1/runs/run-cqs-123/actions",
    "/api/v1/runs/{run_id}/actions/history": "/api/v1/runs/run-cqs-123/actions/history",
    "/api/v1/scheduler/status": "/api/v1/scheduler/status",
    "/api/v1/validations/authority/{project_id}/{change_name}": "/api/v1/validations/authority/p-cqs-census/sample-change?head_sha=1234567890abcdef1234567890abcdef12345678&base_sha=4f9ee13bf9e31e2a7b9672d86e1803ccad9d43a7&image_digest=sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
    "/api/v1/validations/scenarios/{project_id}/{change_name}": "/api/v1/validations/scenarios/p-cqs-census/sample-change",
    "/budget/usage": "/budget/usage",
    "/dashboard": "/dashboard",
    "/docs": "/docs",
    "/docs/oauth2-redirect": "/docs/oauth2-redirect",
    "/health": "/health",
    "/jobs/{job_id}": "/jobs/j-cqs-123",
    "/jobs/{job_id}/attempts": "/jobs/j-cqs-123/attempts",
    "/jobs/{job_id}/audit": "/jobs/j-cqs-123/audit",
    "/jobs/{job_id}/blockers": "/jobs/j-cqs-123/blockers",
    "/jobs/{job_id}/diagnostics": "/jobs/j-cqs-123/diagnostics",
    "/jobs/{job_id}/handoffs": "/jobs/j-cqs-123/handoffs",
    "/jobs/{job_id}/logs": "/jobs/j-cqs-123/logs",
    "/jobs/{job_id}/manifest": "/jobs/j-cqs-123/manifest",
    "/jobs/{job_id}/review": "/jobs/j-cqs-123/review",
    "/openapi.json": "/openapi.json",
    "/projects": "/projects",
    "/projects/{project_id}": "/projects/p-cqs-census",
    "/projects/{project_id}/budget": "/projects/p-cqs-census/budget",
    "/projects/{project_id}/changes": "/projects/p-cqs-census/changes",
    "/projects/{project_id}/changes/{change_name}/efficiency": "/projects/p-cqs-census/changes/sample-change/efficiency",
    "/projects/{project_id}/changes/{change_name}/readiness": "/projects/p-cqs-census/changes/sample-change/readiness?project_root=.",
    "/projects/{project_id}/efficiency": "/projects/p-cqs-census/efficiency",
    "/projects/{project_id}/jobs": "/projects/p-cqs-census/jobs",
    "/providers/health": "/providers/health",
    "/providers/openrouter/status": "/providers/openrouter/status",
    "/redoc": "/redoc",
    "/scheduler/status": "/scheduler/status",
    "/status": "/status",
    "/sw.js": "/sw.js",
}


def get_all_get_head_routes() -> list[str]:
    """Dynamically enumerate all GET and HEAD route paths registered in app.routes."""
    routes: set[str] = set()
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        path = getattr(route, "path", "")
        if ("GET" in methods or "HEAD" in methods) and path:
            routes.add(path)
    return sorted(list(routes))


def _get_items(repo, *list_methods):
    if repo is None:
        return []
    for m_name in list_methods:
        if hasattr(repo, m_name):
            try:
                res = getattr(repo, m_name)()
                if res is not None:
                    return res
            except TypeError:
                pass
    if hasattr(repo, "_store"):
        store = getattr(repo, "_store")
        if isinstance(store, dict):
            return list(store.values())
        elif isinstance(store, list):
            return list(store)
    return []


def capture_db_field_snapshot(uow) -> dict[str, list[tuple[Any, ...]]]:
    """Capture full field-level snapshots across canonical domain models."""
    snapshot: dict[str, list[tuple[Any, ...]]] = {}

    # 1. Projects
    projects = _get_items(uow.projects, "list_all")
    snapshot["projects"] = sorted(
        [
            (
                p.project_id,
                p.display_name,
                p.repository,
                p.base_branch,
                p.status.value,
                p.implementer,
                p.reviewer,
            )
            for p in projects
        ]
    )

    # 2. Changes
    changes = _get_items(uow.changes, "list_all")
    snapshot["changes"] = sorted(
        [
            (
                c.project_id,
                c.name,
                c.status.value,
                getattr(c.last_readiness_status, "value", str(c.last_readiness_status)),
                tuple(c.last_readiness_reasons or []),
            )
            for c in changes
        ]
    )

    # 3. Backlog Items
    backlog = _get_items(uow.backlog_items, "list_all")
    snapshot["backlog_items"] = sorted(
        [
            (
                b.project_id,
                b.item_key,
                b.status.value,
                getattr(b.readiness_state, "value", str(b.readiness_state)),
            )
            for b in backlog
        ]
    )

    # 4. Orchestration Runs
    runs = _get_items(uow.orchestration_runs, "list_runs", "list_all")
    snapshot["runs"] = sorted(
        [
            (
                r.run_id,
                r.project_id,
                r.change_name,
                getattr(r.current_stage, "value", str(r.current_stage)),
                r.is_active,
            )
            for r in runs
        ]
    )

    # 5. Jobs
    jobs = _get_items(uow.jobs, "list_active_jobs", "list_all")
    snapshot["jobs"] = sorted(
        [(j.job_id, j.project_id, j.change_name, j.status.value) for j in jobs]
    )

    # 6. Sagas
    sagas = _get_items(uow.durable_sagas, "list_all")
    snapshot["sagas"] = sorted(
        [
            (
                s.id,
                s.project_id,
                s.change_name,
                s.current_phase,
                getattr(s.status, "value", str(s.status)),
            )
            for s in sagas
        ]
    )

    # 7. Events
    events = _get_items(uow.events, "list_events", "list_all")
    snapshot["events"] = sorted(
        [
            (
                e.event_id,
                getattr(e.event_type, "value", str(e.event_type)),
                e.project_id,
                e.change_id,
            )
            for e in events
        ]
    )

    # 8. Provider Health
    healths = _get_items(uow.provider_health, "list_all")
    snapshot["provider_health"] = sorted(
        [
            (
                h.provider,
                getattr(h.status, "value", str(h.status)),
                h.consecutive_failures,
            )
            for h in healths
        ]
    )

    # 9. Auth Sessions
    sessions = _get_items(uow.auth_sessions, "list_all")
    snapshot["auth_sessions"] = sorted(
        [
            (
                s.session_token_hash,
                s.operator_email,
                s.last_seen_at.isoformat() if s.last_seen_at else None,
                s.expires_at.isoformat() if s.expires_at else None,
            )
            for s in sessions
        ]
    )

    # 10. Authorized Operators
    operators = _get_items(uow.authorized_operators, "list_all")
    snapshot["operators"] = sorted([(op.email, op.google_sub, op.is_active) for op in operators])

    # 11. Budget Policies
    b_policies = _get_items(getattr(uow, "budget_policies", None), "list_all")
    snapshot["budget_policies"] = sorted(
        [
            (
                bp.project_id,
                bp.enabled,
                str(bp.daily_cap_usd),
                str(bp.monthly_cap_usd),
                bp.is_breached,
            )
            for bp in b_policies
        ]
    )

    # 12. OrchestrationExternalAction
    ext_actions = _get_items(getattr(uow, "orchestration_external_actions", None), "list_all")
    snapshot["orchestration_external_actions"] = sorted(
        [
            (
                a.action_key,
                a.run_id,
                a.saga_id,
                getattr(a.action_type, "value", str(a.action_type)),
                getattr(a.status, "value", str(a.status)),
                a.candidate_sha,
                a.reconciled_at.isoformat() if a.reconciled_at else None,
                a.remote_identifier,
                a.target_identity,
            )
            for a in ext_actions
        ]
    )

    # 13. MetricFact
    facts = _get_items(getattr(uow, "metrics", None), "list_facts", "list_all")
    snapshot["metric_facts"] = sorted(
        [
            (
                f.metric_name,
                f.project_id,
                f.change_id,
                f.stage,
                f.fact_value,
                f.duration_ms,
                str(sorted(f.details.items())) if f.details else None,
                f.recorded_at.isoformat() if f.recorded_at else None,
            )
            for f in facts
        ]
    )

    # 14. CapacityWindow
    windows = _get_items(getattr(uow, "capacity_windows", None), "list_all")
    snapshot["capacity_windows"] = sorted(
        [
            (
                w.provider,
                w.model,
                w.quota_exhausted_at.isoformat() if w.quota_exhausted_at else None,
                w.capacity_reset_at.isoformat() if w.capacity_reset_at else None,
                w.retry_after_seconds,
                getattr(w.source_signal, "value", str(w.source_signal)),
            )
            for w in windows
        ]
    )

    # 15. BudgetReservation
    reservations = _get_items(getattr(uow, "budget_reservations", None), "list_all")
    snapshot["budget_reservations"] = sorted(
        [
            (
                getattr(r, "reservation_id", getattr(r, "id", None)),
                r.project_id,
                r.job_id,
                r.change_id,
                r.role,
                r.canonical_model_identity,
                str(r.reserved_amount_usd),
                r.status,
                r.pricing_snapshot_id,
            )
            for r in reservations
        ]
    )

    # 16. BudgetLedgerEntry
    ledger_entries = _get_items(getattr(uow, "budget_ledger", None), "list_all")
    snapshot["budget_ledger"] = sorted(
        [
            (
                getattr(e, "entry_id", getattr(e, "id", None)),
                e.reservation_id,
                e.project_id,
                e.job_id,
                e.change_id,
                e.provider,
                e.role,
                e.canonical_model_identity,
                str(e.amount_usd),
                e.entry_type,
            )
            for e in ledger_entries
        ]
    )

    return snapshot


@pytest.fixture
def cqs_test_setup(in_memory_uow):
    uow = in_memory_uow
    now = utc_now()
    raw_token = "cqs_purity_test_token_123456"

    # Seed domain entities for route execution
    proj = Project(
        project_id="p-cqs-census",
        display_name="Census Test Project",
        repository="owner/repo",
        base_branch="main",
        status=ProjectStatus.ACTIVE,
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(proj)

    change = Change(
        project_id="p-cqs-census",
        name="sample-change",
    )
    uow.changes.save(change)

    backlog_item = BacklogItem(
        project_id="p-cqs-census",
        item_key="item-cqs-123",
        title="Census Backlog Item",
        status=WorkItemStatus.BACKLOG,
    )
    uow.backlog_items.save(backlog_item)

    job = Job(
        job_id="j-cqs-123",
        project_id="p-cqs-census",
        change_name="sample-change",
        status=JobStatus.QUEUED,
        implementer_role="codex",
        created_at=now,
        updated_at=now,
    )
    uow.jobs.save(job)

    run = OrchestrationRun(
        run_id="run-cqs-123",
        project_id="p-cqs-census",
        change_name="sample-change",
        base_sha="main",
        current_phase="PENDING",
        active_job_id="j-cqs-123",
        created_at=now,
        updated_at=now,
    )
    uow.orchestration_runs.save(run)

    saga = DurableSaga(
        id="saga-cqs-123",
        project_id="p-cqs-census",
        work_item_key="item-cqs-123",
        change_name="sample-change",
        saga_type="INTAKE",
        current_phase="INITIATED",
        created_at=now,
        updated_at=now,
    )
    uow.durable_sagas.save(saga)

    for prov in ["codex", "antigravity"]:
        uow.provider_health.save(
            ProviderHealth(
                health_id=f"ph-{prov}",
                provider=prov,
                status=ProviderHealthStatus.AVAILABLE,
                updated_at=now,
            )
        )

    if hasattr(uow, "events"):
        uow.events.save(
            Event(
                event_id="evt-cqs-123",
                event_type=EventType.STATUS_CHECKED,
                project_id="p-cqs-census",
                change_id="sample-change",
                timestamp=now,
            )
        )

    if hasattr(uow, "budget_policies"):
        uow.budget_policies.save(
            OpenRouterBudgetPolicy(
                project_id="p-cqs-census",
                daily_cap_usd=Decimal("10.0"),
                updated_at=now,
            )
        )

    # Seed representative records for the 5 additional durable stores
    # 1. OrchestrationExternalAction
    action = OrchestrationExternalAction(
        action_id="act-cqs-123",
        run_id="run-cqs-123",
        saga_id="saga-cqs-123",
        action_key="git_push:p-cqs-census:sample-change:sha123",
        action_type=ExternalActionType.BRANCH_PUSH,
        target_identity="github.com/owner/repo",
        request_fingerprint="fp123",
        candidate_sha="1234567890abcdef1234567890abcdef12345678",
        status=ExternalActionStatus.RESERVED,
        created_at=now,
        updated_at=now,
    )
    if hasattr(uow, "orchestration_external_actions"):
        uow.orchestration_external_actions.reserve(action)

    # 2. MetricFact
    fact = MetricFact(
        fact_id="mf-cqs-123",
        metric_name="cycle_time",
        project_id="p-cqs-census",
        change_id="sample-change",
        stage="IMPLEMENTING",
        fact_value=42.0,
        recorded_at=now,
    )
    if hasattr(uow, "metrics"):
        uow.metrics.save(fact)

    # 3. CapacityWindow
    window = CapacityWindow(
        window_id="cw-cqs-123",
        provider="codex",
        model="codex-5",
        quota_exhausted_at=now,
        retry_after_seconds=60,
        source_signal=CapacitySignalSource.HEADER_RETRY_AFTER,
        created_at=now,
    )
    if hasattr(uow, "capacity_windows"):
        uow.capacity_windows.save(window)

    # 4. BudgetReservation
    reservation = BudgetReservation(
        reservation_id="res-cqs-123",
        project_id="p-cqs-census",
        job_id="j-cqs-123",
        change_id="sample-change",
        role="implementer",
        canonical_model_identity="openai/gpt-4o",
        reserved_amount_usd=Decimal("0.50"),
        status="RESERVED",
        pricing_snapshot_id="ps-123",
        created_at=now,
        updated_at=now,
    )
    if hasattr(uow, "budget_reservations"):
        uow.budget_reservations.save(reservation)

    # 5. BudgetLedgerEntry
    ledger_entry = BudgetLedgerEntry(
        entry_id="ble-cqs-123",
        reservation_id="res-cqs-123",
        project_id="p-cqs-census",
        job_id="j-cqs-123",
        change_id="sample-change",
        provider="openrouter",
        role="implementer",
        canonical_model_identity="openai/gpt-4o",
        amount_usd=Decimal("0.25"),
        entry_type="RESERVATION_SETTLED",
        created_at=now,
    )
    if hasattr(uow, "budget_ledger"):
        uow.budget_ledger.save(ledger_entry)

    operator = AuthorizedOperator(
        email="cqsop@example.com",
        display_name="CQS Operator",
        is_active=True,
    )
    uow.authorized_operators.save(operator)

    session = AuthSession(
        session_token_hash=hash_token(raw_token),
        operator_email="cqsop@example.com",
        created_at=now,
        expires_at=now + timedelta(days=1),
        last_seen_at=now,
    )
    uow.auth_sessions.save(session)
    uow.commit()

    lock_queries: list[str] = []
    orig_ph_for_update = uow.provider_health.get_by_provider_for_update

    def spy_ph_for_update(provider: str):
        lock_queries.append(f"provider_health.get_by_provider_for_update({provider})")
        return orig_ph_for_update(provider)

    uow.provider_health.get_by_provider_for_update = spy_ph_for_update

    orig_budget_for_update = uow.budget_policies.get_for_update

    def spy_budget_for_update(project_id: str):
        lock_queries.append(f"budget_policies.get_for_update({project_id})")
        return orig_budget_for_update(project_id)

    uow.budget_policies.get_for_update = spy_budget_for_update

    orig_saga_for_update = uow.durable_sagas.get_for_update

    def spy_saga_for_update(saga_id: str):
        lock_queries.append(f"durable_sagas.get_for_update({saga_id})")
        return orig_saga_for_update(saga_id)

    uow.durable_sagas.get_for_update = spy_saga_for_update

    def _get_uow_override():
        return uow

    app.dependency_overrides[get_uow] = _get_uow_override
    client = TestClient(app)
    yield client, uow, raw_token, lock_queries
    app.dependency_overrides.clear()


def test_route_census_inventory_and_exclusion_classification():
    all_routes = get_all_get_head_routes()
    assert len(all_routes) > 0, "No GET/HEAD routes enumerated from app.routes!"

    query_routes = [r for r in all_routes if r not in EXCLUDED_PROTOCOL_COMMAND_ROUTES]
    excluded_routes = [r for r in all_routes if r in EXCLUDED_PROTOCOL_COMMAND_ROUTES]

    assert len(query_routes) > 0
    # Verify exact excluded protocol routes
    for exc in EXCLUDED_PROTOCOL_COMMAND_ROUTES:
        assert exc in excluded_routes or any(r == exc for r in all_routes)


def test_dynamic_get_route_census_purity(cqs_test_setup):
    client, uow, raw_token, lock_queries = cqs_test_setup
    all_routes = get_all_get_head_routes()
    query_routes = [r for r in all_routes if r not in EXCLUDED_PROTOCOL_COMMAND_ROUTES]

    headers = {"Authorization": f"Bearer {raw_token}"}

    executed_count = 0
    for route_path in query_routes:
        # Require fixture mapping for every query GET/HEAD route (0 silent skips permitted!)
        assert route_path in ROUTE_FIXTURE_MAP, (
            f"Route {route_path} has no fixture in ROUTE_FIXTURE_MAP!"
        )

        test_path = ROUTE_FIXTURE_MAP[route_path]
        assert "{" not in test_path and "}" not in test_path, (
            f"Test path for {route_path} contains unreplaced placeholders: {test_path}"
        )

        lock_queries.clear()
        before_snapshot = capture_db_field_snapshot(uow)

        response = client.get(test_path, headers=headers)

        # 422 is parameter validation rejection BEFORE handler execution, which does NOT prove purity!
        assert response.status_code != 422, (
            f"Route {test_path} (from {route_path}) failed parameter validation with 422: {response.text}"
        )
        assert response.status_code in {200, 307, 404}, (
            f"Route {test_path} returned unexpected status {response.status_code}: {response.text}"
        )

        # Assert zero write locks executed
        assert len(lock_queries) == 0, f"Route {test_path} executed write locks: {lock_queries}"

        # Assert zero DB field mutations
        after_snapshot = capture_db_field_snapshot(uow)
        assert before_snapshot == after_snapshot, (
            f"Route {test_path} mutated DB snapshot:\nBefore: {before_snapshot}\nAfter: {after_snapshot}"
        )

        executed_count += 1

    assert executed_count == len(query_routes), (
        f"Executed {executed_count} query handlers, expected {len(query_routes)}"
    )


def test_db_field_snapshot_detects_mutation(cqs_test_setup):
    """Negative-control unit test verifying snapshot detects DB model field mutations."""
    _, uow, _, _ = cqs_test_setup
    before = capture_db_field_snapshot(uow)

    # Prove snapshot captures non-empty data across all 14 stores
    for key, records in before.items():
        assert len(records) > 0, (
            f"Snapshot store '{key}' is empty! Test fixture must seed representative records."
        )

    # Mutate a record in one of the new stores
    uow.metrics.save(
        MetricFact(
            fact_id="mf-cqs-mutation-test",
            metric_name="mutation_test_metric",
            project_id="p-cqs-census",
            change_id="sample-change",
            fact_value=999.0,
            recorded_at=utc_now(),
        )
    )
    after = capture_db_field_snapshot(uow)
    assert before != after, "capture_db_field_snapshot failed to detect DB mutation!"
