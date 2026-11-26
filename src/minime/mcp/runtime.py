from __future__ import annotations

import json
import os
import socket
import socketserver
import stat
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from minime.db.models import MCPConnectionModel
from minime.mcp.security import CredentialCipher
from minime.mcp.protocol import MCPProtocolError


@dataclass(frozen=True)
class EphemeralMCPProfile:
    connection_id: str | None
    endpoint: str | None
    transport: str | None
    capabilities: tuple[str, ...]
    relay_path: str | None = None


@dataclass(frozen=True)
class AgentMCPProfile:
    relay_path: str
    working_directory: str | None = None


class MCPRuntimeProfileResolver:
    """Resolves project scope and exposes it to one authorized agent invocation."""

    _active: dict[str, tuple[EphemeralMCPRelay, AgentMCPProfile]] = {}
    _active_lock = threading.Lock()

    def __init__(self, session: Session, cipher: CredentialCipher):
        self.session = session
        self.cipher = cipher
        self._relays: dict[str, EphemeralMCPRelay] = {}

    def resolve(self, project_id: str, run_id: str, agent_id: str, connection_id: str) -> EphemeralMCPProfile:
        row = self.session.scalar(select(MCPConnectionModel).where(MCPConnectionModel.id == connection_id))
        if row is None or row.project_id not in (None, project_id) or row.status != "ACTIVE" or not row.encrypted_credentials:
            raise PermissionError("MCP connection is not active for this project")
        self.cipher.decrypt(row.encrypted_credentials)
        return EphemeralMCPProfile(row.id, row.endpoint, row.transport, tuple(c.name for c in row.capabilities))

    @classmethod
    def agent_profile(cls, run_id: str) -> AgentMCPProfile | None:
        with cls._active_lock:
            active = cls._active.get(run_id)
            return active[1] if active else None

    @classmethod
    def close_active(cls, run_id: str) -> None:
        with cls._active_lock:
            active = cls._active.pop(run_id, None)
        if active:
            active[0].close()

    def prepare(
        self, project_id: str, run_id: str, agent_id: str,
        connection_id: str | None = None, *, relay_parent: str | None = None,
        agent_cwd: str | None = None,
    ) -> EphemeralMCPProfile:
        """Renew eligible connections, then start a private bridge for the run."""
        from minime.mcp.service import MCPConnectionService

        service = MCPConnectionService(self.session, self.cipher)
        if connection_id:
            selected = service.get_accessible(project_id, connection_id)
            if selected is None:
                raise PermissionError("The selected MCP connection is not accessible")
            service.ensure_renewed(project_id, connection_id)

        # Renewal may alter status. Re-resolve before authorizing any tool.
        runtime_capabilities = lambda: service.resolved_capabilities(
            project_id, local_connection_id=connection_id, include_project_locals=False
        )
        capabilities = runtime_capabilities()
        connection_ids = list(dict.fromkeys(item["connection_id"] for item in capabilities))
        if connection_id and connection_id not in connection_ids:
            raise PermissionError("The selected MCP connection has no active observed capability")
        for eligible_id in connection_ids:
            service.ensure_renewed(project_id, eligible_id)
        capabilities = runtime_capabilities()
        if not capabilities:
            self.close(run_id)
            return EphemeralMCPProfile(connection_id, None, None, ())

        parent = relay_parent or "/tmp"
        os.makedirs(parent, mode=0o700, exist_ok=True)
        parent_path = Path(parent)
        if relay_parent is not None and parent_path.is_symlink():
            raise PermissionError("MCP relay parent must be a real directory")
        parent_path = parent_path.resolve(strict=True)
        if not parent_path.is_dir():
            raise PermissionError("MCP relay parent must be a real directory")
        if agent_cwd:
            worktree = Path(agent_cwd).resolve(strict=True)
            if not parent_path.is_relative_to(worktree):
                raise PermissionError("MCP relay must remain inside the assigned worktree")
        previous = self._relays.pop(run_id, None)
        if previous is not None:
            previous.close()
        with self._active_lock:
            old = self._active.pop(run_id, None)
            if old:
                old[0].close()

        bind = self.session.get_bind()
        session_factory = sessionmaker(bind=bind, expire_on_commit=False)
        tools = self._tool_routes(capabilities)
        relay = EphemeralMCPRelay(
            tools=tools,
            invoke=lambda conn_id, tool_name, args: self._invoke(
                session_factory, self.cipher, project_id, run_id, conn_id, tool_name, args
            ),
        )
        effective_cwd = agent_cwd or os.getcwd()
        try:
            relay.start(str(parent_path), client_cwd=effective_cwd)
        except Exception:
            relay.close()
            raise
        self._relays[run_id] = relay
        profile = AgentMCPProfile(relay.client_path, effective_cwd)
        with self._active_lock:
            self._active[run_id] = (relay, profile)
        chosen = connection_ids[0] if connection_ids else connection_id
        row = self.session.get(MCPConnectionModel, chosen) if chosen else None
        return EphemeralMCPProfile(
            chosen, row.endpoint if row else None, row.transport if row else None,
            tuple(item["name"] for item in capabilities), relay_path=relay.path,
        )

    @staticmethod
    def _tool_routes(capabilities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        routes: dict[str, dict[str, Any]] = {}
        for item in capabilities:
            if item.get("kind") != "mcp_tool":
                continue
            connection_id = str(item["connection_id"])
            tool_name = str(item["name"])
            external_name = f"mcp_{connection_id.replace('-', '_')}_{tool_name}"
            routes[external_name] = {
                "connection_id": connection_id,
                "tool_name": tool_name,
                "description": item.get("description") or "",
                "inputSchema": item.get("input_schema") or {"type": "object", "properties": {}},
            }
        return routes

    @staticmethod
    def _invoke(session_factory: Callable[[], Session], cipher: CredentialCipher, project_id: str, run_id: str, connection_id: str, tool: str, arguments: dict[str, Any]):
        from minime.mcp.service import MCPConnectionService

        with session_factory() as session:
            service = MCPConnectionService(session, cipher)
            service.ensure_renewed(project_id, connection_id)
            return service.invoke(project_id, connection_id, tool, arguments, run_id=run_id)

    def close(self, run_id: str) -> None:
        relay = self._relays.pop(run_id, None)
        with self._active_lock:
            active = self._active.pop(run_id, None)
        if relay is not None:
            relay.close()
        elif active is not None:
            active[0].close()

    def invoke(self, project_id: str, run_id: str, agent_id: str, connection_id: str, tool: str, arguments: dict | None = None):
        profile = self.prepare(project_id, run_id, agent_id, connection_id)
        from minime.mcp.service import MCPConnectionService
        row = self.session.get(MCPConnectionModel, profile.connection_id) if profile.connection_id else None
        if row is None:
            raise PermissionError("MCP connection disappeared before invocation")
        try:
            return MCPConnectionService(self.session, self.cipher).invoke(project_id, row.id, tool, arguments)
        except Exception as exc:
            if isinstance(exc, (PermissionError, MCPProtocolError)):
                raise
            raise MCPProtocolError("MCP runtime invocation failed") from exc


class _RelayRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            request = json.loads(self.rfile.readline(1_048_577))
            response = self.server.dispatch(request)  # type: ignore[attr-defined]
        except Exception:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "MCP relay request failed"}}
        if response is not None:
            self.wfile.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")


