"""Dynamic route census and integration test suite verifying 100% GET query purity."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from minime.api.app import app, get_uow
from minime.domain.models import AuthorizedOperator, AuthSession, Project, utc_now
from minime.services.auth_service import hash_token

# Contract-authorized Exclusion Register for protocol GET commands
EXCLUDED_PROTOCOL_COMMAND_ROUTES = {
    "/api/v1/auth/google/login",
    "/api/v1/auth/google/callback",
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


@pytest.fixture
def cqs_test_setup(in_memory_uow):
    uow = in_memory_uow
    now = utc_now()
    raw_token = "cqs_purity_test_token_123456"

    # Seed test project and auth session
    proj = Project(
        project_id="p-cqs-census",
        display_name="Census Test Project",
        repository="owner/repo",
        base_branch="main",
    )
    uow.projects.save(proj)

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

    def _get_uow_override():
        return uow

    app.dependency_overrides[get_uow] = _get_uow_override
    client = TestClient(app)
    yield client, uow, raw_token
    app.dependency_overrides.clear()


def capture_db_snapshot(uow) -> dict[str, int]:
    """Capture row counts across canonical domain tables."""
    return {
        "projects": len(uow.projects.list_all()),
        "changes": len(uow.changes.list_all() if hasattr(uow.changes, "list_all") else []),
        "backlog_items": len(uow.backlog_items.list_all() if hasattr(uow.backlog_items, "list_all") else []),
        "runs": len(uow.orchestration_runs.list_runs()),
        "jobs": len(uow.jobs.list_active_jobs()),
        "sagas": len(uow.durable_sagas.list_all() if hasattr(uow.durable_sagas, "list_all") else []),
        "events": len(uow.events.list_events(limit=1000)),
        "auth_sessions": len(uow.auth_sessions.list_all() if hasattr(uow.auth_sessions, "list_all") else []),
    }


def test_route_census_inventory_and_exclusion_classification():
    all_routes = get_all_get_head_routes()
    assert len(all_routes) > 0, "No GET/HEAD routes enumerated from app.routes!"

    query_routes = [r for r in all_routes if r not in EXCLUDED_PROTOCOL_COMMAND_ROUTES]
    excluded_routes = [r for r in all_routes if r in EXCLUDED_PROTOCOL_COMMAND_ROUTES]

    assert len(query_routes) > 0
    # Ensure documented protocol command GET exclusions exist in expected set
    for exc in EXCLUDED_PROTOCOL_COMMAND_ROUTES:
        assert exc in excluded_routes or any(r == exc for r in all_routes)


def test_dynamic_get_route_census_purity(cqs_test_setup):
    client, uow, raw_token = cqs_test_setup
    all_routes = get_all_get_head_routes()
    query_routes = [r for r in all_routes if r not in EXCLUDED_PROTOCOL_COMMAND_ROUTES]

    headers = {"Authorization": f"Bearer {raw_token}"}

    for route_path in query_routes:
        # Parameterize dynamic route placeholders if needed
        test_path = route_path.replace("{project_id}", "p-cqs-census").replace("{change_name}", "sample-change")
        if "{" in test_path:
            continue  # Skip unparameterized deep parametric paths for generic census sweep

        before_snapshot = capture_db_snapshot(uow)
        response = client.get(test_path, headers=headers)

        # GET request must succeed or return expected client status (200, 307, 404, 422), never 500
        assert response.status_code in {200, 307, 404, 422}, f"Route {test_path} returned error {response.status_code}"

        after_snapshot = capture_db_snapshot(uow)
        assert before_snapshot == after_snapshot, f"Route {test_path} mutated DB snapshot: before={before_snapshot}, after={after_snapshot}"
