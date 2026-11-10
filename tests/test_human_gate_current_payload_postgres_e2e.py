"""Persisted-PostgreSQL → real API projection → operator response acceptance path."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
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
from minime.services.orchestration_coordinator import ApplyOutcome, NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeInfo

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


def test_postgres_apply_gate_response_starts_one_simulated_cycle(monkeypatch, tmp_path):
    """PostgreSQL/API/coordinator E2E with simulated Update and Apply agents."""
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as connection:
        database_name = connection.execute(text("select current_database()")).scalar_one()
        assert "test" in database_name.lower(), "Refusing to write outside a test database"
    project_id = str(uuid4())
    run_id = str(uuid4())
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    subprocess.run(["git", "init", "-q", str(candidate)], check=True)
    subprocess.run(["git", "-C", str(candidate), "checkout", "-qb", "feature/issue-375"], check=True)
    subprocess.run(["git", "-C", str(candidate), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(candidate), "config", "user.name", "Test"], check=True)
    change_name = "issue-375-reset-apply-attempt-cycle"
    change_dir = candidate / "openspec" / "changes" / change_name
    source_change = (
        Path(__file__).resolve().parents[1]
        / "openspec"
        / "changes"
        / "archive"
        / "2026-11-10-req-378-human-directed-validation-deferral"
    )
    shutil.copytree(source_change, change_dir)
    subprocess.run(["git", "-C", str(candidate), "add", "."], check=True)
    subprocess.run(["git", "-C", str(candidate), "commit", "-qm", "seed candidate"], check=True)
    candidate_sha = subprocess.check_output(
        ["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True
    ).strip()

    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    uow = PostgresPersistenceUnitOfWork(session)
    run = OrchestrationRun(
        run_id=run_id,
        project_id=project_id,
        change_name=change_name,
        base_sha="base-sha",
        current_stage=OrchestrationStage.IMPLEMENTING,
        resumable_stage=OrchestrationStage.IMPLEMENTING,
        human_gate=HumanGate.NEEDS_HUMAN,
        stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
        current_candidate_sha=candidate_sha,
        stop_details={
            "issue_number": 375,
            "issue_title": "Reset Apply recovery cycle after operator response",
            "request_normalization": {"normalized_body": "Implement the authorized Issue #375 change."},
            "apply_total_attempts": 3,
            "apply_no_progress": 2,
            "apply_limits": {"max_attempts": 3, "max_no_progress": 2},
            "apply_snapshot": {
                "run_id": run_id, "sha": candidate_sha,
                "branch": "feature/issue-375", "worktree": str(candidate.resolve()),
                "completed": ["1.1"], "pending": ["1.3"],
                "files": [], "tests_passed": None,
            },
            "human_payload": {
                "gate_id": "gate-apply-375",
                "gate": "apply_escalation",
                "stage": "IMPLEMENTING",
                "attempts": 3,
                "hard_limit": 3,
                "no_progress": 2,
                "candidate_sha": candidate_sha,
                "question": "Continue Apply recovery?",
                "options": [{"id": "retry", "label": "Continue"}],
            },
        },
    )
    uow.projects.save(Project(
        project_id=project_id,
        display_name="Apply cycle E2E",
        repository="org/issue-375-apply-cycle-test",
        execution_policy={},
    ))
    uow.project_managed_repository_bindings.save(ProjectManagedRepositoryBinding(
        project_id=project_id,
        canonical_repository_identity="github.com/org/issue-375-apply-cycle-test",
        managed_repository_root=str(tmp_path / "managed-repo"),
        worktree_parent_dir=str(tmp_path / "worktrees"),
    ))
    uow.orchestration_runs.save(run)
    uow.commit()

    operator = AuthorizedOperator(email="operator@example.com", name="Operator", roles=["admin"])
    app.dependency_overrides[get_uow] = lambda: uow
    app.dependency_overrides[get_current_operator] = lambda: operator
    scheduled: list[tuple[str, object, str]] = []
    monkeypatch.setattr(
        "minime.api.app._schedule_request_worker",
        lambda project, body, key: scheduled.append((project, body, key)) or "apply-cycle-operation",
    )
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/projects/{project_id}/requests/run",
                json={"target_run_id": run_id, "operator_clarification": "Continue Apply recovery"},
            )
            duplicate_response = client.post(
                f"/api/v1/projects/{project_id}/requests/run",
                json={
                    "target_run_id": run_id,
                    "operator_clarification": "Continue Apply recovery",
                    "idempotency_key": response.json().get("idempotency_key"),
                },
            )
        assert response.status_code == 202
        assert duplicate_response.status_code == 202
        assert duplicate_response.json()["operation_id"] == response.json()["operation_id"]
        assert len(scheduled) == 1
        action_id = response.json()["idempotency_key"]
        accepted_action = uow.operator_actions.get_by_request_id(action_id)
        assert accepted_action is not None
        assert accepted_action.status == "ACCEPTED"

        coordinator = NativeOrchestrationCoordinator(
            uow_factory=lambda: uow,
            github_adapter=MagicMock(),
            worktree_manager=MagicMock(),
            agent_runner=MagicMock(),
        )
        coordinator.worktree_manager.create_request_worktree = AsyncMock(
            return_value=WorktreeInfo(
                path=candidate, branch_name="feature/issue-375", base_sha="base-sha"
            )
        )
        async def simulated_update_with_task_reclassification(**kwargs):
            tasks_path = change_dir / "tasks.md"
            tasks_text = tasks_path.read_text(encoding="utf-8")
            tasks_path.write_text(
                tasks_text.replace(
                    "- [x] 1.1 Trace the accepted gate response",
                    "- [ ] 1.1 Trace the accepted gate response [DEFERRED] Operator supplied published-version evidence; candidate-specific evidence remains pending.",
                ),
                encoding="utf-8",
            )
            return simulated_update

        simulated_update = MagicMock(
            exit_code=0,
            timed_out=False,
            preflight_error=None,
            environment_error=False,
            structured_output_missing=False,
            structured_output_too_large=False,
            workflow_handoff_required=False,
            final_response_status="COMPLETE",
            response_output="Deterministic simulated authorized task reclassification.",
        )
        coordinator.agent_runner.resolve_workflow = MagicMock(return_value=MagicMock())
        coordinator.agent_runner.run = AsyncMock(side_effect=simulated_update_with_task_reclassification)
        coordinator._run_apply = AsyncMock(return_value=ApplyOutcome(
            status="FAILED", completed_tasks=(), pending_tasks=("Simulated pending task",),
            candidate_sha=candidate_sha, changed_files=(), diff_fingerprint=None,
            tests_passed=None, test_evidence="", error="deterministic simulated failure",
            branch="feature/issue-375", worktree=str(candidate.resolve()), run_id=run_id,
        ))
        result = asyncio.run(coordinator.execute_project_request(
            project_id,
            target_run_id=run_id,
            operator_clarification="Continue Apply recovery",
            operator_action_id=action_id,
        ))

        persisted = uow.orchestration_runs.get_by_id(run_id)
        events = uow.orchestration_stage_events.list_by_run(run_id)
        starts = [event for event in events if event.event_type == "STAGE_INVOCATION_STARTED"]
        finishes = [
            event for event in events
            if event.event_type in {
                "STAGE_INVOCATION_COMPLETED", "STAGE_INVOCATION_FAILED",
                "STAGE_INVOCATION_HUMAN_REQUIRED",
            }
        ]
        assert result.status == "HUMAN_REQUIRED"
        assert result.run_id == run_id
        assert persisted.stop_details["apply_total_attempts"] == 1
        assert persisted.stop_details["apply_cycle_started_by_action_id"] == action_id
        assert persisted.stop_details["apply_snapshot"]["sha"] == candidate_sha
        assert persisted.stop_details["apply_gate_update"]["status"] == "VALIDATED"
        assert persisted.stop_details["apply_gate_update"]["validation"]["status"] == "PASS"
        assert persisted.stop_details["apply_gate_update"]["reclassified_tasks"] == ["1.1"]
        assert persisted.stop_details["apply_snapshot"]["pending"] == ["Simulated pending task"]
        assert persisted.stop_details["apply_snapshot"]["completed"] == []
        assert coordinator.agent_runner.resolve_workflow.call_args.kwargs["operation"] == "update"
        assert coordinator.agent_runner.run.await_args.kwargs["role"] == "thinker"
        update_starts = [event for event in starts if ":UPDATE:" in event.evidence_references["claim_key"]]
        apply_starts = [event for event in starts if ":APPLY:" in event.evidence_references["claim_key"]]
        assert len(update_starts) == len(apply_starts) == 1
        assert len(finishes) == 2
        assert any(
            event.event_type == "STAGE_INVOCATION_COMPLETED"
            and ":UPDATE:" in event.evidence_references["claim_key"]
            for event in finishes
        )
        assert any(
            event.event_type == "STAGE_INVOCATION_FAILED"
            and ":APPLY:" in event.evidence_references["claim_key"]
            for event in finishes
        )
        assert all(event.evidence_references["operator_action_id"] == action_id for event in starts)
        assert all(event.evidence_references["candidate"]["candidate_sha"] == candidate_sha for event in starts)
        assert all(event.evidence_references["candidate"]["candidate_sha"] == candidate_sha for event in finishes)
    finally:
        app.dependency_overrides.clear()
        session.execute(
            text("DELETE FROM recovery_claims WHERE claim_key LIKE :prefix"),
            {"prefix": f"stage-invocation:{run_id}:%"},
        )
        session.execute(text("DELETE FROM projects WHERE id = :project_id"), {"project_id": project_id})
        session.commit()
        session.close()
        engine.dispose()
