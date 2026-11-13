from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.api.app import app, get_current_operator, get_uow
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
)
from minime.domain.models import (
    AuthorizedOperator,
    HumanGate,
    OperatorActionRecord,
    OrchestrationRun,
    OrchestrationStageEvent,
    OrchestrationStopOutcome,
    Project,
    ProjectManagedRepositoryBinding,
)
from minime.services.apply_checkpoint_recovery import (
    REBASELINE_RESPONSE,
    RECOVERY_GATE,
    diagnose_lost_apply_checkpoint,
    human_gate_fingerprint,
    recovery_gate_payload,
)
from minime.services.orchestration_coordinator import ApplyOutcome, NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeInfo

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")


def _sequence():
    run_id = "run-387"
    change_name = "req-387-recover-overwritten-apply-disposition"
    candidate_sha = "a" * 40
    branch = "feature/issue-387"
    worktree = "/tmp/issue-387-worktree"
    identity = {
        "run_id": run_id,
        "branch": branch,
        "worktree": worktree,
        "generation": 2,
        "candidate_sha": candidate_sha,
    }
    checkpoint_identity = {**identity, "candidate_fingerprint": "same-fingerprint"}
    snapshot = {
        "run_id": run_id,
        "sha": candidate_sha,
        "branch": branch,
        "worktree": worktree,
        "completed": ["3.2"],
        "pending": [],
    }
    no_op_action_id = "operator-noop"
    prior_action_id = "operator-disposition"
    run = OrchestrationRun(
        run_id=run_id,
        project_id="mini-me",
        change_name=change_name,
        base_sha="base",
        current_stage=OrchestrationStage.IMPLEMENTING,
        current_candidate_sha=candidate_sha,
        is_active=True,
        stop_details={
            "apply_snapshot": snapshot,
            "apply_gate_update": {
                "status": "VALIDATED",
                "changed": False,
                "operator_action_id": no_op_action_id,
                "change_name": change_name,
                "before": checkpoint_identity,
                "after": checkpoint_identity,
                "reclassified_tasks": [],
                "task_dispositions_after": {"3.2": "pending", "4.1": "deferred"},
                "validation": {"status": "PASS"},
            },
            "human_payload": {"gate": "apply_escalation", "question": "Continue?"},
        },
    )
    actions = [
        OperatorActionRecord(
            action_request_id=prior_action_id,
            project_id="mini-me",
            change_name=change_name,
            run_id=run_id,
            action_type=OperatorActionType.RESOLVE_GATE,
            precondition_gate="physical_validation",
            status=OperatorActionStatus.COMPLETED,
            parameters_json={"accepted_response": "Defer physical validation."},
        ),
        OperatorActionRecord(
            action_request_id=no_op_action_id,
            project_id="mini-me",
            change_name=change_name,
            run_id=run_id,
            action_type=OperatorActionType.RESOLVE_GATE,
            precondition_gate="apply_escalation",
            status=OperatorActionStatus.COMPLETED,
            parameters_json={"accepted_response": "Continue Apply."},
        ),
    ]
    now = datetime.now(UTC)
    events = []
    for index, (action_id, changed) in enumerate(
        ((prior_action_id, True), (no_op_action_id, False))
    ):
        attempt_id = f"update-{index}"
        candidate = {**checkpoint_identity, "stage": "UPDATE"}
        claim_key = f"stage-invocation:{run_id}:UPDATE:fingerprint-{index}"
        events.extend([
            OrchestrationStageEvent(
                run_id=run_id,
                to_stage=OrchestrationStage.IMPLEMENTING,
                event_type="STAGE_INVOCATION_STARTED",
                evidence_references={
                    "attempt_id": attempt_id,
                    "claim_key": claim_key,
                    "candidate": candidate,
                    "operator_action_id": action_id,
                },
                created_at=now + timedelta(seconds=index * 2),
            ),
            OrchestrationStageEvent(
                run_id=run_id,
                to_stage=OrchestrationStage.IMPLEMENTING,
                event_type="STAGE_INVOCATION_COMPLETED",
                evidence_references={
                    "attempt_id": attempt_id,
                    "claim_key": claim_key,
                    "status": "COMPLETE",
                    "result": {"changed": changed, "validation": {"status": "PASS"}},
                },
                created_at=now + timedelta(seconds=index * 2 + 1),
            ),
        ])
    return run, actions, events, identity


