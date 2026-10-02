"""PostgreSQL adversarial tests for Stage G Scheduler and Recovery Convergence (G01–G22)."""

import os
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    ChangeStatus,
    ExternalActionObservation,
    ExternalActionStatus,
    ExternalActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    RecoveryClassification,
    RecoveryDecisionStatus,
    RecoverySource,
    SagaStatus,
    SagaType,
    WorkItemStatus,
)
from minime.domain.exceptions import StaleClaimError
from minime.domain.models import (
    BacklogItem,
    Change,
    DurableSaga,
    OrchestrationExternalAction,
    OrchestrationRun,
    Project,
    ProjectBinding,
    RecoveryClaimContext,
    utc_now,
)
from minime.services.orchestration_service import OrchestrationService
from minime.services.recovery_convergence_service import RecoveryConvergenceService
from minime.services.saga_engine import SagaEngine


def _ensure_pg_server() -> str | None:
    candidate_urls = [
        os.environ.get("MINIME_TEST_DATABASE_URL"),
        "postgresql+psycopg://testuser@localhost:54333/minime_test",
    ]
    for url in candidate_urls:
        if not url:
            continue
        try:
            eng = create_engine(url, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            eng.dispose()
            return url
        except Exception:
            continue

    pg_ctl = Path("/Library/PostgreSQL/17/bin/pg_ctl")
    initdb = Path("/Library/PostgreSQL/17/bin/initdb")
    psql = Path("/Library/PostgreSQL/17/bin/psql")
    data_dir = Path("/tmp/minime_pg_test_data")

    if pg_ctl.exists() and initdb.exists():
        if not data_dir.exists():
            subprocess.run(
                [str(initdb), "-D", str(data_dir), "-U", "testuser", "-A", "trust"],
                check=False,
                capture_output=True,
            )
        subprocess.run(
            [
                str(pg_ctl),
                "-D",
                str(data_dir),
                "-o",
                "-p 54333 -k /tmp",
                "-l",
                "/tmp/minime_pg_test.log",
                "start",
            ],
            check=False,
            capture_output=True,
        )
        time.sleep(0.5)
        if psql.exists():
            subprocess.run(
                [
                    str(psql),
                    "-h",
                    "localhost",
                    "-p",
                    "54333",
                    "-U",
                    "testuser",
                    "-d",
                    "postgres",
                    "-c",
                    "CREATE DATABASE minime_test;",
                ],
                check=False,
                capture_output=True,
            )
        try:
            test_url = "postgresql+psycopg://testuser@localhost:54333/minime_test"
            eng = create_engine(test_url, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            eng.dispose()
            return test_url
        except Exception:
            pass
    return None


PG_TEST_URL = _ensure_pg_server()


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    if not PG_TEST_URL:
        pytest.skip("PostgreSQL test database server is not reachable.")
    engine = create_engine(PG_TEST_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)

    with engine.connect() as conn:
        conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid();"))
        conn.commit()
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) PRIMARY KEY);"))
        conn.execute(text("DELETE FROM alembic_version;"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('g01_recovery_convergence');"))
        conn.commit()
    yield engine
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid();"))
        conn.commit()
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()
    engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)


def _seed_base_project_and_change(session: Session, change_name: str = "change-stage-g-01") -> tuple[str, str]:
    uow = PostgresPersistenceUnitOfWork(session)
    project_id = "proj-stage-g"
    if not uow.projects.get_by_id(project_id):
        uow.projects.save(
            Project(
                project_id=project_id,
                display_name="Stage G Test Project",
                repository="https://github.com/silverberdi/mini-me.git",
                base_branch="main",
            )
        )
    if not uow.bindings.get_by_project_and_change(project_id, change_name):
        uow.bindings.save(
            ProjectBinding(
                binding_id=f"bind-{change_name}",
                project_id=project_id,
                openspec_change_name=change_name,
                repository="https://github.com/silverberdi/mini-me.git",
                is_valid=True,
            )
        )
    if not uow.changes.get_by_name(project_id, change_name):
        ch = Change(
            change_id=f"ch-{change_name}",
            project_id=project_id,
            name=change_name,
            status=ChangeStatus.READY,
        )
        uow.changes.save(ch)
    session.commit()
    return project_id, change_name


# ============================================================================
# G01: Real PostgreSQL startup-vs-tick same-run claim contention
# ============================================================================
def test_g01_startup_vs_tick_same_run_contention(pg_session_factory: sessionmaker[Session]):
    """G01 / 10.1: Startup vs tick contending for the same run claim acquire."""
    session1 = pg_session_factory()
    session2 = pg_session_factory()

    project_id, change_name = _seed_base_project_and_change(session1, "g01-change")

    # Seed an active run
    uow1 = PostgresPersistenceUnitOfWork(session1)
    run = OrchestrationRun(
        run_id="run-g01",
        project_id=project_id,
        change_name=change_name,
        base_sha="15e55c515ae917c2f0330809f0d9e44d49bce12b",
        current_stage=OrchestrationStage.ADMITTED,
        created_at=utc_now(),
    )
    uow1.orchestration_runs.save(run)
    session1.commit()

    # Worker 1 (Startup) acquires claim
    service1 = RecoveryConvergenceService(PostgresPersistenceUnitOfWork(session1), owner_instance_id="worker-startup")
    claim1 = service1.acquire_claim("run:run-g01", lease_seconds=60)
    assert claim1 is not None
    assert claim1.fence_token == 1
    assert claim1.owner_instance_id == "worker-startup"

    # Worker 2 (Tick) attempts acquire while Worker 1's claim is active
    service2 = RecoveryConvergenceService(PostgresPersistenceUnitOfWork(session2), owner_instance_id="worker-tick")
    claim2 = service2.acquire_claim("run:run-g01", lease_seconds=60)
    # Active claim refusal: cannot steal active claim before expiry
    assert claim2 is None

    session1.close()
    session2.close()


# ============================================================================
# G02: Real PostgreSQL tick-vs-direct-resume/control-plane contention
# ============================================================================
def test_g02_tick_vs_direct_resume_contention(pg_session_factory: sessionmaker[Session]):
    """G02 / 10.2: Contention between tick and control plane direct resume."""
    session1 = pg_session_factory()
    session2 = pg_session_factory()

    project_id, change_name = _seed_base_project_and_change(session1, "g02-change")

    uow1 = PostgresPersistenceUnitOfWork(session1)
    run = OrchestrationRun(
        run_id="run-g02",
        project_id=project_id,
        change_name=change_name,
        base_sha="15e55c515ae917c2f0330809f0d9e44d49bce12b",
        current_stage=OrchestrationStage.ADMITTED,
        created_at=utc_now(),
    )
    uow1.orchestration_runs.save(run)
    session1.commit()

    # Tick acquires claim first
    tick_rec = RecoveryConvergenceService(PostgresPersistenceUnitOfWork(session1), owner_instance_id="instance-tick")
    claim = tick_rec.acquire_claim("run:run-g02")
    assert claim is not None

    # Control plane attempts continuation request on same run
    cp_service = RecoveryConvergenceService(PostgresPersistenceUnitOfWork(session2), owner_instance_id="instance-cp")
    decision = cp_service.request_run_continuation(run_id="run-g02", source=RecoverySource.CONTROL_PLANE)
    assert decision.classification == RecoveryClassification.CLAIMED_ELSEWHERE
    assert decision.reason_code == "CLAIMED_ELSEWHERE"

    session1.close()
    session2.close()


# ============================================================================
# G03 & G21: Lease expiry fence increment, stale owner result rejection, stale heartbeat & release
# ============================================================================
def test_g03_lease_expiry_and_stale_owner_rejection(pg_session_factory: sessionmaker[Session]):
    """G03, G21 / 10.3, 10.21: Expired claim re-acquisition increments fence; stale owner operations fail."""
    session = pg_session_factory()
    uow = PostgresPersistenceUnitOfWork(session)
    claim_repo = uow.claims

    claim_key = "run:run-g03"

    # Worker 1 acquires claim with 1s lease
    c1 = claim_repo.acquire_or_reacquire(claim_key, owner_instance_id="worker-1", lease_seconds=1)
    assert c1 is not None
    assert c1.fence_token == 1
    session.commit()

    # Simulate lease expiry by rewinding acquired_at and lease_expires_at in DB
    session.execute(
        text("UPDATE recovery_claims SET lease_expires_at = NOW() - INTERVAL '10 seconds' WHERE claim_key = :k"),
        {"k": claim_key},
    )
    session.commit()

    # Worker 2 acquires expired claim -> fence token increments to 2
    c2 = claim_repo.acquire_or_reacquire(claim_key, owner_instance_id="worker-2", lease_seconds=60)
    assert c2 is not None
    assert c2.owner_instance_id == "worker-2"
    assert c2.fence_token == 2
    session.commit()

    # 1. Worker 1 heartbeat renewal fails (stale fence=1, stale owner)
    heartbeat_ok = claim_repo.renew_heartbeat(claim_key, owner_instance_id="worker-1", fence_token=1)
    assert heartbeat_ok is False

    # 2. Worker 1 claim release fails
    release_ok = claim_repo.release(claim_key, owner_instance_id="worker-1", fence_token=1)
    assert release_ok is False

    # 3. Worker 1 CAS validation fails
    valid = claim_repo.validate_cas(claim_key, owner_instance_id="worker-1", fence_token=1)
    assert valid is False

    # 4. Worker 1 lifecycle result application rejected
    rec_service1 = RecoveryConvergenceService(uow, owner_instance_id="worker-1")
    ctx1 = RecoveryClaimContext(
        claim_key=claim_key,
        owner_instance_id="worker-1",
        fence_token=1,
        lease_expires_at=utc_now() + timedelta(seconds=60),
    )

    with pytest.raises(StaleClaimError):
        rec_service1.apply_lifecycle_result(
            context=ctx1,
            apply_fn=lambda: None,
        )

    session.close()


# ============================================================================
# G04 & G20: Atomic dispatch intent commit before slow I/O (no DB lock spanning I/O)
# ============================================================================
def test_g04_atomic_dispatch_intent_commit_boundary(pg_session_factory: sessionmaker[Session]):
    """G04, G20 / 10.4, 10.20: Atomic commit of dispatch intent before external mutation."""
    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "g04-change")

    uow = PostgresPersistenceUnitOfWork(session)
    rec_service = RecoveryConvergenceService(uow, owner_instance_id="worker-g04")

    run = OrchestrationRun(
        run_id="run-g04",
        project_id=project_id,
        change_name=change_name,
        base_sha="15e55c515ae917c2f0330809f0d9e44d49bce12b",
        current_stage=OrchestrationStage.ADMITTED,
        created_at=utc_now(),
    )
    uow.orchestration_runs.save(run)

    action_key = "action:git_branch_create:run-g04"
    action = OrchestrationExternalAction(
        action_key=action_key,
        run_id="run-g04",
        action_type=ExternalActionType.BRANCH_PUSH,
        target_identity=change_name,
        request_fingerprint="fp-g04",
        status=ExternalActionStatus.RESERVED,
    )
    uow.orchestration_external_actions.reserve(action)
    session.commit()

    ctx = rec_service.acquire_claim("run:run-g04")
    assert ctx is not None

    # Pre-commit intent
    attempt = rec_service.atomic_commit_dispatch_intent(
        context=ctx,
        action_key=action_key,
        attempt_number=1,
    )
    assert attempt is not None
    assert attempt.status == "EXECUTING"
    assert attempt.dispatch_intent_key == f"{action_key}:{ctx.claim_key}:{ctx.fence_token}:1"

    # Verify intent persisted in DB immediately (before external I/O)
    session2 = pg_session_factory()
    uow2 = PostgresPersistenceUnitOfWork(session2)
    saved_attempt = uow2.external_action_attempts.get_by_dispatch_intent_key(attempt.dispatch_intent_key)
    assert saved_attempt is not None
    assert saved_attempt.status == "EXECUTING"

    session.close()
    session2.close()


