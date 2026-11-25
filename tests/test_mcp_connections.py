from minime.db.models import Base, MCPConnectionModel
from minime.mcp.security import CredentialCipher
from minime.mcp.service import MCPConnectionService


def test_mcp_metadata_has_project_scoped_connection_and_separate_capability_cache():
    assert "mcp_connections" in Base.metadata.tables
    assert "mcp_capabilities" in Base.metadata.tables
    assert "encrypted_credentials" in Base.metadata.tables["mcp_connections"].c
    assert "metadata_json" in Base.metadata.tables["mcp_capabilities"].c


def test_public_connection_never_contains_credentials():
    row = MCPConnectionModel(id="c", project_id="p", name="test", endpoint="http://mcp", transport="http", auth_type="bearer", encrypted_credentials=b"secret", status="ACTIVE")
    public = MCPConnectionService.public(row)
    assert "credentials" not in public
    assert "encrypted_credentials" not in public


def test_cipher_requires_explicit_key_and_round_trips():
    import pytest
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    cipher = CredentialCipher(key)
    encrypted = cipher.encrypt({"token": "do-not-return"})
    assert b"do-not-return" not in encrypted
    assert cipher.decrypt(encrypted)["token"] == "do-not-return"
    with pytest.raises(RuntimeError):
        CredentialCipher(None)
