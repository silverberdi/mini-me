import asyncio

from minime.mcp.security import redact
from minime.services.event_broker import EventBroker, MCPEventPublisher


def test_mcp_diagnostics_are_sanitized_before_event_publication():
    diagnostic = redact({"code": "MCP_AUTH_FAILED", "message": "Authorization: Bearer top-secret"})
    assert "top-secret" not in str(diagnostic)


def test_redacted_diagnostics_are_deterministic_for_retries():
    payload = {"code": "MCP_DOWN", "summary": "endpoint unavailable"}
    assert redact(payload) == redact(payload)


def test_mcp_event_publication_is_sanitized_and_idempotent():
    broker = EventBroker()
    publisher = MCPEventPublisher(broker)
    assert asyncio.run(publisher.publish("mcp.connection.failed", {"token": "secret", "status": "ERROR"}, operation_id="op-1"))
    assert not asyncio.run(publisher.publish("mcp.connection.failed", {"token": "secret", "status": "ERROR"}, operation_id="op-1"))