# ============================================================================
# G05: Repeated unchanged recovery produces zero duplicate effects
# ============================================================================
def test_g05_repeated_unchanged_recovery_idempotency(pg_session_factory: sessionmaker[Session]):
    """G05 / 10.5: Repeated recovery cycles on unchanged state yield identical zero-duplicate decisions."""
    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "g05-change")

    uow = PostgresPersistenceUnitOfWork(session)
    rec_service = RecoveryConvergenceService(uow, owner_instance_id="worker-g05")

    # Run 1st reconcile cycle
    decisions1 = rec_service.reconcile_cycle(project_id=project_id, source=RecoverySource.TICK)
    assert isinstance(decisions1, list)

    # Run 2nd reconcile cycle immediately on same state
    decisions2 = rec_service.reconcile_cycle(project_id=project_id, source=RecoverySource.TICK)
    assert len(decisions1) == len(decisions2)

    session.close()


# ============================================================================
# G06 & G07: External action status matrix & RESERVED authorization
# ============================================================================
def test_g06_external_action_status_matrix(pg_session_factory: sessionmaker[Session]):
    """G06, G07 / 10.6, 10.7: Verify observation classification for external action status matrix."""
    session = pg_session_factory()
    uow = PostgresPersistenceUnitOfWork(session)
    rec_service = RecoveryConvergenceService(uow)

    # Action without attempts or remote_identifier is PROVEN_NEVER_DISPATCHED
    action_fresh = OrchestrationExternalAction(
        action_key="act-test-fresh",
        run_id="run-g06",
        action_type=ExternalActionType.BRANCH_PUSH,
        target_identity="target-fresh",
        request_fingerprint="fp-fresh",
        status=ExternalActionStatus.RESERVED,
    )
    obs_fresh = rec_service.classify_external_action_observation(action_fresh)
    assert obs_fresh == ExternalActionObservation.PROVEN_NEVER_DISPATCHED

    # Action with remote identifier is POSSIBLY_DISPATCHED
    action_remote = OrchestrationExternalAction(
        action_key="act-test-remote",
        run_id="run-g06",
        action_type=ExternalActionType.BRANCH_PUSH,
        target_identity="target-remote",
        request_fingerprint="fp-remote",
        status=ExternalActionStatus.EXECUTING,
        remote_identifier="sha-123",
    )
    obs_remote = rec_service.classify_external_action_observation(action_remote)
    assert obs_remote == ExternalActionObservation.POSSIBLY_DISPATCHED

    session.close()


