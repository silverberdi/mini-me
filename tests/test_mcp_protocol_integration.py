import json

import httpx

from minime.mcp.protocol import HTTPMCPTransport, handshake_and_discover


def test_http_handshake_and_tools_list_against_controlled_server():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["method"])
        result = {"tools": [{"name": "stitch_get", "description": "get"}]} if body["method"] == "tools/list" else {"resources": []} if body["method"] == "resources/list" else {"protocolVersion": "2024-11-05"}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    transport = HTTPMCPTransport("https://mcp.test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    discovery = handshake_and_discover(transport)
    assert calls == ["initialize", "tools/list", "resources/list"]
    assert discovery.tools[0]["name"] == "stitch_get"
