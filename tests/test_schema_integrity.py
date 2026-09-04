from unittest.mock import MagicMock, patch

from minime.db.models import Base
from minime.db.session import verify_physical_schema_invariants


def _engine_with_schema(missing_table=None, missing_column=None):
    engine = MagicMock()
    inspector = MagicMock()
    tables = set(Base.metadata.tables) | {"alembic_version"}
    tables.discard(missing_table)
    inspector.get_table_names.return_value = list(tables)
    inspector.get_columns.side_effect = lambda table: [
        {"name": c.name}
        for c in Base.metadata.tables[table].columns
        if not (missing_column and table == missing_column[0] and c.name == missing_column[1])
    ]
    connection = MagicMock()
    connection.execute.return_value.scalar.return_value = "019_work_intake_and_backlog_items"
    engine.connect.return_value.__enter__.return_value = connection

    return engine, inspector


def test_migration_head_with_missing_table_fails_closed():
    engine, inspector = _engine_with_schema(missing_table="reviews")
    with patch("minime.db.session.inspect", return_value=inspector):
        result = verify_physical_schema_invariants(engine)
    assert result.valid is False
    assert "reviews" in result.missing_tables


def test_migration_head_with_missing_required_column_fails_closed():
    engine, inspector = _engine_with_schema(missing_column=("reviews", "is_mixed_authorship"))
    with patch("minime.db.session.inspect", return_value=inspector):
        result = verify_physical_schema_invariants(engine)
    assert result.valid is False
    assert result.missing_columns["reviews"] == ("is_mixed_authorship",)


def test_valid_physical_schema_passes_preflight():
    engine, inspector = _engine_with_schema()
    with patch("minime.db.session.inspect", return_value=inspector):
        result = verify_physical_schema_invariants(engine)
    assert result.valid is True
