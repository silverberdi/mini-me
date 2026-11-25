import pytest

from minime.mcp.auth import validate_token_credentials
from minime.mcp.protocol import HTTPMCPTransport, handshake_and_discover
from tests.mcp_controlled_server import ControlledMCPHandler, controlled_server


def test_token_auth_requires_material():
    validate_token_credentials("api_key", {"key": "k"})
    validate_token_credentials("bearer", {"token": "t"})
    with pytest.raises(ValueError):
        validate_token_credentials("bearer", {})


def test_bearer_transport_sends_authentication_to_controlled_server():
    server, endpoint = controlled_server()
    ControlledMCPHandler.require_auth = True
    try:
        discovery = handshake_and_discover(HTTPMCPTransport(endpoint, {"Authorization": "Bearer ephemeral"}))
    finally:
        server.shutdown()
    assert discovery.tools[0]["name"] == "stitch_get"
