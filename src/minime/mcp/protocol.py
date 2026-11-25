from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class MCPProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class MCPDiscovery:
    tools: list[dict[str, Any]]
    resources: list[dict[str, Any]]


class MCPTransport(Protocol):
    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]: ...


def _request_payload(method: str, params: dict[str, Any] | None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


class HTTPMCPTransport:
    def __init__(self, endpoint: str, headers: dict[str, str] | None = None, client: httpx.Client | None = None):
        self.endpoint = endpoint
        self.headers = headers or {}
        self.client = client or httpx.Client(timeout=10.0)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self.client.post(self.endpoint, json=_request_payload(method, params), headers=self.headers)
        except httpx.HTTPError as exc:
            raise MCPProtocolError("MCP endpoint unavailable") from exc
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise MCPProtocolError(str(body["error"].get("message", "MCP request failed")))
        result = body.get("result")
        if not isinstance(result, dict):
            raise MCPProtocolError("MCP response has invalid result")
        return result

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})


class StdioMCPTransport:
    def __init__(self, command: list[str]):
        if not command:
            raise ValueError("stdio command is required")
        self.command = command

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        process = subprocess.run(
            self.command,
            input=json.dumps(_request_payload(method, params)) + "\n",
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if process.returncode:
            raise MCPProtocolError("MCP stdio process failed")
        try:
            body = json.loads(process.stdout.splitlines()[0])
            if "error" in body:
                raise MCPProtocolError("MCP stdio request failed")
            return body["result"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise MCPProtocolError("MCP stdio response is invalid") from exc

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})


def handshake_and_discover(transport: MCPTransport) -> MCPDiscovery:
    transport.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "mini-me", "version": "0.1"}})
    tools = transport.request("tools/list").get("tools", [])
    resources = transport.request("resources/list").get("resources", [])
    if not isinstance(tools, list) or not isinstance(resources, list):
        raise MCPProtocolError("MCP discovery has invalid capabilities")
    return MCPDiscovery(tools=[x for x in tools if isinstance(x, dict)], resources=[x for x in resources if isinstance(x, dict)])
