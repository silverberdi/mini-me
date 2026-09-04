"""Acceptance tests for the runtime diagnostic health header."""

from datetime import datetime
from typing import Any
from unittest.mock import patch

from fastapi import Response

from minime.api.app import app, get_health


def invoke_api_health() -> tuple[Response, dict[str, Any]]:
    api_health_routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/health"
        and "GET" in getattr(route, "methods", set())
    ]
    assert len(api_health_routes) == 1
    assert api_health_routes[0].endpoint is get_health

    response = Response()
    with patch("minime.api.app.db_manager.check_health", return_value=(True, "ok")):
        payload = api_health_routes[0].endpoint(response)
    return response, payload


def test_api_health_includes_iso_runtime_diagnostic_header() -> None:
    response, payload = invoke_api_health()

    assert payload["status"] == "healthy"
    diagnostic_timestamp = datetime.fromisoformat(response.headers["X-Runtime-Diagnostic"])
    assert diagnostic_timestamp.tzinfo is not None


def test_api_health_runtime_diagnostic_timestamp_is_generated_per_response() -> None:
    first_response, _ = invoke_api_health()
    second_response, _ = invoke_api_health()

    assert (
        first_response.headers["X-Runtime-Diagnostic"]
        != second_response.headers["X-Runtime-Diagnostic"]
    )
