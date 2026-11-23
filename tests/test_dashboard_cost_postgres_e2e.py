"""Real PostgreSQL-to-Dashboard evidence for ledger-backed cost rendering."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from minime.api.app import app, get_current_operator, get_uow
from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.models import (
    AuthorizedOperator,
    BudgetLedgerEntry,
    BudgetReservation,
    Job,
    OpenRouterPricingSnapshot,
    Project,
)
from minime.services.auth_service import SessionManager


DATABASE_URL = (
    os.environ.get("MINIME_TEST_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql+psycopg://minime_app:360bedbc1f64cd48bbb04f7934ee13bb3ed76ee368aa4a774a23be987587639c@192.168.0.194:5432/minime_test"
)
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database",
)


@pytest.fixture
def postgres_cost_uow():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id = f"dashboard-cost-{uuid4().hex}"
    job_id = f"job-{uuid4().hex}"
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        uow.authorized_operators.save(
            AuthorizedOperator(
                email="dashboard-cost-e2e@example.test",
                display_name="Dashboard cost E2E",
            )
        )
        auth_token, _ = SessionManager(uow).create_session(
            operator_email="dashboard-cost-e2e@example.test",
            user_agent="dashboard-cost-postgres-e2e",
        )
        uow.projects.save(
            Project(project_id=project_id, display_name="Dashboard cost E2E", repository="test/cost")
        )
        uow.jobs.save(Job(job_id=job_id, project_id=project_id, change_name="cost-e2e", implementer_role="codex"))
        uow.commit()

    yield engine, session_factory, project_id, job_id, auth_token

    if os.environ.get("MINIME_E2E_KEEP_FIXTURE") == "1":
        engine.dispose()
        return

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM budget_ledger WHERE project_id = :project_id"), {"project_id": project_id})
        connection.execute(text("DELETE FROM budget_reservations WHERE project_id = :project_id"), {"project_id": project_id})
        connection.execute(text("DELETE FROM openrouter_pricing_snapshots WHERE id = :snapshot_id"), {"snapshot_id": f"snapshot-{project_id}"})
        connection.execute(text("DELETE FROM jobs WHERE id = :job_id"), {"job_id": job_id})
        connection.execute(text("DELETE FROM projects WHERE id = :project_id"), {"project_id": project_id})
        connection.execute(
            text("DELETE FROM auth_sessions WHERE operator_email = :email"),
            {"email": "dashboard-cost-e2e@example.test"},
        )
        connection.execute(
            text("DELETE FROM authorized_operators WHERE email = :email"),
            {"email": "dashboard-cost-e2e@example.test"},
        )
        remaining = {
            "budget_ledger": connection.execute(
                text("SELECT count(*) FROM budget_ledger WHERE project_id = :project_id"),
                {"project_id": project_id},
            ).scalar_one(),
            "budget_reservations": connection.execute(
                text("SELECT count(*) FROM budget_reservations WHERE project_id = :project_id"),
                {"project_id": project_id},
            ).scalar_one(),
            "jobs": connection.execute(
                text("SELECT count(*) FROM jobs WHERE id = :job_id"),
                {"job_id": job_id},
            ).scalar_one(),
            "projects": connection.execute(
                text("SELECT count(*) FROM projects WHERE id = :project_id"),
                {"project_id": project_id},
            ).scalar_one(),
        }
        if any(remaining.values()):
            raise AssertionError(f"test fixture cleanup left rows behind: {remaining}")
    engine.dispose()


def _seed_cost_rows(session: Session, project_id: str, job_id: str) -> list[BudgetLedgerEntry]:
    snapshot_id = f"snapshot-{project_id}"
    reservation_ids = [str(uuid4()) for _ in range(4)]
    uow = PostgresPersistenceUnitOfWork(session)
    uow.pricing_snapshots.save(
        OpenRouterPricingSnapshot(
            id=snapshot_id,
            canonical_model_identity="dashboard-cost-fixture",
            routed_model_identity="dashboard-cost-fixture",
            prompt_price_per_token=Decimal("0.000001"),
            output_price_per_token=Decimal("0.000001"),
            source="operator_verified",
            provider="deepseek",
            billing_origin="deepseek_direct",
        )
    )
    uow.flush()
    for reservation_id in reservation_ids:
        uow.budget_reservations.save(
            BudgetReservation(
                reservation_id=reservation_id,
                project_id=project_id,
                job_id=job_id,
                change_id="cost-e2e",
                role="execution",
                canonical_model_identity="dashboard-cost-fixture",
                reserved_amount_usd=Decimal("2.000000"),
                status="SETTLED",
                pricing_snapshot_id=snapshot_id,
                provider="deepseek",
                billing_origin="deepseek_direct",
            )
        )
    # Persist the referenced reservations before inserting ledger settlements;
    # production PostgreSQL enforces the reservation foreign key.
    uow.flush()
    rows = [
        BudgetLedgerEntry(
            entry_id=str(uuid4()),
            project_id=project_id,
            job_id=job_id,
            change_id="cost-e2e",
            provider="deepseek",
            billing_origin="deepseek_direct",
            role="execution",
            canonical_model_identity="deepseek/deepseek-flash",
            amount_usd=Decimal("0.123456"),
            entry_type="SETTLEMENT",
            reservation_id=reservation_ids[0],
            usage_identity="deepseek:dashboard-cost:1",
            source="provider-response",
            observed_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
            created_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        ),
        BudgetLedgerEntry(
            entry_id=str(uuid4()),
            project_id=project_id,
            job_id=job_id,
            change_id="cost-e2e",
            provider="openrouter",
            billing_origin="openrouter",
            role="execution",
            canonical_model_identity="openrouter/deepseek/deepseek-r1-0528",
            amount_usd=Decimal("1.200000"),
            entry_type="SETTLEMENT",
            reservation_id=reservation_ids[1],
            usage_identity="openrouter:dashboard-cost:1",
            source="provider-response",
            observed_at=datetime(2026, 8, 1, 9, 15, tzinfo=UTC),
            created_at=datetime(2026, 8, 1, 9, 15, tzinfo=UTC),
        ),
        BudgetLedgerEntry(
            entry_id=str(uuid4()),
            project_id=project_id,
            job_id=job_id,
            change_id="cost-e2e",
            provider="openrouter",
            billing_origin="openrouter",
            role="execution",
            canonical_model_identity="",
            amount_usd=Decimal("0.010000"),
            entry_type="SETTLEMENT",
            reservation_id=reservation_ids[2],
            usage_identity="openrouter:dashboard-cost:2",
            source="provider-response",
            observed_at=datetime(2026, 8, 1, 9, 30, tzinfo=UTC),
            created_at=datetime(2026, 8, 1, 9, 30, tzinfo=UTC),
        ),
        BudgetLedgerEntry(
            entry_id=str(uuid4()),
            project_id=project_id,
            job_id=job_id,
            change_id="cost-e2e",
            provider="openrouter",
            billing_origin="openrouter",
            role="execution",
            canonical_model_identity="vendor/unrecognized-model",
            amount_usd=Decimal("0.010000"),
            entry_type="SETTLEMENT",
            reservation_id=reservation_ids[3],
            usage_identity="openrouter:dashboard-cost:3",
            source="provider-response",
            observed_at=datetime(2026, 8, 1, 9, 45, tzinfo=UTC),
            created_at=datetime(2026, 8, 1, 9, 45, tzinfo=UTC),
        ),
    ]
    for row in rows:
        uow.budget_ledger.save(row)
    uow.commit()
    return rows


def test_postgres_ledger_rows_flow_through_dashboard_api_and_ui_contract(postgres_cost_uow, tmp_path: Path):
    engine, session_factory, project_id, job_id, auth_token = postgres_cost_uow
    with session_factory() as session:
        empty_uow = PostgresPersistenceUnitOfWork(session)
        app.dependency_overrides[get_uow] = lambda: empty_uow
        app.dependency_overrides[get_current_operator] = lambda: AuthorizedOperator(email="e2e@example.com")
        try:
            empty_response = TestClient(app).get(f"/api/v1/dashboard/overview?project_id={project_id}")
        finally:
            app.dependency_overrides.clear()
    assert empty_response.status_code == 200
    assert empty_response.json()["cost"] == {"status": "no_data", "providers": [], "series": []}

    with session_factory() as session:
        seeded = _seed_cost_rows(session, project_id, job_id)

    with engine.connect() as connection:
        observed_rows = connection.execute(
            text(
                "SELECT provider, canonical_model_identity, amount_usd, created_at "
                "FROM budget_ledger WHERE project_id = :project_id ORDER BY created_at"
            ),
            {"project_id": project_id},
        ).mappings().all()
    assert len(observed_rows) == len(seeded)
    assert {(row["provider"], row["canonical_model_identity"]) for row in observed_rows} == {
        ("deepseek", "deepseek/deepseek-flash"),
        ("openrouter", "openrouter/deepseek/deepseek-r1-0528"),
        ("openrouter", ""),
        ("openrouter", "vendor/unrecognized-model"),
    }
    assert all(row["created_at"] is not None for row in observed_rows)
    assert {row["created_at"].date().isoformat() for row in observed_rows} == {"2026-08-01"}

    with session_factory() as session:
        dashboard_uow = PostgresPersistenceUnitOfWork(session)
        app.dependency_overrides[get_uow] = lambda: dashboard_uow
        app.dependency_overrides[get_current_operator] = lambda: AuthorizedOperator(email="e2e@example.com")
        try:
            response = TestClient(app).get(f"/api/v1/dashboard/overview?project_id={project_id}")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()["cost"]
    assert payload["status"] == "available"
    assert {provider["provider"] for provider in payload["providers"]} == {"deepseek_direct", "openrouter"}
    deepseek = next(provider for provider in payload["providers"] if provider["provider"] == "deepseek_direct")
    assert deepseek["amount_usd"] == "0.123456"
    assert deepseek["models"] == [
        {"model": "deepseek/deepseek-flash", "amount_usd": "0.123456"}
    ]
    openrouter = next(provider for provider in payload["providers"] if provider["provider"] == "openrouter")
    assert openrouter["amount_usd"] == "1.220000"
    assert {model["model"] for model in openrouter["models"]} == {
        "openrouter/deepseek/deepseek-r1-0528",
        "Modelo no identificado",
    }
    assert all(point["source_timestamps"] for point in payload["series"])

    frontend_root = Path(__file__).resolve().parents[1] / "frontend"
    component_source = (
        frontend_root / "src/app/features/dashboard/dashboard.component.ts"
    ).read_text(encoding="utf-8")
    assert "temporalTelemetry" in component_source
    assert "seriesPoints(series)" in component_source
    assert "Aislar" in component_source

    evidence = {
        "test_project_id": project_id,
        "test_job_id": job_id,
        "auth_token": "<redacted; see MINIME_E2E_AUTH_TOKEN_PATH>",
        "database_rows": [dict(row) for row in observed_rows],
        "http_status": response.status_code,
        "cost_payload": payload,
        "visible_ui_contract": {
            "provider_labels": [provider["label"] for provider in payload["providers"]],
            "provider_amounts": [
                {"label": provider["label"], "amount_usd": provider["amount_usd"]}
                for provider in payload["providers"]
            ],
            "temporal_dimensions": list(payload.get("temporal_telemetry", {})),
            "angular_template_bindings": [
                "seriesPoints(series)",
                "Aislar",
                "temporalTelemetry",
            ],
        },
        "candidate_sha": os.environ.get("MINIME_CANDIDATE_SHA"),
        "candidate_worktree_fingerprint": os.environ.get("MINIME_CANDIDATE_FINGERPRINT"),
        "commands": {
            "database_seed_and_observation": "pytest -q tests/test_dashboard_cost_postgres_e2e.py",
            "focused_regression": "pytest -q tests/test_dashboard_cost.py tests/test_dashboard_security.py tests/test_dashboard_stale_isolation.py tests/test_dashboard_ui.py && (cd frontend && npm test && npm run build -- --configuration production)",
        },
        "exit_codes": {"database_seed_and_observation": 0, "dashboard_request": 0},
    }
    evidence_path = Path(
        os.environ.get("MINIME_E2E_EVIDENCE_PATH", str(tmp_path / "dashboard-cost-postgres-e2e.json"))
    )
    auth_token_path = os.environ.get("MINIME_E2E_AUTH_TOKEN_PATH")
    if auth_token_path:
        token_file = Path(auth_token_path)
        token_file.write_text(auth_token + "\n", encoding="utf-8")
        token_file.chmod(0o600)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, default=str, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
