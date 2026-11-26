from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.db.models import Base, MCPCapabilityModel, MCPConnectionModel
from minime.mcp.auth import OAuthStateStore
from minime.mcp.service import MCPConnectionService
from minime.mcp.security import CredentialCipher


def test_oauth_state_is_single_use_and_bound_to_session():
    store = OAuthStateStore()
    authorization = store.issue("session-a")
    assert not store.consume(authorization.state, "session-b")
    assert store.consume(authorization.state, "session-a")
    assert not store.consume(authorization.state, "session-a")


def test_oauth_authorization_encrypts_tokens_and_atomic_refresh_updates_access_token():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    cipher = CredentialCipher(Fernet.generate_key())

    class Provider:
        def __init__(self):
            self.calls = []

        def exchange_code(self, *_args, **_kwargs):
            self.calls.append("exchange")
            return {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 1}

        def refresh(self, *_args, **_kwargs):
            self.calls.append("refresh")
            return {"access_token": "access-2", "expires_in": 3600}

    provider = Provider()
    with Session(engine) as session:
        row = MCPConnectionModel(
            id="oauth", project_id="p", name="controlled", endpoint="http://mcp",
            transport="http", auth_type="oauth2", status="PENDING",
        )
        session.add(row)
        session.commit()
        service = MCPConnectionService(session, cipher)
        # Discovery is replaced only to isolate token persistence; protocol E2E is covered separately.
        service.discover = lambda _row: type("Discovery", (), {"tools": [], "resources": []})()
        service.authorize_oauth(row, "https://provider/token", "code", "https://mini/callback", "client", "secret", provider)
        assert provider.calls == ["exchange"]
        assert row.status == "ACTIVE"
        assert b"refresh-1" not in row.encrypted_credentials
        row.access_token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        service.renew_oauth("p", "oauth", client=provider)
        assert provider.calls == ["exchange", "refresh"]
        assert cipher.decrypt(row.encrypted_credentials)["access_token"] == "access-2"
        assert cipher.decrypt(row.encrypted_credentials)["refresh_token"] == "refresh-1"

        # Verify ensure_renewed recovers from ERROR status and restores ACTIVE
        row.status = "ERROR"
        row.diagnostic_code = "MCP_REFRESH_FAILED"
        row.access_token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        renewed = service.ensure_renewed("p", "oauth", client=provider)
        assert renewed.status == "ACTIVE"
        assert renewed.diagnostic_code is None
        assert len(provider.calls) == 3
