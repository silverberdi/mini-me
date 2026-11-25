from minime.mcp.protocol import HTTPMCPTransport, handshake_and_discover
from cryptography.fernet import Fernet
import os
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.db.models import Base, MCPConnectionModel, ProjectModel
from minime.mcp.auth import OAuthClient
from minime.mcp.security import CredentialCipher
from minime.mcp.service import MCPConnectionService
from tests.mcp_controlled_server import ControlledMCPHandler, controlled_oauth_server, controlled_server


def test_controlled_mcp_e2e_observes_handshake_discovery_and_effect():
    server, endpoint = controlled_server()
    try:
        transport = HTTPMCPTransport(endpoint)
        discovery = handshake_and_discover(transport)
        result = transport.call_tool("stitch_get", {"screen": "home"})
    finally:
        server.shutdown()
    assert discovery.tools[0]["name"] == "stitch_get"
    assert result["isError"] is False
    assert ControlledMCPHandler.effect == [{"tool": "stitch_get", "arguments": {"screen": "home"}}]


def test_oauth_e2e_provider_consent_callback_encrypted_refresh_handshake_tools_and_active():
    provider, token_endpoint = controlled_oauth_server()
    mcp, endpoint = controlled_server()
    engine = create_engine(os.environ.get("MINIME_TEST_DATABASE_URL", "sqlite://"))
    Base.metadata.create_all(engine)
    cipher = CredentialCipher(Fernet.generate_key())
    try:
        with Session(engine) as session:
            if session.get(ProjectModel, "p") is None:
                session.add(ProjectModel(id="p", display_name="MCP E2E", repository="controlled/repo"))
                session.commit()
            row = MCPConnectionModel(
                id=f"oauth-e2e-{uuid4().hex[:12]}", project_id="p", name="controlled-oauth", endpoint=endpoint,
                transport="http", auth_type="oauth2", status="PENDING",
            )
            session.add(row)
            session.commit()
            service = MCPConnectionService(session, cipher)
            service.authorize_oauth(
                row, f"{token_endpoint}/token", "consent-code", "http://localhost/callback",
                "client", "secret", OAuthClient(),
            )
            assert row.status == "ACTIVE"
            assert any(cap.name == "stitch_get" for cap in row.capabilities)
            assert b"refresh-1" not in row.encrypted_credentials
            row.access_token_expires_at = None
            session.commit()
            result = service.invoke("p", row.id, "stitch_get", {"oauth": True})
            assert result["isError"] is False
    finally:
        provider.shutdown()
        mcp.shutdown()
    assert ControlledMCPHandler.effect == [{"tool": "stitch_get", "arguments": {"oauth": True}}]