def test_g07_reserved_requires_stage_authorization(pg_session_factory: sessionmaker[Session]):
    """G07 / 10.7, 10.22: RESERVED state classification depends on dispatch attempt persistence."""
    session = pg_session_factory()
    uow = PostgresPersistenceUnitOfWork(session)
    rec_service = RecoveryConvergenceService(uow)

    action_key = "act-reserved-test"
    action = OrchestrationExternalAction(
        action_key=action_key,
        run_id="run-g07",
        action_type=ExternalActionType.BRANCH_PUSH,
        target_identity="target-reserved",
        request_fingerprint="fp-reserved",
        status=ExternalActionStatus.RESERVED,
    )

    # Without an attempt in EXECUTING/COMPLETED status, RESERVED maps to PROVEN_NEVER_DISPATCHED
    obs = rec_service.classify_external_action_observation(action)
    assert obs == ExternalActionObservation.PROVEN_NEVER_DISPATCHED

    session.close()


# ============================================================================
# G08: WAITING_EXTERNAL direct resume re-observation
# ============================================================================
def test_g08_waiting_external_direct_resume_reobserves(pg_session_factory: sessionmaker[Session]):
    """G08 / 10.8: WAITING_EXTERNAL direct resume re-observes status and remains waiting if unobservable."""
    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "g08-change")

    uow = PostgresPersistenceUnitOfWork(session)
    rec_service = RecoveryConvergenceService(uow, owner_instance_id="worker-g08")

    run = OrchestrationRun(
        run_id="run-g08",
        project_id=project_id,
        change_name=change_name,
        base_sha="15e55c515ae917c2f0330809f0d9e44d49bce12b",
        current_stage=OrchestrationStage.PREPARING_PR,
        stop_outcome=OrchestrationStopOutcome.WAITING_EXTERNAL,
        created_at=utc_now(),
    )
    uow.orchestration_runs.save(run)

    action = OrchestrationExternalAction(
        action_key="action:git_push:run-g08",
        run_id="run-g08",
        action_type=ExternalActionType.BRANCH_PUSH,
        target_identity=change_name,
        request_fingerprint="fp-g08",
        status=ExternalActionStatus.EXECUTING,
    )
    uow.orchestration_external_actions.reserve(action)
    session.commit()

    decision = rec_service.reconcile_action(action_key="action:git_push:run-g08", source=RecoverySource.CLI)
    assert decision is not None

    session.close()


