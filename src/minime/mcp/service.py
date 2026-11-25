from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from minime.db.models import MCPCapabilityModel, MCPConnectionModel
from minime.mcp.protocol import HTTPMCPTransport, MCPProtocolError, StdioMCPTransport, handshake_and_discover
from minime.mcp.security import CredentialCipher, redact


class MCPConnectionService:
    """Small application service: persistence, protocol validation and revocation."""

    def __init__(self, session: Session, cipher: CredentialCipher | None = None):
        self.session = session
        self.cipher = cipher

    def list(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.session.scalars(select(MCPConnectionModel).where(MCPConnectionModel.project_id == project_id)).all()
        return [self.public(row) for row in rows]

    @staticmethod
    def public(row: MCPConnectionModel) -> dict[str, Any]:
        return {"id": row.id, "name": row.name, "endpoint": row.endpoint, "transport": row.transport, "auth_type": row.auth_type, "status": row.status, "diagnostic": {"code": row.diagnostic_code, "summary": row.diagnostic_summary} if row.diagnostic_code else None, "capabilities": [{"kind": c.kind, "name": c.name, "description": c.description, "observed_at": c.observed_at.isoformat()} for c in row.capabilities]}

    def create(self, project_id: str, payload: dict[str, Any]) -> MCPConnectionModel:
        if self.cipher is None:
            raise RuntimeError("MCP credential cipher is required")
        credentials = payload.get("credentials") or {}
        row = MCPConnectionModel(id=str(uuid4()), project_id=project_id, name=payload["name"].strip(), endpoint=payload["endpoint"].strip(), transport=payload["transport"], auth_type=payload["auth_type"], encrypted_credentials=self.cipher.encrypt(credentials))
        self.session.add(row)
        self.session.flush()
        try:
            discovery = self.discover(row)
            row.status = "ACTIVE"
            row.diagnostic_code = None
            row.diagnostic_summary = None
            self._replace_capabilities(row, discovery.tools, discovery.resources)
        except Exception as exc:
            row.status = "ERROR"
            row.diagnostic_code = "MCP_VALIDATION_FAILED"
            row.diagnostic_summary = str(redact(str(exc)))[:500]
        self.session.commit()
        self.session.refresh(row)
        return row

    def _transport(self, row: MCPConnectionModel):
        credentials = self.cipher.decrypt(row.encrypted_credentials or b"") if self.cipher else {}
        headers = {}
        if row.auth_type == "bearer": headers["Authorization"] = f"Bearer {credentials.get('token', '')}"
        if row.auth_type == "api_key": headers[credentials.get("header", "X-API-Key")] = credentials.get("key", "")
        if row.transport in ("http", "sse"): return HTTPMCPTransport(row.endpoint, headers)
        return StdioMCPTransport(credentials.get("command", []))

    def discover(self, row: MCPConnectionModel):
        return handshake_and_discover(self._transport(row))

    def _replace_capabilities(self, row, tools, resources):
        self.session.execute(delete(MCPCapabilityModel).where(MCPCapabilityModel.connection_id == row.id))
        for kind, values in (("tool", tools), ("resource", resources)):
            for value in values:
                name = str(value.get("name", "")).strip()
                if not name: continue
                self.session.add(MCPCapabilityModel(id=str(uuid4()), connection_id=row.id, kind=kind, name=name, description=str(value.get("description", ""))[:1000], metadata_json=redact({k: v for k, v in value.items() if k not in {"name", "description"}})))

    def revoke(self, project_id: str, connection_id: str) -> bool:
        row = self.session.scalar(select(MCPConnectionModel).where(MCPConnectionModel.project_id == project_id, MCPConnectionModel.id == connection_id))
        if not row or row.status == "REVOKED": return False
        row.encrypted_credentials = None
        row.status = "REVOKED"
        self.session.execute(delete(MCPCapabilityModel).where(MCPCapabilityModel.connection_id == row.id))
        self.session.commit()
        return True

    def delete(self, project_id: str, connection_id: str) -> bool:
        row = self.session.scalar(select(MCPConnectionModel).where(MCPConnectionModel.project_id == project_id, MCPConnectionModel.id == connection_id))
        if not row: return False
        self.session.delete(row)
        self.session.commit()
        return True

    @staticmethod
    def new_oauth_state() -> tuple[str, str, datetime]:
        state = secrets.token_urlsafe(32)
        return state, hashlib.sha256(state.encode()).hexdigest(), datetime.now(UTC) + timedelta(minutes=10)
