import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.db.models import Base, MCPConnectionModel
from minime.mcp.runtime import EphemeralMCPRelay, MCPRuntimeProfileResolver
from minime.mcp.security import CredentialCipher


def test_inactive_connection_cannot_resolve_profile():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    cipher = CredentialCipher(Fernet.generate_key())
    with Session(engine) as session:
        session.add(MCPConnectionModel(id="c", project_id="p", name="x", endpoint="http://x", transport="http", auth_type="bearer", status="REVOKED", encrypted_credentials=cipher.encrypt({"token": "x"})))
        session.commit()
        with pytest.raises(PermissionError):
            MCPRuntimeProfileResolver(session, cipher).resolve("p", "run", "agent", "c")


def test_relay_is_owner_only_and_ephemeral():
    relay = EphemeralMCPRelay()
    path = relay.start()
    assert path.startswith(relay._directory.name)
    assert (path and __import__("os").stat(path).st_mode & 0o777) == 0o600
    relay.close()
    assert not __import__("os").path.exists(path)
