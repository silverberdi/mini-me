"""Acceptance tests for the runtime diagnostic health header."""

from datetime import datetime
from unittest.mock import patch

from fastapi import Response

from minime.api.app import app, get_health


def invoke_api_health() -> Response:
    api_health_routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/health"
        and "GET" in getattr(route, "methods", set())
    ]
    assert len(api_health_routes) == 1

    response = Response()
    with patch("minime.api.app.db_manager.check_health", return_value=(True, "ok")):
        get_health(response)
    return response


def test_api_health_includes_iso_runtime_diagnostic_header() -> None:
    response = invoke_api_health()

    diagnostic_timestamp = datetime.fromisoformat(response.headers["X-Runtime-Diagnostic"])
    assert diagnostic_timestamp.tzinfo is not None


def test_api_health_runtime_diagnostic_timestamp_is_generated_per_response() -> None:
    first_response = invoke_api_health()
    second_response = invoke_api_health()

    assert (
        first_response.headers["X-Runtime-Diagnostic"]
        != second_response.headers["X-Runtime-Diagnostic"]
    )