class _UnixRelayServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, path: str, tools: dict[str, dict[str, Any]], invoke: Callable[..., dict[str, Any]]):
        self.tools = tools
        self.invoke_tool = invoke
        super().__init__(path, _RelayRequestHandler)

    def dispatch(self, request: Any) -> dict[str, Any] | None:
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "mini-me", "version": "0.1"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]} for name, spec in self.tools.items()]}
        elif method == "tools/call":
            external_name = params.get("name")
            spec = self.tools.get(external_name) if isinstance(external_name, str) else None
            if spec is None:
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Tool is not available"}}
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Tool arguments must be an object"}}
            try:
                result = self.invoke_tool(spec["connection_id"], spec["tool_name"], arguments)
            except Exception:
                result = {"isError": True, "content": [{"type": "text", "text": "MCP tool invocation failed"}]}
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not supported"}}
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


class EphemeralMCPRelay:
    """Unix MCP relay with owner-only ACL and bounded lifetime."""

    def __init__(self, *, tools: dict[str, dict[str, Any]] | None = None, invoke: Callable[..., dict[str, Any]] | None = None):
        self._directory: tempfile.TemporaryDirectory[str] | None = None
        self.path = ""
        self.client_path = ""
        self._server: _UnixRelayServer | None = None
        self._thread: threading.Thread | None = None
        self._tools = tools or {}
        self._invoke = invoke or (lambda *_: {})

    def start(self, parent: str | None = None, *, client_cwd: str | None = None) -> str:
        self._directory = tempfile.TemporaryDirectory(prefix="minime-mcp-", dir=parent or "/tmp")
        os.chmod(self._directory.name, 0o700)
        self.path = os.path.join(self._directory.name, "relay.sock")
        bind_path = os.path.relpath(self.path, os.getcwd())
        self.client_path = os.path.relpath(self.path, client_cwd) if client_cwd else self.path
        self._server = _UnixRelayServer(bind_path, self._tools, self._invoke)
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        self._thread = threading.Thread(target=self._server.serve_forever, name="minime-mcp-relay", daemon=True)
        self._thread.start()
        return self.path

    def close(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self._directory:
            self._directory.cleanup()
            self._directory = None
