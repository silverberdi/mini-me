from minime.mcp.protocol import HTTPMCPTransport, handshake_and_discover
from tests.mcp_controlled_server import ControlledMCPHandler, controlled_server


def test_runtime_e2e_invokes_real_tool_and_observes_result_and_effect():
    server, endpoint = controlled_server()
    ControlledMCPHandler.require_auth = True
    try:
        transport = HTTPMCPTransport(endpoint, {"Authorization": "Bearer runtime-ephemeral"})
        discovery = handshake_and_discover(transport)
        assert any(tool["name"] == "stitch_get" for tool in discovery.tools)
        result = transport.call_tool("stitch_get", {"run_id": "run-e2e"})
    finally:
        server.shutdown()
    assert result["content"][0]["text"] == "controlled-result"
    assert ControlledMCPHandler.effect[0]["arguments"]["run_id"] == "run-e2e"
