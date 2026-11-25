from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.db.models import Base, MCPCapabilityModel, MCPConnectionModel
from minime.mcp.security import CredentialCipher
from minime.mcp.service import MCPConnectionService


def test_revocation_purges_secret_and_capabilities_idempotently():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        cipher = CredentialCipher(Fernet.generate_key())
        session.add(MCPConnectionModel(id="c", project_id="p", name="x", endpoint="http://x", transport="http", auth_type="bearer", status="ACTIVE", encrypted_credentials=cipher.encrypt({"token": "x"})))
        session.add(MCPCapabilityModel(id="cap", connection_id="c", kind="tool", name="x"))
        session.commit()
        service = MCPConnectionService(session, cipher)
        assert service.revoke("p", "c")
        assert service.revoke("p", "c")
        row = session.get(MCPConnectionModel, "c")
        assert row.status == "REVOKED" and row.encrypted_credentials is None and not row.capabilities
