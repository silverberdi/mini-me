from unittest.mock import MagicMock, patch

from minime.db.models import Base
from minime.db.session import EXPECTED_ALEMBIC_HEAD, verify_physical_schema_invariants


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
    connection.execute.return_value.scalar.return_value = EXPECTED_ALEMBIC_HEAD
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


def _engine_at_revision(revision):
    engine, inspector = _engine_with_schema()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar.return_value = revision
    return engine, inspector


def test_expected_alembic_head_is_canonical_023():
    # The runtime invariant must track the canonical migration head.
    assert EXPECTED_ALEMBIC_HEAD == "023_integrity_findings"
    engine, inspector = _engine_with_schema()
    with patch("minime.db.session.inspect", return_value=inspector):
        result = verify_physical_schema_invariants(engine)
    assert result.valid is True
    assert result.revision == "023_integrity_findings"


def test_021_head_is_behind_current_schema():
    engine, inspector = _engine_at_revision("021_provider_probe_cooldown_state")
    with patch("minime.db.session.inspect", return_value=inspector):
        result = verify_physical_schema_invariants(engine)
    assert result.valid is False
    assert result.revision == "021_provider_probe_cooldown_state"
    assert "023_integrity_findings" in result.reason


def test_stale_020_head_remains_invalid():
    engine, inspector = _engine_at_revision("020_autonomous_intake_admission_policy")
    with patch("minime.db.session.inspect", return_value=inspector):
        result = verify_physical_schema_invariants(engine)
    assert result.valid is False
    assert result.revision == "020_autonomous_intake_admission_policy"


def test_arbitrary_unknown_head_fails_closed():
    engine, inspector = _engine_at_revision("999_unknown_head")
    with patch("minime.db.session.inspect", return_value=inspector):
        result = verify_physical_schema_invariants(engine)
    assert result.valid is False
    assert "999_unknown_head" in result.reason


def test_wrong_head_emits_schema_invariant_violation():
    from minime.db.session import SchemaInvariantResult
    from minime.services.readiness_service import ReadinessService

    uow = MagicMock()
    uow.session.bind = MagicMock()
    uow.projects.get_by_id.return_value = None
    failed = SchemaInvariantResult(
        valid=False,
        reason="Expected Alembic head 023_integrity_findings, found 999_unknown_head.",
    )
    with patch(
        "minime.services.readiness_service.verify_physical_schema_invariants",
        return_value=failed,
    ):
        service = ReadinessService(uow, openspec_adapter=MagicMock(), github_adapter=MagicMock())
        evaluation = service.evaluate_change_readiness("proj", "change", "/tmp")
    assert any(
        "SCHEMA_INVARIANT_VIOLATION" in reason for reason in evaluation.unmet_reasons
    )
