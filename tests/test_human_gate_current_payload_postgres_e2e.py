"""Persisted-PostgreSQL → real API projection → operator response acceptance path."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from minime.api.app import app, get_current_operator, get_uow
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import HumanGate, OrchestrationStage, OrchestrationStopOutcome
from minime.domain.models import (
    AuthorizedOperator,
    OrchestrationRun,
    Project,
    ProjectManagedRepositoryBinding,
)
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database",
)


def test_persisted_current_gate_reaches_operator_response_api(monkeypatch, tmp_path):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id = str(uuid4())
    run_id = str(uuid4())
    run_uow = None
    try:
        with engine.connect() as connection:
            database_name = connection.execute(text("select current_database()")).scalar_one()
            assert "test" in database_name.lower(), "Refusing to write outside a test database"

        session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        session = session_factory()
        run_uow = PostgresPersistenceUnitOfWork(session)
        project = Project(
            project_id=project_id,
            display_name="Human gate persisted integration",
            repository="org/human-gate-persisted-test",
            execution_policy={"max_review_rounds": 1},
        )
        binding = ProjectManagedRepositoryBinding(
            project_id=project_id,
            canonical_repository_identity="github.com/org/human-gate-persisted-test",
            managed_repository_root=str(tmp_path / "managed-repo"),
            worktree_parent_dir=str(tmp_path / "worktrees"),
        )
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name="issue-300-proposal-review-gate",
            base_sha="base-sha",
            current_stage=OrchestrationStage.PROPOSAL_REVIEW,
            resumable_stage=OrchestrationStage.PROPOSAL_REVIEW,
            is_active=True,
        )
        run_uow.projects.save(project)
        run_uow.project_managed_repository_bindings.save(binding)
        run_uow.orchestration_runs.save(run)
        run_uow.commit()

        coordinator = NativeOrchestrationCoordinator(
            uow_factory=lambda: run_uow,
            github_adapter=MagicMock(),
            worktree_manager=MagicMock(),
            agent_runner=MagicMock(),
        )
        escalation = asyncio.run(
            coordinator._route_proposal_changes_required(
                uow=run_uow,
                project_id=project_id,
                run=run,
                result={
                    "status": "changes_required",
                    "summary": "Material gap in data filtering creates a reporting risk.",
                    "findings": [
                        {
                            "severity": "MAJOR",
                            "location": "Design Decision #2",
                            "violated_requirement": "preserve traceability and the ledger as financial authority",
                            "expected_correction": "include verified provider aggregates for unrecognized model entries",
                        }
                    ],
                },
                worktree_path=Path(tmp_path),
                thinker_provider="codex",
                change_name=run.change_name,
            )
        )
        assert escalation.status == "HUMAN_REQUIRED"
        current_payload = escalation.human_payload
        assert current_payload["review_findings"][0]["location"] == "Design Decision #2"

        operator = AuthorizedOperator(email="operator@example.com", name="Operator", roles=["admin"])
        app.dependency_overrides[get_uow] = lambda: run_uow
        app.dependency_overrides[get_current_operator] = lambda: operator
        scheduled: list[tuple[str, object, str]] = []

        def record_schedule(project_id_arg, body, intent_key):
            scheduled.append((project_id_arg, body, intent_key))
            return "operation-human-gate-e2e"

        monkeypatch.setattr("minime.api.app._schedule_request_worker", record_schedule)
        try:
            with TestClient(app) as client:
                projected_response = client.get(
                    "/api/v1/orchestration/runs",
                    params={"project_id": project_id, "is_active": "true"},
                )
                projected = next(
                    row for row in projected_response.json() if row["run_id"] == run_id
                )
                response = client.post(
                    f"/api/v1/projects/{project_id}/requests/run",
                    json={"operator_clarification": "Pedir corrección y nueva revisión"},
                )
                duplicate_response = client.post(
                    f"/api/v1/projects/{project_id}/requests/run",
                    json={
                        "operator_clarification": "Pedir corrección y nueva revisión",
                        "idempotency_key": response.json().get("idempotency_key"),
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert projected_response.status_code == 200
        assert projected["status"] == "HUMAN_REQUIRED"
        assert projected["stop_details"]["human_payload"] == current_payload
        assert projected["stop_details"]["human_payload"]["reviewer_summary"].startswith("Material gap")
        assert projected["stop_details"]["human_payload"]["review_findings"][0]["severity"] == "MAJOR"
        assert response.status_code == 202
        assert response.json()["status"] == "ACCEPTED"
        assert duplicate_response.status_code == 202
        assert duplicate_response.json()["operation_id"] == response.json()["operation_id"]
        assert response.json()["idempotency_key"]
        assert len(scheduled) == 1
        assert scheduled[0][0] == project_id
        assert scheduled[0][1].operator_clarification == "Pedir corrección y nueva revisión"
        assert scheduled[0][1].idempotency_key
        accepted_actions = run_uow.operator_actions.list_by_run(run_id)
        assert len(accepted_actions) == 1
        assert accepted_actions[0].action_type.value == "RESOLVE_GATE"
        assert accepted_actions[0].parameters_json["accepted_response"] == "Pedir corrección y nueva revisión"
        still_gated = run_uow.orchestration_runs.get_by_id(run_id)
        assert still_gated.human_gate == HumanGate.NEEDS_HUMAN
        assert still_gated.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
        assert still_gated.current_stage == OrchestrationStage.PROPOSAL_REVIEW
        assert still_gated.stop_details.get("proposal_review", {}).get("status") != "approved"

        accepted_actions[0].status = "COMPLETED"
        accepted_actions[0].result_payload_json = {
            "status": "RUNNING", "run_id": run_id,
            "current_stage": OrchestrationStage.PROPOSAL_REVIEW.value,
            "message": "Gate response was already processed.",
        }
        run_uow.operator_actions.save(accepted_actions[0])
        persisted_run = run_uow.orchestration_runs.get_by_id(run_id)
        persisted_run.stop_details = {}
        persisted_run.human_gate = None
        persisted_run.stop_outcome = None
        run_uow.orchestration_runs.save(persisted_run)
        run_uow.commit()
        app.dependency_overrides[get_uow] = lambda: run_uow
        app.dependency_overrides[get_current_operator] = lambda: operator
        with TestClient(app) as client:
            completed_duplicate = client.post(
                f"/api/v1/projects/{project_id}/requests/run",
                json={
                    "operator_clarification": "Pedir corrección y nueva revisión",
                    "idempotency_key": response.json()["idempotency_key"],
                },
            )
        assert completed_duplicate.status_code == 202
        assert completed_duplicate.json()["message"] == "Gate response was already processed."
        assert len(scheduled) == 1
        app.dependency_overrides.clear()

        persisted = run_uow.orchestration_runs.get_by_id(run_id)
        assert "human_payload" not in persisted.stop_details
    finally:
        app.dependency_overrides.clear()
        if run_uow is not None:
            run_uow.session.execute(
                text("delete from orchestration_runs where id = :run_id"), {"run_id": run_id}
            )
            run_uow.session.execute(
                text("delete from project_managed_repository_bindings where project_id = :project_id"),
                {"project_id": project_id},
            )
            run_uow.session.execute(
                text("delete from projects where id = :project_id"), {"project_id": project_id}
            )
            run_uow.commit()
            run_uow.session.close()
        engine.dispose()
