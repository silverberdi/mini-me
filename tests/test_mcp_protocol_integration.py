import json

from minime.mcp.protocol import HTTPMCPTransport, handshake_and_discover
from tests.mcp_controlled_server import ControlledMCPHandler, controlled_server


def test_http_handshake_and_tools_list_against_controlled_server():
    server, endpoint = controlled_server()
    try:
        discovery = handshake_and_discover(HTTPMCPTransport(endpoint))
    finally:
        server.shutdown()
    assert [call["method"] for call in ControlledMCPHandler.calls] == ["initialize", "tools/list", "resources/list"]
    assert discovery.tools[0]["name"] == "stitch_get"
    assert discovery.resources[0]["name"] == "design://home"