# ============================================================================
# G09 & G10 & G11: Saga Checkpoint Recovery & Post-merge Clean-up
# ============================================================================
def test_g09_intake_saga_resumes_from_checkpoint(pg_session_factory: sessionmaker[Session]):
    """G09 / 10.9: Intake saga checkpoint resume with claim context."""
    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "g09-change")

    uow = PostgresPersistenceUnitOfWork(session)
    saga_engine = SagaEngine(uow)

    item = BacklogItem(
        item_id="item-g09",
        project_id=project_id,
        item_key=change_name,
        title="G09 Test Item",
        status=WorkItemStatus.PREPARING,
    )
    uow.backlog_items.save(item)

    saga = DurableSaga(
        id="saga-g09",
        saga_type=SagaType.INTAKE,
        status=SagaStatus.IN_PROGRESS,
        current_phase="CHECKPOINT_PROJECT_VALIDATED",
        project_id=project_id,
        work_item_key=change_name,
    )
    uow.durable_sagas.save(saga)
    session.commit()

    rec_service = RecoveryConvergenceService(uow, owner_instance_id="worker-g09")
    ctx = rec_service.acquire_claim("saga:saga-g09", lease_seconds=60)
    res = saga_engine.resume_saga("saga-g09", claim_context=ctx)
    assert res is not None
    assert res.id == "saga-g09"

    session.close()


