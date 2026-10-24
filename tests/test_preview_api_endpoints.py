"""Negative regressions for preview/validation writes deferred to F5."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from minime.api.app import app, get_uow


@pytest.fixture
def client(in_memory_uow):
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    try:
        yield TestClient(app), in_memory_uow
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/api/v1/previews/build", {"project_id": "p", "change_name": "c"}),
        ("POST", "/api/v1/previews/start", {"preview_id": "p"}),
        ("POST", "/api/v1/previews/p/teardown", {}),
        ("POST", "/api/v1/previews/reconcile", {}),
        ("POST", "/api/v1/validations/submit", {"project_id": "p"}),
    ],
)
def test_deferred_preview_and_validation_writes_are_explicitly_unavailable(
    client, method, path, payload
):
    http, uow = client
    before = (
        len(uow.preview_sessions._store),
        len(uow.validation_runs._store),
        len(uow.events._store),
    )
    response = http.request(method, path, json=payload)

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "operation_unavailable"
    assert before == (
        len(uow.preview_sessions._store),
        len(uow.validation_runs._store),
        len(uow.events._store),
    )
