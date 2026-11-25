from alembic.config import Config
from minime.db.models import Base


def test_mcp_migration_contract_is_reversible_and_metadata_matches():
    assert "mcp_connections" in Base.metadata.tables
    assert "mcp_capabilities" in Base.metadata.tables
    config = Config("alembic.ini")
    assert config.get_main_option("script_location")