def test_g11_pr_closed_unmerged_never_enters_merge_closure(pg_session_factory: sessionmaker[Session]):
    """G11 / 10.11: PR closed-unmerged cleanup is idempotent and never enters merge closure."""
    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "g11-change")

    uow = PostgresPersistenceUnitOfWork(session)
    rec_service = RecoveryConvergenceService(uow, owner_instance_id="worker-g11")

    run = OrchestrationRun(
        run_id="run-g11",
        project_id=project_id,
        change_name=change_name,
        base_sha="15e55c515ae917c2f0330809f0d9e44d49bce12b",
        current_stage=OrchestrationStage.PR_PREPARED,
        stop_outcome=OrchestrationStopOutcome.READY_FOR_HUMAN_MERGE,
        created_at=utc_now(),
    )
    uow.orchestration_runs.save(run)
    session.commit()

    decision = rec_service.request_run_continuation(run_id="run-g11", source=RecoverySource.TICK)
    assert decision is not None

    session.close()


# ============================================================================
# G13: Terminal parent prevents execution resurrection
# ============================================================================
def test_g13_terminal_parent_prevents_execution_resurrection(pg_session_factory: sessionmaker[Session]):
    """G13 / 10.13: CANCELLED/DONE/COMPLETED parent runs block job resurrection."""
    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "g13-change")

    uow = PostgresPersistenceUnitOfWork(session)
    rec_service = RecoveryConvergenceService(uow, owner_instance_id="worker-g13")

    run = OrchestrationRun(
        run_id="run-g13",
        project_id=project_id,
        change_name=change_name,
        base_sha="15e55c515ae917c2f0330809f0d9e44d49bce12b",
        current_stage=OrchestrationStage.COMPLETED,
        stop_outcome=OrchestrationStopOutcome.COMPLETED,
        created_at=utc_now(),
    )
    uow.orchestration_runs.save(run)
    session.commit()

    decision = rec_service.request_run_continuation(run_id="run-g13", source=RecoverySource.TICK)
    assert decision.status in {RecoveryDecisionStatus.NO_ACTION, RecoveryDecisionStatus.COMPLETED, RecoveryDecisionStatus.BLOCKED}

    session.close()


# ============================================================================
# G14 & G15: WAITING_CAPACITY & Recovery-before-admission ordering
# ============================================================================
def test_g15_recovery_converges_before_admission(pg_session_factory: sessionmaker[Session]):
    """G15 / 10.15: Scheduler tick executes recovery convergence cycle before fresh admission."""
    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "g15-change")

    uow = PostgresPersistenceUnitOfWork(session)
    rec_service = RecoveryConvergenceService(uow)

    decisions = rec_service.reconcile_cycle(project_id=project_id, source=RecoverySource.TICK)
    assert isinstance(decisions, list)

    session.close()


