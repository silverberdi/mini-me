from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from minime.db.models import MCPCapabilityModel, MCPConnectionModel
from minime.mcp.protocol import HTTPMCPTransport, MCPProtocolError, StdioMCPTransport, handshake_and_discover
from minime.mcp.auth import OAuthClient, validate_token_credentials
from minime.mcp.security import CredentialCipher, redact


class MCPConnectionService:
    """Small application service: persistence, protocol validation and revocation."""

    def __init__(self, session: Session, cipher: CredentialCipher | None = None):
        self.session = session
        self.cipher = cipher

    def list(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.session.scalars(
            select(MCPConnectionModel)
            .where(self._scope_filter(project_id))
            .order_by(MCPConnectionModel.project_id.is_(None), MCPConnectionModel.id)
        ).all()
        return [self.public(row) for row in rows]

    @staticmethod
    def _scope_filter(project_id: str):
        return or_(
            MCPConnectionModel.project_id == project_id,
            MCPConnectionModel.project_id.is_(None),
        )

    def get_accessible(self, project_id: str, connection_id: str) -> MCPConnectionModel | None:
        return self.session.scalar(
            select(MCPConnectionModel).where(
                MCPConnectionModel.id == connection_id,
                self._scope_filter(project_id),
            )
        )

    def resolved_capabilities(
        self, project_id: str, *, local_connection_id: str | None = None,
        include_project_locals: bool = True,
    ) -> list[dict[str, Any]]:
        """Return active, observed project and global capabilities without collisions."""
        scope = self._scope_filter(project_id)
        if not include_project_locals:
            scope = or_(MCPConnectionModel.project_id.is_(None), MCPConnectionModel.id == local_connection_id)
        rows = self.session.scalars(
            select(MCPConnectionModel)
            .where(
                scope,
                MCPConnectionModel.status == "ACTIVE",
                MCPConnectionModel.encrypted_credentials.is_not(None),
            )
            .order_by(MCPConnectionModel.project_id.is_(None), MCPConnectionModel.id)
        ).all()
        resolved: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            for capability in row.capabilities:
                identity = (capability.kind, capability.name)
                resolved.setdefault(
                    identity,
                    {
                        "ref": f"mcp:{capability.kind}:{capability.name}",
                        "kind": f"mcp_{capability.kind}",
                        "name": capability.name,
                        "description": capability.description,
                        "input_schema": (capability.metadata_json or {}).get("inputSchema", {"type": "object", "properties": {}}),
                        "connection_id": row.id,
                        "is_global": row.project_id is None,
                        "available": True,
                    },
                )
        return list(resolved.values())

    def create_oauth_pending(self, project_id: str, payload: dict[str, Any], state: str, expires_at: datetime) -> MCPConnectionModel:
        if self.cipher is None:
            raise RuntimeError("MCP credential cipher is required")
        credentials = payload.get("credentials") or {}
        required = ("token_endpoint", "client_id", "client_secret", "redirect_uri")
        if any(not isinstance(credentials.get(key), str) or not credentials[key] for key in required):
            raise ValueError("OAuth configuration is incomplete")
        scope = None if payload.get("is_global") is True else project_id
        scope_predicate = MCPConnectionModel.project_id.is_(None) if scope is None else MCPConnectionModel.project_id == scope
        row = self.session.scalar(select(MCPConnectionModel).where(
            scope_predicate, MCPConnectionModel.endpoint == payload["endpoint"].strip()
        ))
        if row is None:
            row = MCPConnectionModel(
                id=str(uuid4()),
                project_id=scope,
                endpoint=payload["endpoint"].strip(),
            )
            self.session.add(row)
        row.name = payload["name"].strip()
        row.transport = payload["transport"]
        row.auth_type = "oauth2"
        row.status = "PENDING"
        row.encrypted_credentials = self.cipher.encrypt({"_oauth": credentials})
        row.oauth_state_hash = hashlib.sha256(state.encode()).hexdigest()
        row.oauth_state_expires_at = expires_at
        self.session.commit()
        self.session.refresh(row)
        return row

    @staticmethod
    def public(row: MCPConnectionModel) -> dict[str, Any]:
        return {"id": row.id, "name": row.name, "endpoint": row.endpoint, "transport": row.transport, "auth_type": row.auth_type, "status": row.status, "is_global": row.project_id is None, "diagnostic": {"code": row.diagnostic_code, "summary": row.diagnostic_summary} if row.diagnostic_code else None, "capabilities": [{"kind": c.kind, "name": c.name, "description": c.description, "observed_at": c.observed_at.isoformat()} for c in row.capabilities]}

    def create(self, project_id: str, payload: dict[str, Any]) -> MCPConnectionModel:
        if self.cipher is None:
            raise RuntimeError("MCP credential cipher is required")
        credentials = payload.get("credentials") or {}
        validate_token_credentials(payload["auth_type"], credentials)
        row = MCPConnectionModel(id=str(uuid4()), project_id=None if payload.get("is_global") is True else project_id, name=payload["name"].strip(), endpoint=payload["endpoint"].strip(), transport=payload["transport"], auth_type=payload["auth_type"], encrypted_credentials=self.cipher.encrypt(credentials))
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

    def refresh(self, project_id: str, connection_id: str) -> MCPConnectionModel:
        """Revalidate the connection before a Run; never retain a failed refresh."""
        row = self.get_accessible(project_id, connection_id)
        if row is None:
            raise LookupError("MCP connection not found")
        try:
            discovery = self.discover(row)
            self._replace_capabilities(row, discovery.tools, discovery.resources)
            row.status, row.diagnostic_code, row.diagnostic_summary = "ACTIVE", None, None
        except Exception as exc:
            row.status, row.diagnostic_code = "ERROR", "MCP_REFRESH_FAILED"
            row.diagnostic_summary = str(redact(str(exc)))[:500]
            self.session.commit()
            raise MCPProtocolError("MCP credential refresh failed") from exc
        self.session.commit()
        self.session.refresh(row)
        return row

    def ensure_renewed(self, project_id: str, connection_id: str) -> MCPConnectionModel:
        """Renew OAuth just before runtime use; token connections are unchanged."""
        row = self.get_accessible(project_id, connection_id)
        if row is None:
            raise LookupError("MCP connection not found")
        if row.status != "ACTIVE" or not row.encrypted_credentials:
            raise PermissionError("MCP connection is not active for this project")
        if row.auth_type != "oauth2" or not row.access_token_expires_at:
            return row
        if row.access_token_expires_at > datetime.now(UTC) + timedelta(seconds=30):
            return row
        return self.renew_oauth(project_id, connection_id)

    def authorize_oauth(self, row: MCPConnectionModel, token_endpoint: str, code: str, redirect_uri: str, client_id: str, client_secret: str, client: OAuthClient | None = None) -> MCPConnectionModel:
        if row.auth_type != "oauth2":
            raise ValueError("MCP connection is not OAuth2")
        tokens = (client or OAuthClient()).exchange_code(token_endpoint, code, redirect_uri, client_id, client_secret)
        tokens["_oauth"] = {
            "token_endpoint": token_endpoint,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }
        if self.cipher is None:
            raise RuntimeError("MCP credential cipher is required")
        row.encrypted_credentials = self.cipher.encrypt(tokens)
        row.access_token_expires_at = self._expires_at(tokens)
        try:
            discovery = self.discover(row)
            self._replace_capabilities(row, discovery.tools, discovery.resources)
            row.status, row.diagnostic_code, row.diagnostic_summary = "ACTIVE", None, None
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(row)
        return row

    @staticmethod
    def _expires_at(tokens: dict[str, Any]) -> datetime | None:
        expires_in = tokens.get("expires_in")
        if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool):
            return datetime.now(UTC) + timedelta(seconds=max(0, expires_in))
        return None

    def renew_oauth(
        self,
        project_id: str,
        connection_id: str,
        *,
        token_endpoint: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        client: OAuthClient | None = None,
    ) -> MCPConnectionModel:
        """Refresh and replace OAuth credentials in one database transaction."""
        row = self.session.scalar(
            select(MCPConnectionModel)
            .where(MCPConnectionModel.id == connection_id, self._scope_filter(project_id))
            .with_for_update()
        )
        if row is None:
            raise LookupError("MCP connection not found")
        if row.auth_type != "oauth2" or not row.encrypted_credentials:
            raise PermissionError("MCP connection has no renewable OAuth credentials")
        credentials = self.cipher.decrypt(row.encrypted_credentials) if self.cipher else {}
        refresh_token = credentials.get("refresh_token")
        if not refresh_token:
            raise PermissionError("MCP refresh token is unavailable")
        oauth_config = credentials.get("_oauth") if isinstance(credentials.get("_oauth"), dict) else {}
        token_endpoint = token_endpoint or oauth_config.get("token_endpoint")
        client_id = client_id or oauth_config.get("client_id")
        client_secret = client_secret or oauth_config.get("client_secret")
        if not all(isinstance(value, str) and value for value in (token_endpoint, client_id, client_secret)):
            raise PermissionError("MCP OAuth configuration is unavailable")
        tokens = (client or OAuthClient()).refresh(token_endpoint, refresh_token, client_id, client_secret)
        tokens["_oauth"] = oauth_config or {
            "token_endpoint": token_endpoint,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if not tokens.get("refresh_token"):
            tokens["refresh_token"] = refresh_token
        row.encrypted_credentials = self.cipher.encrypt(tokens)
        row.access_token_expires_at = self._expires_at(tokens)
        self.session.commit()
        self.session.refresh(row)
        return row

    def _transport(self, row: MCPConnectionModel):
        credentials = self.cipher.decrypt(row.encrypted_credentials or b"") if self.cipher else {}
        headers = {}
        if row.auth_type == "bearer": headers["Authorization"] = f"Bearer {credentials.get('token', '')}"
        if row.auth_type == "api_key": headers[credentials.get("header", "X-API-Key")] = credentials.get("key", "")
        if row.auth_type == "oauth2": headers["Authorization"] = f"Bearer {credentials.get('access_token', '')}"
        if row.transport in ("http", "sse"): return HTTPMCPTransport(row.endpoint, headers)
        return StdioMCPTransport(credentials.get("command", []))

    def discover(self, row: MCPConnectionModel):
        return handshake_and_discover(self._transport(row))

    def invoke(self, project_id: str, connection_id: str, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        row = self.get_accessible(project_id, connection_id)
        if row is None or row.status != "ACTIVE" or not row.encrypted_credentials:
            raise PermissionError("MCP connection is not active for this project")
        if not any(cap.kind == "tool" and cap.name == tool for cap in row.capabilities):
            raise MCPProtocolError("MCP tool is not available")
        try:
            return self._transport(row).call_tool(tool, arguments)
        except Exception as exc:
            row.status = "ERROR"
            row.diagnostic_code = "MCP_INVOCATION_FAILED"
            row.diagnostic_summary = str(redact(str(exc)))[:500]
            self.session.commit()
            raise

    def _replace_capabilities(self, row, tools, resources):
        self.session.execute(delete(MCPCapabilityModel).where(MCPCapabilityModel.connection_id == row.id))
        for kind, values in (("tool", tools), ("resource", resources)):
            for value in values:
                name = str(value.get("name", "")).strip()
                if not name: continue
                self.session.add(MCPCapabilityModel(id=str(uuid4()), connection_id=row.id, kind=kind, name=name, description=str(value.get("description", ""))[:1000], metadata_json=redact({k: v for k, v in value.items() if k not in {"name", "description"}})))

    def revoke(self, project_id: str, connection_id: str) -> bool:
        row = self.get_accessible(project_id, connection_id)
        if not row: return False
        if row.status == "REVOKED": return True
        row.encrypted_credentials = None
        row.status = "REVOKED"
        self.session.execute(delete(MCPCapabilityModel).where(MCPCapabilityModel.connection_id == row.id))
        self.session.commit()
        return True

    def delete(self, project_id: str, connection_id: str) -> bool:
        row = self.get_accessible(project_id, connection_id)
        if not row: return False
        self.session.delete(row)
        self.session.commit()
        return True

    @staticmethod
    def new_oauth_state() -> tuple[str, str, datetime]:
        state = secrets.token_urlsafe(32)
        return state, hashlib.sha256(state.encode()).hexdigest(), datetime.now(UTC) + timedelta(minutes=10)
