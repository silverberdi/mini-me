from minime.mcp.protocol import HTTPMCPTransport, handshake_and_discover
from tests.mcp_controlled_server import ControlledMCPHandler, controlled_server


def test_controlled_mcp_e2e_observes_handshake_discovery_and_effect():
    server, endpoint = controlled_server()
    try:
        transport = HTTPMCPTransport(endpoint)
        discovery = handshake_and_discover(transport)
        result = transport.call_tool("stitch_get", {"screen": "home"})
    finally:
        server.shutdown()
    assert discovery.tools[0]["name"] == "stitch_get"
    assert result["isError"] is False
    assert ControlledMCPHandler.effect == [{"tool": "stitch_get", "arguments": {"screen": "home"}}]