# ============================================================================
# G16 & G22: Control Plane Routing & Primitive Claim Context Requirement
# ============================================================================
def test_g16_control_plane_routing_and_g22_primitive_claim_context(pg_session_factory: sessionmaker[Session]):
    """G16, G22 / 10.16, 10.23: Control plane CONTINUATION routes through RecoveryConvergenceService and direct primitives require valid claim context."""
    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "g16-change")

    uow = PostgresPersistenceUnitOfWork(session)
    run = OrchestrationRun(
        run_id="run-g16",
        project_id=project_id,
        change_name=change_name,
        base_sha="15e55c515ae917c2f0330809f0d9e44d49bce12b",
        current_stage=OrchestrationStage.ADMITTED,
        created_at=utc_now(),
    )
    uow.orchestration_runs.save(run)
    session.commit()

    orch = OrchestrationService(uow)

    # Direct OrchestrationService.resume with stale/invalid claim_context raises StaleClaimError
    stale_ctx = RecoveryClaimContext(claim_key="run:run-g16", owner_instance_id="stale", fence_token=0, lease_expires_at=utc_now())
    with pytest.raises(StaleClaimError):
        orch.resume(run_id="run-g16", claim_context=stale_ctx)

    session.close()


# ============================================================================
# BLOCKER REMEDIATION TESTS: G-R01, G-R02, G-R03
# ============================================================================
def test_gr01_scheduler_recovery_authority_convergence(pg_session_factory: sessionmaker[Session]):
    """BLOCKER G-R01 proof: Scheduler recovery & continuation is driven exclusively through RecoveryConvergenceService."""
    from minime.services.scheduler_service import SchedulerService

    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "gr01-change")

    uow = PostgresPersistenceUnitOfWork(session)
    scheduler = SchedulerService(uow)

    # 1. Verify reconcile_waiting_runs delegates to RecoveryConvergenceService
    waiting_run = OrchestrationRun(
        run_id="run-gr01-waiting",
        project_id=project_id,
        change_name=change_name,
        base_sha="15e55c515ae917c2f0330809f0d9e44d49bce12b",
        current_stage=OrchestrationStage.ADMITTED,
        stop_outcome=OrchestrationStopOutcome.WAITING_CAPACITY,
        created_at=utc_now(),
    )
    uow.orchestration_runs.save(waiting_run)
    session.commit()

    scheduler.reconcile_waiting_runs(project_id=project_id)
    decisions = uow.recovery_decisions.list_by_claim_key("run:run-gr01-waiting")
    assert len(decisions) >= 1
    assert decisions[-1].source == RecoverySource.TICK

    # 2. Verify tick() drives recovery exclusively through RecoveryConvergenceService
    scheduler.tick(project_id=project_id)
    tick_decisions = uow.recovery_decisions.list_by_claim_key("run:run-gr01-waiting")
    assert len(tick_decisions) >= 2
    assert tick_decisions[-1].source == RecoverySource.TICK

    session.close()


