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


@dataclass(frozen=True)
class EphemeralMCPProfile:
    connection_id: str
    endpoint: str
    transport: str
    capabilities: tuple[str, ...]


class MCPRuntimeProfileResolver:
    """Authorizes a project/run/agent tuple without putting secrets in argv."""

    def __init__(self, session: Session, cipher: CredentialCipher):
        self.session = session
        self.cipher = cipher

    def resolve(self, project_id: str, run_id: str, agent_id: str, connection_id: str) -> EphemeralMCPProfile:
        row = self.session.scalar(select(MCPConnectionModel).where(MCPConnectionModel.id == connection_id, MCPConnectionModel.project_id == project_id))
        if row is None or row.status != "ACTIVE" or not row.encrypted_credentials:
            raise PermissionError("MCP connection is not active for this project")
        self.cipher.decrypt(row.encrypted_credentials)
        return EphemeralMCPProfile(row.id, row.endpoint, row.transport, tuple(c.name for c in row.capabilities))


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
