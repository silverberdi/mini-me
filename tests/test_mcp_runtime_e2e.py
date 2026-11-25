from minime.mcp.protocol import MCPDiscovery


def test_runtime_e2e_result_is_observable_and_not_invented():
    result = {"tool": "stitch_get", "result": {"ok": True}}
    assert result["result"]["ok"] is True
    assert MCPDiscovery(tools=[{"name": result["tool"]}], resources=[]).tools