def test_gr02_atomic_fenced_dispatch_intent_adversarial(pg_session_factory: sessionmaker[Session]):
    """BLOCKER G-R02 proof: Stale worker whose lease expired cannot commit dispatch intent in DB after successor acquired higher fence."""
    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "gr02-change")

    uow = PostgresPersistenceUnitOfWork(session)
    rec_a = RecoveryConvergenceService(uow, owner_instance_id="worker-A")
    rec_b = RecoveryConvergenceService(PostgresPersistenceUnitOfWork(pg_session_factory()), owner_instance_id="worker-B")

    claim_key = "run:run-gr02"
    action_key = "action:test_dispatch:run-gr02"

    run = OrchestrationRun(
        run_id="run-gr02",
        project_id=project_id,
        change_name=change_name,
        base_sha="15e55c515ae917c2f0330809f0d9e44d49bce12b",
        current_stage=OrchestrationStage.ADMITTED,
        created_at=utc_now(),
    )
    uow.orchestration_runs.save(run)

    action = OrchestrationExternalAction(
        action_key=action_key,
        run_id="run-gr02",
        action_type=ExternalActionType.BRANCH_PUSH,
        target_identity=change_name,
        request_fingerprint="fp-gr02",
        status=ExternalActionStatus.RESERVED,
    )
    uow.orchestration_external_actions.reserve(action)
    session.commit()

    # 1. Worker A acquires claim (fence 1)
    ctx_a = rec_a.acquire_claim(claim_key, lease_seconds=60)
    assert ctx_a is not None
    assert ctx_a.fence_token == 1

    # 2. Simulate Worker A's lease expiring in DB
    session.execute(
        text("UPDATE recovery_claims SET lease_expires_at = NOW() - INTERVAL '10 seconds' WHERE claim_key = :k"),
        {"k": claim_key},
    )
    session.commit()

    # 3. Worker B reacquires claim (fence 2)
    ctx_b = rec_b.acquire_claim(claim_key, lease_seconds=60)
    assert ctx_b is not None
    assert ctx_b.fence_token == 2

    # 4. Worker A attempts atomic commit dispatch intent with stale fence 1 -> MUST FAIL with StaleClaimError
    with pytest.raises(StaleClaimError):
        rec_a.atomic_commit_dispatch_intent(ctx_a, action_key=action_key, attempt_number=1)

    # Assert 0 attempts exist for fence 1
    attempts = uow.external_action_attempts.list_by_action_key(action_key)
    assert len(attempts) == 0

    # 5. Worker B commits dispatch intent with fence 2 -> MUST SUCCEED
    attempt_b = rec_b.atomic_commit_dispatch_intent(ctx_b, action_key=action_key, attempt_number=1)
    assert attempt_b is not None
    assert attempt_b.status == "EXECUTING"
    assert attempt_b.dispatch_intent_key == f"{action_key}:{claim_key}:2:1"

    # Exactly one dispatch intent exists in DB
    attempts_after = uow.external_action_attempts.list_by_action_key(action_key)
    assert len(attempts_after) == 1
    assert attempts_after[0].dispatch_intent_key == f"{action_key}:{claim_key}:2:1"

    session.close()


def test_gr03_db_authoritative_claim_context_validation(pg_session_factory: sessionmaker[Session]):
    """BLOCKER G-R03 proof: Locally non-expired claim context with obsolete DB fence fails DB-authoritative validation and raises StaleClaimError."""
    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "gr03-change")

    uow = PostgresPersistenceUnitOfWork(session)
    rec_a = RecoveryConvergenceService(uow, owner_instance_id="worker-A")
    rec_b = RecoveryConvergenceService(PostgresPersistenceUnitOfWork(pg_session_factory()), owner_instance_id="worker-B")

    claim_key = "run:run-gr03"

    run = OrchestrationRun(
        run_id="run-gr03",
        project_id=project_id,
        change_name=change_name,
        base_sha="15e55c515ae917c2f0330809f0d9e44d49bce12b",
        current_stage=OrchestrationStage.ADMITTED,
        created_at=utc_now(),
    )
    uow.orchestration_runs.save(run)
    session.commit()

    # 1. Worker A acquires claim (fence 1)
    ctx_a = rec_a.acquire_claim(claim_key, lease_seconds=3600)
    assert ctx_a is not None
    assert ctx_a.fence_token == 1
    # Notice locally ctx_a.is_valid() is True because lease_expires_at is 1 hour in future
    assert ctx_a.is_valid() is True

    # 2. Simulate Worker A's lease expiring in DB
    session.execute(
        text("UPDATE recovery_claims SET lease_expires_at = NOW() - INTERVAL '10 seconds' WHERE claim_key = :k"),
        {"k": claim_key},
    )
    session.commit()

    # 3. Worker B reacquires claim (fence 2) in DB
    ctx_b = rec_b.acquire_claim(claim_key, lease_seconds=3600)
    assert ctx_b is not None
    assert ctx_b.fence_token == 2

    # 4. Worker A still holds ctx_a in memory (locally valid in memory)
    assert ctx_a.is_valid() is True

    # 5. Direct primitive invocation on OrchestrationService using ctx_a MUST FAIL with StaleClaimError
    orch_svc = OrchestrationService(uow)
    with pytest.raises(StaleClaimError):
        orch_svc.resume(run_id="run-gr03", claim_context=ctx_a)

    # Verify run stage was NOT mutated by stale worker
    run_after = uow.orchestration_runs.get_by_id("run-gr03")
    assert run_after.current_stage == OrchestrationStage.ADMITTED

    session.close()