def test_detects_only_same_candidate_validated_update_then_validated_noop():
    run, actions, events, identity = _sequence()

    diagnosis = diagnose_lost_apply_checkpoint(run, actions, events)

    assert diagnosis["status"] == "RECOVERABLE"
    assert diagnosis["identity"] == identity
    assert diagnosis["prior_action_id"] == "operator-disposition"
    assert diagnosis["no_op_action_id"] == "operator-noop"
    assert diagnosis["current_dispositions"] == {"3.2": "pending", "4.1": "deferred"}
    gate = recovery_gate_payload(run, diagnosis)
    assert gate["gate"] == RECOVERY_GATE
    assert gate["options"][0]["response_text"] == REBASELINE_RESPONSE
    assert gate["recovery_evidence"]["prior_snapshot"]["completed"] == ["3.2"]


def test_fails_closed_when_identity_or_durable_update_evidence_is_ambiguous():
    run, actions, events, _ = _sequence()
    events[0].evidence_references["candidate"]["candidate_sha"] = "b" * 40

    diagnosis = diagnose_lost_apply_checkpoint(run, actions, events)

    assert diagnosis["status"] == "BLOCKED"
    assert "única" in diagnosis["reason"] or "invocación" in diagnosis["reason"]
    assert not any(event.event_type == "APPLY_CHECKPOINT_REBASELINED" for event in events)


def test_fails_closed_when_same_candidate_update_has_no_terminal_event():
    run, actions, events, _ = _sequence()
    events = [event for event in events if event.event_type != "STAGE_INVOCATION_COMPLETED"]

    diagnosis = diagnose_lost_apply_checkpoint(run, actions, events)

    assert diagnosis["status"] == "BLOCKED"
    assert "activa" in diagnosis["reason"] or "cierre durable" in diagnosis["reason"]


def test_fails_closed_when_snapshot_candidate_identity_does_not_match():
    run, actions, events, _ = _sequence()
    run.stop_details["apply_snapshot"]["sha"] = "b" * 40

    diagnosis = diagnose_lost_apply_checkpoint(run, actions, events)

    assert diagnosis["status"] == "BLOCKED"
    assert "snapshot" in diagnosis["reason"]


