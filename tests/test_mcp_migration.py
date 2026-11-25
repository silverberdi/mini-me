import os
import subprocess

import pytest
from alembic.config import Config
from minime.db.models import Base


def test_mcp_migration_contract_is_reversible_and_metadata_matches():
    assert "mcp_connections" in Base.metadata.tables
    assert "mcp_capabilities" in Base.metadata.tables
    config = Config("alembic.ini")
    assert config.get_main_option("script_location")


@pytest.mark.skipif(not os.environ.get("MINIME_TEST_DATABASE_URL"), reason="isolated PostgreSQL test database is required")
def test_mcp_migration_upgrade_and_rollback_against_disposable_postgres():
    env = os.environ.copy()
    env["MINIME_DATABASE_URL"] = env["MINIME_TEST_DATABASE_URL"]
    env.pop("DATABASE_URL", None)
    upgrade = subprocess.run(["alembic", "upgrade", "req537_mcp_connections"], env=env, text=True, capture_output=True, check=False)
    assert upgrade.returncode == 0, upgrade.stderr
    downgrade = subprocess.run(["alembic", "downgrade", "req466_project_test_database_profile"], env=env, text=True, capture_output=True, check=False)
    assert downgrade.returncode == 0, downgrade.stderr
    restore = subprocess.run(["alembic", "upgrade", "req537_mcp_connections"], env=env, text=True, capture_output=True, check=False)
    assert restore.returncode == 0, restore.stderr