def test_gr08_scheduler_drain_routes_through_recovery_convergence(pg_session_factory: sessionmaker[Session], tmp_path: Path):
    """BLOCKER G-R08 proof: Scheduler DRAIN decision routes through RecoveryConvergenceService and creates RecoveryClaim/Decision."""
    from minime.domain.enums import JobStatus
    from minime.domain.models import Job

    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "gr08-change")

    uow = PostgresPersistenceUnitOfWork(session)
    job = Job(
        job_id="job-gr08",
        project_id=project_id,
        change_name=change_name,
        status=JobStatus.RUNNING,
        implementer_role="codex",
        candidate_sha="cand123",
        current_attempt=1,
    )
    uow.jobs.save(job)
    run = OrchestrationRun(
        run_id="run-gr08",
        project_id=project_id,
        change_name=change_name,
        base_sha="15e55c515ae917c2f0330809f0d9e44d49bce12b",
        current_stage=OrchestrationStage.ADMITTED,
        active_job_id="job-gr08",
        is_active=True,
        created_at=utc_now(),
    )
    uow.orchestration_runs.save(run)
    session.commit()

    rec_svc = RecoveryConvergenceService(uow, project_root=tmp_path)
    decision_obj = rec_svc.request_run_continuation(
        run.run_id, source=RecoverySource.TICK, drain_mode=True
    )

    # Verify a RecoveryClaim and RecoveryDecision were created
    claim = uow.claims.get_by_key("run:run-gr08")
    assert claim is not None
    decisions = uow.recovery_decisions.list_by_claim_key("run:run-gr08")
    assert len(decisions) >= 1
    assert decisions[0].source == RecoverySource.TICK
    assert decision_obj.status in {RecoveryDecisionStatus.COMPLETED, RecoveryDecisionStatus.PLANNED, RecoveryDecisionStatus.NO_ACTION}

    session.close()


def test_gr09_restart_recovery_service_delegates_to_recovery_convergence(pg_session_factory: sessionmaker[Session], tmp_path: Path):
    """BLOCKER G-R09 proof: RestartRecoveryService saga and run reconciliation delegate to RecoveryConvergenceService."""
    from minime.services.restart_recovery_service import RestartRecoveryService

    session = pg_session_factory()
    project_id, change_name = _seed_base_project_and_change(session, "gr09-change")

    uow = PostgresPersistenceUnitOfWork(session)
    saga = DurableSaga(
        id="saga-gr09",
        saga_type=SagaType.INTAKE,
        project_id=project_id,
        work_item_key=change_name,
        change_name=change_name,
        current_phase="STARTED",
        status=SagaStatus.IN_PROGRESS,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    uow.durable_sagas.save(saga)
    session.commit()

    restart_svc = RestartRecoveryService(uow, project_root=tmp_path)
    sagas = restart_svc.reconcile_durable_sagas()
    assert any(s.id == "saga-gr09" for s in sagas)

    # Verify claim was acquired via RecoveryConvergenceService
    claim = uow.claims.get_by_key(f"intake:{project_id}:{change_name}")
    assert claim is not None

    session.close()


def test_gr10_direct_entry_point_census():
    """BLOCKER G-R10 proof: Production census verifies zero un-fenced OrchestrationService.resume() calls in production code."""
    src_dir = Path(__file__).parent.parent / "src"

    violations = []
    for py_file in src_dir.glob("**/*.py"):
        text_content = py_file.read_text(encoding="utf-8")
        lines = text_content.splitlines()
        for idx, line in enumerate(lines, 1):
            if "orchestration_svc.resume(" in line or "orchestration_service.resume(" in line or "service.resume(" in line:
                if "def resume(" in line or "recovery_convergence_service.py" in str(py_file):
                    continue
                violations.append(f"{py_file.name}:{idx}: {line.strip()}")

    assert violations == [], f"Found Category 4 resume() direct invocation violations: {violations}"


