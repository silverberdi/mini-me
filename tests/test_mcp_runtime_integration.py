from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.db.models import Base, MCPCapabilityModel, MCPConnectionModel
from minime.mcp.runtime import EphemeralMCPRelay, MCPRuntimeProfileResolver
from minime.mcp.security import CredentialCipher
from tests.mcp_controlled_server import ControlledMCPHandler, controlled_server


def test_runtime_uses_ephemeral_relay_without_process_arguments():
    relay = EphemeralMCPRelay()
    path = relay.start()
    assert "mcp-" in path and "--token" not in path
    relay.close()


def test_runtime_prepare_and_invoke_uses_active_connection_and_observable_effect():
    server, endpoint = controlled_server()
    ControlledMCPHandler.require_auth = True
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    cipher = CredentialCipher(Fernet.generate_key())
    try:
        with Session(engine) as session:
            row = MCPConnectionModel(id="c", project_id="p", name="x", endpoint=endpoint, transport="http", auth_type="bearer", status="ACTIVE", encrypted_credentials=cipher.encrypt({"token": "runtime"}))
            session.add(row)
            session.add(MCPCapabilityModel(id="cap", connection_id="c", kind="tool", name="stitch_get"))
            session.commit()
            resolver = MCPRuntimeProfileResolver(session, cipher)
            profile = resolver.prepare("p", "run-1", "agent-1", "c")
            assert profile.relay_path
            result = resolver.invoke("p", "run-1", "agent-1", "c", "stitch_get", {"run_id": "run-1"})
            assert result["isError"] is False
            resolver.close("run-1")
    finally:
        server.shutdown()
    assert ControlledMCPHandler.effect == [{"tool": "stitch_get", "arguments": {"run_id": "run-1"}}]