@pytest.mark.parametrize(
    ("validation_status", "expected_apply_count"),
    [("PASS", 1), ("FAIL", 0)],
)
@pytest.mark.asyncio
async def test_explicit_rebaseline_dispatches_only_one_apply_on_same_candidate(
    tmp_path: Path, validation_status: str, expected_apply_count: int
):
    uow = InMemoryPersistenceUnitOfWork()
    repo = tmp_path / "repo"
    managed = tmp_path / "worktrees"
    repo.mkdir()
    managed.mkdir()
    worktree = managed / "issue-387-candidate"
    worktree.mkdir()
    subprocess.run(["git", "init", "-q", str(worktree)], check=True)
    subprocess.run(["git", "-C", str(worktree), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(worktree), "config", "user.email", "test@example.test"], check=True)
    change_name = "req-387-recover-overwritten-apply-disposition"
    tasks_path = worktree / "openspec" / "changes" / change_name / "tasks.md"
    tasks_path.parent.mkdir(parents=True)
    tasks_path.write_text(
        "- [ ] 3.2 Pending task\n- [ ] 4.1 [DEFERRED] Live Run proof\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(worktree), "add", "."], check=True)
    subprocess.run(["git", "-C", str(worktree), "commit", "-qm", "candidate"], check=True)
    setup_managed_repository_fixture(
        uow, "mini-me", repo, managed,
        canonical_repository_identity="github.com/silverberdi/mini-me",
    )
    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
    )
    coordinator.openspec_adapter.validate_change_strict = MagicMock(return_value={
        "status": validation_status, "returncode": 0 if validation_status == "PASS" else 1,
        "stdout": "valid" if validation_status == "PASS" else "invalid",
        "stderr": "" if validation_status == "PASS" else "strict validation failed",
    })
    coordinator.worktree_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=worktree, branch_name="feature/387", base_sha="base")
    )
    coordinator.agent_runner.resolve_workflow = MagicMock(return_value=MagicMock())
    candidate_sha = subprocess.check_output(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
    ).strip()
    run = OrchestrationRun(
        run_id="run-387-one-apply",
        project_id="mini-me",
        change_name=change_name,
        base_sha="base",
        current_stage=OrchestrationStage.IMPLEMENTING,
        resumable_stage=OrchestrationStage.IMPLEMENTING,
        current_candidate_sha=candidate_sha,
        human_gate="NEEDS_HUMAN",
        stop_outcome="NEEDS_HUMAN",
        is_active=True,
        stop_details={
            "issue_number": 387,
            "issue_title": "Recover lost Apply checkpoint",
            "request_normalization": {"normalized_body": f"OpenSpec: `{change_name}`"},
            "complexity_assessment": {"feasibility_status": "EXECUTABLE"},
            "apply_total_attempts": 3,
            "apply_no_progress": 2,
            "apply_snapshot": {
                "run_id": "run-387-one-apply", "sha": candidate_sha,
                "branch": "feature/387", "worktree": str(worktree.resolve()),
                "completed": ["3.2"], "pending": [],
            },
            "human_payload": {
                "gate_id": "old-gate", "gate": "apply_escalation",
                "stage": "IMPLEMENTING", "question": "Continue?", "options": [],
            },
        },
    )
    update_identity = await coordinator._stage_candidate_identity(run, worktree, "UPDATE")
    run.stop_details["apply_snapshot"]["branch"] = update_identity["branch"]
    run.stop_details["apply_snapshot"]["worktree"] = update_identity["worktree"]
    prior_action_id, noop_action_id, auth_action_id = "prior-387", "noop-387", "rebaseline-387"
    run.stop_details["apply_gate_update"] = {
        "status": "VALIDATED", "changed": False,
        "operator_action_id": noop_action_id, "change_name": change_name,
        "before": update_identity, "after": update_identity,
        "reclassified_tasks": [],
        "task_dispositions_after": {"3.2": "pending", "4.1": "deferred"},
        "validation": {"status": "PASS"},
    }
    uow.orchestration_runs.save(run)
    for action_id, gate, response, state in (
        (prior_action_id, "physical_validation", "defer live check", OperatorActionStatus.COMPLETED),
        (noop_action_id, "apply_escalation", "continue", OperatorActionStatus.COMPLETED),
    ):
        uow.operator_actions.save(OperatorActionRecord(
            action_request_id=action_id, project_id="mini-me", change_name=change_name,
            run_id=run.run_id, action_type=OperatorActionType.RESOLVE_GATE,
            precondition_gate=gate, status=state,
            parameters_json={"accepted_response": response},
        ))
    now = datetime.now(UTC)
    for index, (action_id, changed) in enumerate(((prior_action_id, True), (noop_action_id, False))):
        attempt_id = f"update-387-{index}"
        claim_key = f"stage-invocation:{run.run_id}:UPDATE:{index}"
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            run_id=run.run_id, to_stage=OrchestrationStage.IMPLEMENTING,
            event_type="STAGE_INVOCATION_STARTED",
            evidence_references={
                "attempt_id": attempt_id, "claim_key": claim_key,
                "candidate": update_identity, "operator_action_id": action_id,
            },
            created_at=now + timedelta(seconds=index * 2),
        ))
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            run_id=run.run_id, to_stage=OrchestrationStage.IMPLEMENTING,
            event_type="STAGE_INVOCATION_COMPLETED",
            evidence_references={
                "attempt_id": attempt_id, "claim_key": claim_key, "status": "COMPLETE",
                "result": {"changed": changed, "validation": {"status": "PASS"}},
            },
            created_at=now + timedelta(seconds=index * 2 + 1),
        ))
    diagnosis = diagnose_lost_apply_checkpoint(
        run, uow.operator_actions.list_by_run(run.run_id),
        uow.orchestration_stage_events.list_by_run(run.run_id),
    )
    gate = recovery_gate_payload(run, diagnosis)
    run.stop_details["human_payload"] = gate
    run.human_gate = HumanGate.NEEDS_HUMAN
    run.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
    uow.orchestration_runs.save(run)
    auth_params = {
        "accepted_response": REBASELINE_RESPONSE,
        "gate_fingerprint": human_gate_fingerprint(run.run_id, run.current_stage, gate),
        "response_fingerprint": hashlib.sha256(REBASELINE_RESPONSE.encode()).hexdigest(),
    }
    uow.operator_actions.save(OperatorActionRecord(
        action_request_id=auth_action_id, project_id="mini-me", change_name=change_name,
        run_id=run.run_id, action_type=OperatorActionType.RESOLVE_GATE,
        precondition_gate=RECOVERY_GATE, status=OperatorActionStatus.ACCEPTED,
        parameters_json=auth_params,
    ))
    apply_outcome = ApplyOutcome(
        status="PARTIAL", completed_tasks=(), pending_tasks=("3.2", "4.1"),
        candidate_sha=candidate_sha, changed_files=(), diff_fingerprint="same",
        tests_passed=None, test_evidence="simulated Apply result",
        branch=update_identity["branch"], worktree=update_identity["worktree"],
        run_id=run.run_id,
    )
    coordinator._run_apply = AsyncMock(return_value=apply_outcome)

    result = await coordinator.execute_project_request(
        "mini-me", target_run_id=run.run_id,
        operator_clarification=REBASELINE_RESPONSE,
        operator_action_id=auth_action_id,
    )

    stored = uow.orchestration_runs.get_by_id(run.run_id)
    apply_events = [
        event for event in uow.orchestration_stage_events.list_by_run(run.run_id)
        if event.event_type == "STAGE_INVOCATION_STARTED"
        and ":APPLY:" in (event.evidence_references or {}).get("claim_key", "")
    ]
    assert result.status == "HUMAN_REQUIRED"
    assert coordinator._run_apply.await_count == expected_apply_count, (result.message, stored.stop_details)
    assert len(apply_events) == expected_apply_count
    if validation_status == "PASS":
        assert apply_events[0].evidence_references["operator_action_id"] == auth_action_id
        assert apply_events[0].evidence_references["candidate"]["run_id"] == run.run_id
        assert apply_events[0].evidence_references["candidate"]["candidate_sha"] == candidate_sha
        assert stored.stop_details["apply_checkpoint_recovery"]["status"] == "AUTHORIZED"
        assert stored.stop_details["apply_total_attempts"] == 1
    else:
        assert stored.stop_details["apply_checkpoint_recovery"]["status"] == "BLOCKED"
        return

    replay_result = await coordinator.execute_project_request(
        "mini-me", target_run_id=run.run_id,
        operator_clarification=REBASELINE_RESPONSE,
        operator_action_id=auth_action_id,
    )
    assert replay_result.status == "HUMAN_REQUIRED"
    assert coordinator._run_apply.await_count == 1
    replayed_apply_events = [
        event for event in uow.orchestration_stage_events.list_by_run(run.run_id)
        if event.event_type == "STAGE_INVOCATION_STARTED"
        and ":APPLY:" in (event.evidence_references or {}).get("claim_key", "")
    ]
    assert len(replayed_apply_events) == 1


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database",
)
def test_postgres_api_presents_evidence_and_atomically_records_rebaseline(
    monkeypatch, tmp_path: Path
):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, run_id = str(uuid4()), str(uuid4())
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    action_ids = ["prior-disposition", "noop-update"]
    try:
        with engine.connect() as connection:
            name = connection.execute(text("select current_database()")).scalar_one()
            assert "test" in name.lower(), "Refusing to write outside a test database"
        subprocess.run(["git", "init", "-q", str(worktree)], check=True)
        subprocess.run(["git", "-C", str(worktree), "config", "user.name", "integration"], check=True)
        subprocess.run(["git", "-C", str(worktree), "config", "user.email", "integration@example.test"], check=True)
        change_name = "req-387-recover-overwritten-apply-disposition"
        tasks = worktree / "openspec" / "changes" / change_name / "tasks.md"
        tasks.parent.mkdir(parents=True)
        tasks.write_text(
            "- [ ] 3.2 Pending API evidence\n- [ ] 4.1 [DEFERRED] Live Run proof\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(worktree), "add", "."], check=True)
        subprocess.run(["git", "-C", str(worktree), "commit", "-qm", "candidate"], check=True)

        uow = PostgresPersistenceUnitOfWork(session)
        coordinator = NativeOrchestrationCoordinator(
            uow_factory=lambda: uow,
            github_adapter=MagicMock(),
            worktree_manager=MagicMock(),
            agent_runner=MagicMock(),
        )
        coordinator.openspec_adapter.validate_change_strict = MagicMock(return_value={
            "status": "PASS", "returncode": 0, "stdout": "valid", "stderr": "",
        })
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name=change_name,
            base_sha="base-sha",
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            current_candidate_sha=subprocess.check_output(
                ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
            ).strip(),
            human_gate=HumanGate.NEEDS_HUMAN,
            stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
            is_active=True,
        )
        checkpoint_identity = asyncio.run(
            coordinator._stage_candidate_identity(run, worktree, "UPDATE")
        )
        prior_action, noop_action = action_ids
        run.stop_details = {
            "issue_number": 387,
            "apply_snapshot": {
                "run_id": run_id, "sha": run.current_candidate_sha,
                "branch": checkpoint_identity["branch"],
                "worktree": checkpoint_identity["worktree"],
                "completed": ["3.2"], "pending": [],
            },
            "apply_gate_update": {
                "status": "VALIDATED", "changed": False,
                "operator_action_id": noop_action, "change_name": change_name,
                "before": checkpoint_identity, "after": checkpoint_identity,
                "reclassified_tasks": [],
                "task_dispositions_after": {"3.2": "pending", "4.1": "deferred"},
                "validation": {"status": "PASS"},
            },
            "human_payload": {
                "gate_id": "old-apply-gate", "gate": "apply_escalation",
                "stage": "IMPLEMENTING", "question": "Continue Apply?", "options": [],
            },
        }
        uow.projects.save(Project(
            project_id=project_id,
            display_name="Issue 387 recovery integration",
            repository="org/issue-387-recovery-e2e",
        ))
        uow.project_managed_repository_bindings.save(ProjectManagedRepositoryBinding(
            project_id=project_id,
            canonical_repository_identity="github.com/org/issue-387-recovery-e2e",
            managed_repository_root=str(tmp_path / "managed"),
            worktree_parent_dir=str(tmp_path / "worktrees"),
        ))
        uow.orchestration_runs.save(run)
        for action_id, gate in ((prior_action, "physical_validation"), (noop_action, "apply_escalation")):
            uow.operator_actions.save(OperatorActionRecord(
                action_request_id=action_id,
                project_id=project_id,
                change_name=change_name,
                run_id=run_id,
                action_type=OperatorActionType.RESOLVE_GATE,
                precondition_gate=gate,
                status=OperatorActionStatus.COMPLETED,
                parameters_json={"accepted_response": "Recorded operator response."},
            ))
        now = datetime.now(UTC)
        for index, (action_id, changed) in enumerate(((prior_action, True), (noop_action, False))):
            attempt_id = f"update-{index}"
            candidate = {**checkpoint_identity, "stage": "UPDATE"}
            claim_key = f"stage-invocation:{run_id}:UPDATE:{index}"
            uow.orchestration_stage_events.save(OrchestrationStageEvent(
                run_id=run_id, to_stage=OrchestrationStage.IMPLEMENTING,
                event_type="STAGE_INVOCATION_STARTED",
                evidence_references={
                    "attempt_id": attempt_id, "claim_key": claim_key,
                    "candidate": candidate, "operator_action_id": action_id,
                },
                created_at=now + timedelta(seconds=index * 2),
            ))
            uow.orchestration_stage_events.save(OrchestrationStageEvent(
                run_id=run_id, to_stage=OrchestrationStage.IMPLEMENTING,
                event_type="STAGE_INVOCATION_COMPLETED",
                evidence_references={
                    "attempt_id": attempt_id, "claim_key": claim_key,
                    "status": "COMPLETE",
                    "result": {"changed": changed, "validation": {"status": "PASS"}},
                },
                created_at=now + timedelta(seconds=index * 2 + 1),
            ))
        uow.commit()

        operator = AuthorizedOperator(email="operator@example.test", name="Operator", roles=["admin"])
        app.dependency_overrides[get_uow] = lambda: uow
        app.dependency_overrides[get_current_operator] = lambda: operator
        scheduled = []
        monkeypatch.setattr(
            "minime.api.app._schedule_request_worker",
            lambda project, body, key: scheduled.append((project, body, key)) or "recovery-operation",
        )
        with TestClient(app) as client:
            projected_response = client.get(
                "/api/v1/orchestration/runs",
                params={"project_id": project_id, "is_active": "true"},
            )
            projected = next(row for row in projected_response.json() if row["run_id"] == run_id)
            gate = projected["stop_details"]["human_payload"]
            response = client.post(
                f"/api/v1/projects/{project_id}/requests/run",
                json={"operator_clarification": REBASELINE_RESPONSE},
            )
        assert gate["gate"] == RECOVERY_GATE
        assert gate["recovery_status"] == "RECOVERABLE"
        assert gate["recovery_evidence"]["current_dispositions"] == {
            "3.2": "pending", "4.1": "deferred",
        }
        assert response.status_code == 202
        assert response.json()["status"] == "ACCEPTED"
        assert len(scheduled) == 1

        accepted_action = uow.operator_actions.get_by_request_id(response.json()["idempotency_key"])
        current_run = uow.orchestration_runs.get_by_id(run_id)
        current_gate = current_run.stop_details["human_payload"]
        authorized, blocked = asyncio.run(coordinator._authorize_apply_checkpoint_recovery(
            uow=uow,
            run=current_run,
            worktree_path=worktree,
            change_name=change_name,
            diagnosis=diagnose_lost_apply_checkpoint(
                current_run,
                uow.operator_actions.list_by_run(run_id),
                uow.orchestration_stage_events.list_by_run(run_id),
            ),
            gate_payload=current_gate,
            operator_action_id=accepted_action.action_request_id,
            operator_response=REBASELINE_RESPONSE,
        ))
        assert authorized is True and blocked is None
        stored = uow.orchestration_runs.get_by_id(run_id)
        action = uow.operator_actions.get_by_request_id(accepted_action.action_request_id)
        events = uow.orchestration_stage_events.list_by_run(run_id)
        recovery_events = [event for event in events if event.event_type == "APPLY_CHECKPOINT_REBASELINED"]
        assert action.status == OperatorActionStatus.COMPLETED
        assert stored.stop_details["apply_checkpoint_recovery"]["status"] == "AUTHORIZED"
        assert stored.stop_details["apply_checkpoint_recovery"]["apply_baseline"]["pending"] == ["3.2", "4.1"]
        assert len(recovery_events) == 1
        assert recovery_events[0].evidence_references["prior_snapshot"]["completed"] == ["3.2"]
        assert stored.stop_details["apply_snapshot"]["completed"] == ["3.2"]
    finally:
        app.dependency_overrides.clear()
        session.rollback()
        session.execute(text("DELETE FROM orchestration_stage_events WHERE run_id = :run_id"), {"run_id": run_id})
        session.execute(text("DELETE FROM operator_action_records WHERE run_id = :run_id"), {"run_id": run_id})
        session.execute(text("DELETE FROM orchestration_runs WHERE id = :run_id"), {"run_id": run_id})
        session.execute(text("DELETE FROM project_managed_repository_bindings WHERE project_id = :project_id"), {"project_id": project_id})
        session.execute(text("DELETE FROM projects WHERE id = :project_id"), {"project_id": project_id})
        session.commit()
        session.close()
        engine.dispose()
