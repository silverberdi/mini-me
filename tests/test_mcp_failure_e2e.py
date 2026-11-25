import pytest

from minime.mcp.protocol import HTTPMCPTransport, MCPProtocolError
from tests.mcp_controlled_server import ControlledMCPHandler, controlled_server


def test_invalid_credential_is_fail_closed_against_real_server():
    server, endpoint = controlled_server()
    ControlledMCPHandler.invalid_auth = True
    try:
        with pytest.raises(MCPProtocolError, match="invalid credential"):
            HTTPMCPTransport(endpoint).request("initialize")
    finally:
        server.shutdown()


def test_endpoint_down_is_fail_closed():
    server, endpoint = controlled_server()
    server.shutdown()
    with pytest.raises(MCPProtocolError, match="endpoint unavailable"):
        HTTPMCPTransport(endpoint).request("initialize")
