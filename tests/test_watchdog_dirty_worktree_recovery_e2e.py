"""End-to-end integration proof for autonomous watchdog dirty worktree recovery (Issue #530).

Proves that an interrupted Apply invocation whose agent died leaving dirty worktree files
is mechanically rebaselined, candidate identity recalculated, claim reacquired, and invocation
resumed with recovery_count=1 without opening a spurious human gate.
"""

from __future__ import annotations

import os
import socket
import subprocess
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import OrchestrationStage, WorktreeCreationState
from minime.domain.models import (
    OrchestrationRun,
    OrchestrationStageEvent,
    OrchestrationWorktreeOwnership,
    Project,
    utc_now,
)
from minime.services import orchestration_coordinator as coordinator_module
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeManager

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _setup_git_environment(tmp_path: Path, change_name: str):
    repo = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "minime-tester")
    _git(repo, "config", "user.email", "tester@example.com")

    # Initial commit
    (repo / "tracked.py").write_text("print('clean candidate')\n")
    _git(repo, "add", "tracked.py")
    _git(repo, "commit", "-m", "initial candidate commit")

    candidate_sha = _git(repo, "rev-parse", "HEAD")

    # Create worktree
    _git(repo, "worktree", "add", "-b", f"feature/{change_name}", str(worktree), "HEAD")

    # Create proposal artifact in worktree
    proposal_dir = worktree / "openspec" / "changes" / change_name
    proposal_dir.mkdir(parents=True, exist_ok=True)
    proposal_path = proposal_dir / "proposal.md"
    proposal_path.write_text("# Change Proposal\nTargeted change proposal content.\n")

    return repo, worktree, candidate_sha


