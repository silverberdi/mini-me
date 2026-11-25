from minime.mcp.security import redact


def test_mcp_diagnostics_are_sanitized_before_event_publication():
    diagnostic = redact({"code": "MCP_AUTH_FAILED", "message": "Authorization: Bearer top-secret"})
    assert "top-secret" not in str(diagnostic)


def test_redacted_diagnostics_are_deterministic_for_retries():
    payload = {"code": "MCP_DOWN", "summary": "endpoint unavailable"}
    assert redact(payload) == redact(payload)
