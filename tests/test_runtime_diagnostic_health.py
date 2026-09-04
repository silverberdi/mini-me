"""Acceptance tests for the runtime diagnostic health header."""

from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from minime.api.app import app


def test_api_health_includes_iso_runtime_diagnostic_header() -> None:
    with (
        patch("minime.api.app.db_manager.check_health", return_value=(True, "ok")),
        TestClient(app) as client,
    ):
        response = client.get("/api/health")

    assert response.status_code == 200
    diagnostic_timestamp = datetime.fromisoformat(response.headers["X-Runtime-Diagnostic"])
    assert diagnostic_timestamp.tzinfo is not None


def test_api_health_runtime_diagnostic_timestamp_is_generated_per_response() -> None:
    with (
        patch("minime.api.app.db_manager.check_health", return_value=(True, "ok")),
        TestClient(app) as client,
    ):
        first_response = client.get("/api/health")
        second_response = client.get("/api/health")

    assert (
        first_response.headers["X-Runtime-Diagnostic"]
        != second_response.headers["X-Runtime-Diagnostic"]
    )
