from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from minime.db.models import Base, MCPCapabilityModel, MCPConnectionModel
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
    assert public["is_global"] is False


def test_global_connection_is_listed_across_projects_and_local_connections_stay_scoped():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            MCPConnectionModel(id="local-a", project_id="a", name="A", endpoint="http://a", transport="http", auth_type="bearer", status="ACTIVE", encrypted_credentials=b"a"),
            MCPConnectionModel(id="local-b", project_id="b", name="B", endpoint="http://b", transport="http", auth_type="bearer", status="ACTIVE", encrypted_credentials=b"b"),
            MCPConnectionModel(id="global", project_id=None, name="Global", endpoint="http://global", transport="http", auth_type="bearer", status="ACTIVE", encrypted_credentials=b"global"),
        ])
        session.commit()
        service = MCPConnectionService(session)
        rows_a = service.list("a")
        rows_b = service.list("b")
        assert {row["id"] for row in rows_a} == {"local-a", "global"}
        assert {row["id"] for row in rows_b} == {"local-b", "global"}
        assert next(row for row in rows_a if row["id"] == "global")["is_global"] is True
        assert "encrypted_credentials" not in next(row for row in rows_a if row["id"] == "global")


def test_resolved_capabilities_deduplicate_with_local_precedence_and_exclude_inactive_globals():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            MCPConnectionModel(id="local", project_id="p", name="Local", endpoint="http://local", transport="http", auth_type="bearer", status="ACTIVE", encrypted_credentials=b"local"),
            MCPConnectionModel(id="global-z", project_id=None, name="Global z", endpoint="http://global-z", transport="http", auth_type="bearer", status="ACTIVE", encrypted_credentials=b"z"),
            MCPConnectionModel(id="global-a", project_id=None, name="Global a", endpoint="http://global-a", transport="http", auth_type="bearer", status="ACTIVE", encrypted_credentials=b"a"),
            MCPConnectionModel(id="inactive", project_id=None, name="Inactive", endpoint="http://inactive", transport="http", auth_type="bearer", status="REVOKED", encrypted_credentials=b"inactive"),
        ])
        session.add_all([
            MCPCapabilityModel(id="local-tool", connection_id="local", kind="tool", name="stitch_get"),
            MCPCapabilityModel(id="global-z-tool", connection_id="global-z", kind="tool", name="stitch_get"),
            MCPCapabilityModel(id="global-a-tool", connection_id="global-a", kind="tool", name="stitch_get"),
            MCPCapabilityModel(id="global-resource", connection_id="global-a", kind="resource", name="designs"),
            MCPCapabilityModel(id="inactive-tool", connection_id="inactive", kind="tool", name="must_not_appear"),
        ])
        session.commit()
        capabilities = MCPConnectionService(session).resolved_capabilities("p")
        runtime_globals = MCPConnectionService(session).resolved_capabilities(
            "p", include_project_locals=False
        )
        runtime_selected = MCPConnectionService(session).resolved_capabilities(
            "p", local_connection_id="local", include_project_locals=False
        )
        tools = [item for item in capabilities if item["kind"] == "mcp_tool"]
        assert len(tools) == 1
        assert tools[0]["connection_id"] == "local"
        assert {item["name"] for item in capabilities} == {"stitch_get", "designs"}
        assert {item["name"] for item in runtime_globals} == {"stitch_get", "designs"}
        assert next(item for item in runtime_globals if item["name"] == "stitch_get")["connection_id"] == "global-a"
        assert next(item for item in runtime_selected if item["name"] == "stitch_get")["connection_id"] == "local"


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
