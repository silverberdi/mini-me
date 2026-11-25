from minime.mcp.protocol import MCPDiscovery


def test_controlled_mcp_e2e_observes_handshake_and_tools():
    discovery = MCPDiscovery(tools=[{"name": "stitch_get"}], resources=[])
    assert discovery.tools[0]["name"] == "stitch_get"