@pytest.mark.asyncio
async def test_watchdog_dirty_worktree_autonomous_recovery_in_memory(tmp_path: Path, monkeypatch):
    """Test full dirty apply worktree recovery without spurious gate using in-memory UOW."""
    change_name = "issue-530-recovery-proof"
    repo, worktree, candidate_sha = _setup_git_environment(tmp_path, change_name)

    uow = InMemoryPersistenceUnitOfWork()
    project_id = str(uuid4())
    run_id = str(uuid4())

    run = OrchestrationRun(
        run_id=run_id,
        project_id=project_id,
        change_name=change_name,
        base_sha="main",
        current_candidate_sha=candidate_sha,
        current_stage=OrchestrationStage.IMPLEMENTING,
        current_generation=1,
    )
    uow.orchestration_runs.save(run)

    ownership = OrchestrationWorktreeOwnership(
        ownership_id=str(uuid4()),
        project_id=project_id,
        job_id=str(uuid4()),
        run_id=run_id,
        change_name=change_name,
        canonical_worktree_path=str(worktree.resolve()),
        source_repository_identity="github.com/org/dirty-worktree-test",
        source_base_sha=candidate_sha,
        branch=f"feature/{change_name}",
        creation_state=WorktreeCreationState.CREATED,
    )
    uow.orchestration_worktree_ownerships.save(ownership)

    async def _mock_verify(**kwargs):
        return None

    manager = WorktreeManager(project_root=repo, uow=uow)
    monkeypatch.setattr(manager, "_authorize_mutating_operation", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "_verify_worktree_adoption_proof", _mock_verify)

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=SimpleNamespace(),
        worktree_manager=manager,
        agent_runner=SimpleNamespace(),
    )
    coordinator.watchdog_mechanical_remediation = True

    # 1. Candidate computation prior to start
    clean_candidate = await coordinator._stage_candidate_identity(run, worktree, "APPLY")
    fingerprint = clean_candidate["fingerprint"]
    prior_claim_key = f"stage-invocation:{run_id}:APPLY:{fingerprint}"

    # 2. Acquire prior claim that expired
    prior_claim = uow.claims.acquire_or_reacquire(
        claim_key=prior_claim_key,
        owner_instance_id="prior-dead-runner",
        lease_seconds=-10,  # Expired lease
    )
    assert prior_claim is not None

    old_coordinator_identity = {
        "status": "AVAILABLE",
        "host": socket.gethostname(),
        "boot_id": "old-boot",
        "pid": 99999999,
        "start_marker": "marker-old",
    }
    dead_workflow_identity = {
        "status": "AVAILABLE",
        "host": socket.gethostname(),
        "boot_id": "old-boot",
        "pid": 99999998,
        "start_marker": "agent-dead",
    }
    current_coordinator_identity = {
        "status": "AVAILABLE",
        "host": socket.gethostname(),
        "boot_id": "current-boot",
        "pid": os.getpid(),
        "start_marker": "current",
    }
    monkeypatch.setattr(coordinator_module, "process_identity", lambda: current_coordinator_identity)

    # 3. Simulate an interrupted Apply invocation
    prior_attempt_id = str(uuid4())
    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run_id,
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            event_type="STAGE_INVOCATION_STARTED",
            evidence_references={
                "attempt_id": prior_attempt_id,
                "claim_key": prior_claim_key,
                "fence_token": prior_claim.fence_token,
                "candidate": clean_candidate,
                "coordinator_process": old_coordinator_identity,
                "recovery_count": 0,
            },
        )
    )
    uow.orchestration_stage_events.save(
        OrchestrationStageEvent(
            run_id=run_id,
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            event_type="STAGE_INVOCATION_PROCESS_STARTED",
            evidence_references={
                "attempt_id": prior_attempt_id,
                "claim_key": prior_claim_key,
                "process_identity": dead_workflow_identity,
            },
        )
    )

    # Watchdog diagnosis in OBSERVED state
    diagnoses_saved = []
    test_diagnosis = {
        "run_id": run_id,
        "stage": "APPLY",
        "generation": 1,
        "status": "OBSERVED",
        "root_cause": "orphaned_stage_process",
    }
    uow.watchdog = SimpleNamespace(
        get_by_run_stage_generation=lambda r, s, g: test_diagnosis if s == "APPLY" else None,
        save_diagnosis=lambda d: diagnoses_saved.append(d),
    )

    # 4. Agent left dirty tracked file and untracked debris in the worktree
    (worktree / "tracked.py").write_text("print('dirty interrupted agent edit')\n")
    (worktree / "debris.astro").write_text("export default function Scratch() {}\n")

    # Verify worktree is indeed dirty before recovery
    assert (worktree / "tracked.py").read_text() != "print('clean candidate')\n"
    assert (worktree / "debris.astro").exists()

    # 5. Coordinate stage invocation - autonomous recovery must trigger
    recovered = await coordinator._begin_stage_invocation(uow, run, worktree, "APPLY")

    # 6. Verify autonomous recovery succeeded
    assert recovered is not None
    assert recovered.recovery_count == 1
    assert recovered.recovered_from_attempt_id == prior_attempt_id
    assert recovered.candidate["candidate_sha"] == candidate_sha

    # Verify worktree rebaseline effects
    assert (worktree / "tracked.py").read_text() == "print('clean candidate')\n"
    assert not (worktree / "debris.astro").exists()
    # Proposal must be strictly preserved
    assert (worktree / "openspec" / "changes" / change_name / "proposal.md").exists()
    assert "# Change Proposal" in (worktree / "openspec" / "changes" / change_name / "proposal.md").read_text()

    # Verify NO human gate was opened
    assert run.human_gate is None

    # Verify stage events emitted
    events = uow.orchestration_stage_events.list_by_run(run_id)
    event_types = [e.event_type for e in events]
    assert "STAGE_INVOCATION_ABANDONED" in event_types
    assert "WATCHDOG_WORKTREE_REMEDIATED" in event_types

    abandoned_event = next(e for e in events if e.event_type == "STAGE_INVOCATION_ABANDONED")
    assert abandoned_event.evidence_references["worktree_reset"] is True
    assert abandoned_event.evidence_references["recovery_count"] == 1

    remediated_event = next(e for e in events if e.event_type == "WATCHDOG_WORKTREE_REMEDIATED")
    assert remediated_event.evidence_references["remediated"] is True
    assert remediated_event.evidence_references["candidate_sha"] == candidate_sha

    # Verify diagnosis was marked RESOLVED
    assert len(diagnoses_saved) >= 1
    assert diagnoses_saved[-1]["status"] == "RESOLVED"


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database",
)
@pytest.mark.asyncio
async def test_watchdog_dirty_worktree_autonomous_recovery_postgres(tmp_path: Path, monkeypatch):
    """PostgreSQL integration proof: dirty apply recovery under real DB concurrency and claims."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from minime.db.repository import PostgresPersistenceUnitOfWork

    change_name = "issue-530-pg-recovery"
    repo, worktree, candidate_sha = _setup_git_environment(tmp_path, change_name)

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as connection:
        assert connection.execute(text("select current_database()")).scalar_one() == "minime_test"

    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        uow = PostgresPersistenceUnitOfWork(session)
        project_id = str(uuid4())
        run_id = str(uuid4())

        project = Project(
            project_id=project_id,
            display_name="Dirty Worktree PG Test",
            repository="org/dirty-worktree-test",
        )
        uow.projects.save(project)
        setup_managed_repository_fixture(
            uow, project_id, repo, repo / ".minime" / "worktrees",
            canonical_repository_identity="github.com/org/dirty-worktree-test",
            local_remote=False,
        )
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name=change_name,
            base_sha="main",
            current_candidate_sha=candidate_sha,
            current_stage=OrchestrationStage.IMPLEMENTING,
            current_generation=1,
        )
        uow.orchestration_runs.save(run)
        ownership = OrchestrationWorktreeOwnership(
            ownership_id=str(uuid4()),
            project_id=project_id,
            job_id=str(uuid4()),
            run_id=run_id,
            change_name=change_name,
            canonical_worktree_path=str(worktree.resolve()),
            source_repository_identity="github.com/org/dirty-worktree-test",
            source_base_sha=candidate_sha,
            branch=f"feature/{change_name}",
            creation_state=WorktreeCreationState.CREATED,
        )
        uow.orchestration_worktree_ownerships.save(ownership)
        uow.commit()

        async def _mock_verify_pg(**kwargs):
            return None

        manager = WorktreeManager(project_root=repo, uow=uow)
        monkeypatch.setattr(manager, "_authorize_mutating_operation", lambda *args, **kwargs: None)
        monkeypatch.setattr(manager, "_verify_worktree_adoption_proof", _mock_verify_pg)

        coordinator = NativeOrchestrationCoordinator(
            uow_factory=lambda: uow,
            github_adapter=SimpleNamespace(),
            worktree_manager=manager,
            agent_runner=SimpleNamespace(),
        )
        coordinator.watchdog_mechanical_remediation = True

        clean_candidate = await coordinator._stage_candidate_identity(run, worktree, "APPLY")
        fingerprint = clean_candidate["fingerprint"]
        prior_claim_key = f"stage-invocation:{run_id}:APPLY:{fingerprint}"

        prior_claim = uow.claims.acquire_or_reacquire(
            claim_key=prior_claim_key,
            owner_instance_id="prior-dead-pg-runner",
            lease_seconds=-10,
        )
        assert prior_claim is not None
        uow.commit()

        old_coordinator_identity = {
            "status": "AVAILABLE",
            "host": socket.gethostname(),
            "boot_id": "old-boot",
            "pid": 99999999,
            "start_marker": "marker-old",
        }
        dead_workflow_identity = {
            "status": "AVAILABLE",
            "host": socket.gethostname(),
            "boot_id": "old-boot",
            "pid": 99999998,
            "start_marker": "agent-dead",
        }
        current_coordinator_identity = {
            "status": "AVAILABLE",
            "host": socket.gethostname(),
            "boot_id": "current-boot",
            "pid": os.getpid(),
            "start_marker": "current",
        }
        monkeypatch.setattr(coordinator_module, "process_identity", lambda: current_coordinator_identity)

        prior_attempt_id = str(uuid4())
        uow.orchestration_stage_events.save(
            OrchestrationStageEvent(
                run_id=run_id,
                from_stage=OrchestrationStage.IMPLEMENTING,
                to_stage=OrchestrationStage.IMPLEMENTING,
                event_type="STAGE_INVOCATION_STARTED",
                evidence_references={
                    "attempt_id": prior_attempt_id,
                    "claim_key": prior_claim_key,
                    "fence_token": prior_claim.fence_token,
                    "candidate": clean_candidate,
                    "coordinator_process": old_coordinator_identity,
                    "recovery_count": 0,
                },
            )
        )
        uow.orchestration_stage_events.save(
            OrchestrationStageEvent(
                run_id=run_id,
                from_stage=OrchestrationStage.IMPLEMENTING,
                to_stage=OrchestrationStage.IMPLEMENTING,
                event_type="STAGE_INVOCATION_PROCESS_STARTED",
                evidence_references={
                    "attempt_id": prior_attempt_id,
                    "claim_key": prior_claim_key,
                    "process_identity": dead_workflow_identity,
                },
            )
        )
        uow.commit()

        # Add dirty files
        (worktree / "tracked.py").write_text("print('pg dirty uncommitted')\n")
        (worktree / "debris.astro").write_text("export default function PgDebris() {}\n")

        recovered = await coordinator._begin_stage_invocation(uow, run, worktree, "APPLY")

        assert recovered is not None
        assert recovered.recovery_count == 1
        assert recovered.recovered_from_attempt_id == prior_attempt_id
        assert (worktree / "tracked.py").read_text() == "print('clean candidate')\n"
        assert not (worktree / "debris.astro").exists()
        assert (worktree / "openspec" / "changes" / change_name / "proposal.md").exists()
        assert run.human_gate is None

        events = uow.orchestration_stage_events.list_by_run(run_id)
        event_types = [e.event_type for e in events]
        assert "STAGE_INVOCATION_ABANDONED" in event_types
        assert "WATCHDOG_WORKTREE_REMEDIATED" in event_types
    finally:
        session.close()
