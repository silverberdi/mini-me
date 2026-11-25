from __future__ import annotations

import os
import socket
import stat
import tempfile
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from minime.db.models import MCPConnectionModel
from minime.mcp.security import CredentialCipher
from minime.mcp.protocol import MCPProtocolError


@dataclass(frozen=True)
class EphemeralMCPProfile:
    connection_id: str
    endpoint: str
    transport: str
    capabilities: tuple[str, ...]
    relay_path: str | None = None


class MCPRuntimeProfileResolver:
    """Authorizes a project/run/agent tuple without putting secrets in argv."""

    def __init__(self, session: Session, cipher: CredentialCipher):
        self.session = session
        self.cipher = cipher
        self._relays: dict[str, EphemeralMCPRelay] = {}

    def resolve(self, project_id: str, run_id: str, agent_id: str, connection_id: str) -> EphemeralMCPProfile:
        row = self.session.scalar(select(MCPConnectionModel).where(MCPConnectionModel.id == connection_id, MCPConnectionModel.project_id == project_id))
        if row is None or row.status != "ACTIVE" or not row.encrypted_credentials:
            raise PermissionError("MCP connection is not active for this project")
        self.cipher.decrypt(row.encrypted_credentials)
        return EphemeralMCPProfile(row.id, row.endpoint, row.transport, tuple(c.name for c in row.capabilities))

    def prepare(self, project_id: str, run_id: str, agent_id: str, connection_id: str) -> EphemeralMCPProfile:
        """Authoritative Run boundary: renew first, then issue an ephemeral profile."""
        from minime.mcp.service import MCPConnectionService

        MCPConnectionService(self.session, self.cipher).ensure_renewed(project_id, connection_id)
        previous = self._relays.pop(run_id, None)
        if previous is not None:
            previous.close()
        relay = EphemeralMCPRelay()
        self._relays[run_id] = relay
        profile = self.resolve(project_id, run_id, agent_id, connection_id)
        return EphemeralMCPProfile(
            profile.connection_id, profile.endpoint, profile.transport, profile.capabilities,
            relay_path=relay.start(),
        )

    def close(self, run_id: str) -> None:
        relay = self._relays.pop(run_id, None)
        if relay is not None:
            relay.close()

    def invoke(self, project_id: str, run_id: str, agent_id: str, connection_id: str, tool: str, arguments: dict | None = None):
        profile = self.prepare(project_id, run_id, agent_id, connection_id)
        row = self.session.get(MCPConnectionModel, profile.connection_id)
        from minime.mcp.service import MCPConnectionService
        if row is None:
            raise PermissionError("MCP connection disappeared before invocation")
        try:
            return MCPConnectionService(self.session, self.cipher).invoke(project_id, row.id, tool, arguments)
        except Exception as exc:
            if isinstance(exc, (PermissionError, MCPProtocolError)):
                raise
            raise MCPProtocolError("MCP runtime invocation failed") from exc


class EphemeralMCPRelay:
    """Unix relay with owner-only ACL and bounded lifetime."""

    def __init__(self):
        self._directory = tempfile.TemporaryDirectory(prefix="minime-mcp-")
        self.path = os.path.join(self._directory.name, "relay.sock")
        self._socket: socket.socket | None = None

    def start(self) -> str:
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.bind(self.path)
        os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        self._socket.listen(1)
        return self.path

    def close(self) -> None:
        if self._socket:
            self._socket.close()
            self._socket = None
        self._directory.cleanup()
