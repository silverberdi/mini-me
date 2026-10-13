"""Isolated PostgreSQL proof of CONTINUE reusing a deleted N01 worktree identity."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from minime.config import CliInvocationProfile
from minime.db.models import (
    Base,
    DurableSagaModel,
    EventModel,
    JobAttemptModel,
    JobModel,
    OrchestrationRunModel,
)
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    AttemptProductivityClass,
    ContinuationDecision,
    EventType,
    ExecutionOutcome,
    ExternalActionStatus,
    ExternalOutcome,
    HumanGate,
    JobStatus,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProgressClassification,
    ProviderHealthStatus,
    WorktreeCreationState,
)
from minime.domain.models import (
    Event,
    Job,
    JobAttempt,
    OperatorActionRequest,
    OrchestrationRun,
    Project,
    ProviderHealth,
    utc_now,
)
from minime.services import execution_pipeline
from minime.services.agent_confinement import AgentProcessConfinement
from minime.services.control_plane_service import ControlPlaneService
from minime.services.implementer_runner import CliImplementerRunner
from minime.services.worktree_manager import WorktreeManager


@pytest.fixture
def isolated_pg_session_factory():
    configured = os.environ.get("MINIME_TEST_ADMIN_DATABASE_URL")
    raw_url = configured or "postgresql+psycopg://silveriobernal@localhost:54333/postgres"
    admin_url = make_url(raw_url)
    if admin_url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("This regression requires a local isolated PostgreSQL server.")
    admin_engine = create_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    database_name = f"minime_continue_{uuid.uuid4().hex[:12]}"
    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    test_engine = create_engine(admin_url.set(database=database_name), pool_pre_ping=True)
    Base.metadata.create_all(test_engine)
    try:
        yield sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    finally:
        test_engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE "{database_name}"')
        admin_engine.dispose()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True).stdout


@pytest.mark.parametrize(
    "contradiction",
    [
        "progress",
        "same_sha_suppression",
        "candidate",
        "attempt_gap",
        "duplicate_attempt",
        "stale_claim",
        "expired_claim",
        "wrong_decision_source",
        "completed_decision",
        "decision_predates_attempt",
        "deleted_ownership",
        "missing_decision",
        "invalid_productivity",
        "job_candidate",
        "attempt_sha_drift",
        "identity_mismatch",
        "same_sha_progress",
        "same_sha_without_event",
    ],
)
def test_auth_required_created_recovery_predicate_fails_closed(contradiction, tmp_path: Path):
    """The narrow AUTH_REQUIRED exception rejects contradictory durable evidence."""
    now = utc_now()
    started = now - timedelta(minutes=10)
    attempts = [
        SimpleNamespace(
            attempt_id=f"attempt-{number}",
            attempt_number=number,
            normalized_outcome=(
                ExecutionOutcome.PROVIDER_FAILURE if number == 1 else ExecutionOutcome.AUTH_REQUIRED
            ),
            productivity_class=(
                AttemptProductivityClass.PROVIDER_FAILURE
                if number == 1
                else AttemptProductivityClass.PROVIDER_PREFLIGHT_FAILURE
            ),
            progress_classification=ProgressClassification.NO_PROGRESS,
            continuation_decision=(
                ContinuationDecision.NEEDS_HUMAN
                if number == 1
                else ContinuationDecision.CORRECT_AND_RETRY
                if number == 2
                else ContinuationDecision.NEEDS_HUMAN
            ),
            is_same_sha_duplicate=False,
            start_sha="base-sha",
            end_sha="base-sha",
            started_at=started + timedelta(minutes=2 * (number - 1)),
            completed_at=started + timedelta(minutes=2 * (number - 1), seconds=1),
            duration_ms=1000,
        )
        for number in (1, 2, 3)
    ]
    job = SimpleNamespace(
        job_id="job-test",
        project_id="project-test",
        change_name="change-test",
        candidate_sha=None,
        attempt_count=3,
        base_sha="base-sha",
    )
    run = SimpleNamespace(
        run_id="run-test",
        project_id="project-test",
        change_name="change-test",
        active_job_id="job-test",
        current_stage=OrchestrationStage.IMPLEMENTING,
        current_generation=1,
        current_candidate_sha=None,
        base_sha="base-sha",
    )
    decision = SimpleNamespace(
        decision_id="decision-test",
        cycle_id="cycle-test",
        claim_key="run:run-test",
        identity_type="RUN",
        identity_id="run-test",
        project_id="project-test",
        change_name="change-test",
        source="CONTROL_PLANE",
        planned_action="DRIVE_CONTINUATION",
        status="EXECUTING",
        fence_token=7,
        created_at=now - timedelta(minutes=1),
    )
    claim = SimpleNamespace(owner_instance_id="owner-test", fence_token=7, is_active=True)
    cas_valid = True
    decision_present = True

    if contradiction == "progress":
        attempts[-1].progress_classification = ProgressClassification.GOOD_PROGRESS
    elif contradiction == "same_sha_suppression":
        attempts[-1].is_same_sha_duplicate = True
    elif contradiction == "candidate":
        run.current_candidate_sha = "candidate-sha"
    elif contradiction == "attempt_gap":
        attempts[-1].attempt_number = 4
    elif contradiction == "duplicate_attempt":
        attempts.append(SimpleNamespace(**vars(attempts[-1])))
    elif contradiction == "stale_claim":
        cas_valid = False
    elif contradiction == "expired_claim":
        claim.is_active = False
    elif contradiction == "wrong_decision_source":
        decision.source = "API"
    elif contradiction == "completed_decision":
        decision.status = "COMPLETED"
    elif contradiction == "decision_predates_attempt":
        decision.created_at = attempts[-1].completed_at - timedelta(minutes=1)
    elif contradiction == "missing_decision":
        decision_present = False
    elif contradiction == "invalid_productivity":
        attempts[-1].productivity_class = AttemptProductivityClass.OTHER
    elif contradiction == "job_candidate":
        job.candidate_sha = "candidate-sha"
    elif contradiction == "attempt_sha_drift":
        attempts[-1].end_sha = "different-sha"
    elif contradiction == "identity_mismatch":
        job.project_id = "another-project"
    elif contradiction in {"same_sha_progress", "same_sha_without_event"}:
        attempts[-2].normalized_outcome = ExecutionOutcome.AUTH_REQUIRED
        attempts[-1].is_same_sha_duplicate = True
        attempts[-1].productivity_class = AttemptProductivityClass.SAME_SHA_NO_PROGRESS
        attempts[-1].continuation_decision = ContinuationDecision.NEEDS_HUMAN
        attempts[-1].progress_classification = (
            ProgressClassification.GOOD_PROGRESS
            if contradiction == "same_sha_progress"
            else ProgressClassification.NO_PROGRESS
        )
    creation_state = WorktreeCreationState.CREATED
    if contradiction == "deleted_ownership":
        creation_state = WorktreeCreationState.DELETED

    class Decisions:
        def list_by_claim_key(self, _claim_key):
            return [decision] if decision_present else []

        def list_by_cycle(self, _cycle_id):
            return [decision]

    class Claims:
        def get_by_key(self, _claim_key):
            return claim

        def validate_cas(self, **_kwargs):
            return cas_valid

    manager = WorktreeManager(
        tmp_path, SimpleNamespace(recovery_decisions=Decisions(), claims=Claims())
    )
    assert not manager._has_durable_auth_required_created_recovery(
        attempts=attempts,
        latest_attempt=attempts[-1],
        job=job,
        run=run,
        creation_state=creation_state,
        source_base="base-sha",
        project_id="project-test",
        change_name="change-test",
    )


def test_postgres_continue_reuses_created_worktree_after_auth_required_history(
    isolated_pg_session_factory, tmp_path: Path, monkeypatch
):
    """A fenced real CONTINUE may reuse only the exact intact CREATED auth-failure workspace."""
    from conftest import publish_verified_intake_workspace, setup_managed_repository_fixture

    project_id = f"n01-auth-{uuid.uuid4().hex[:8]}"
    change_name = "operational-blocker-visibility"
    run_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    recovery_branch = f"minime/{change_name}-{job_id}"
    managed_root = tmp_path / "managed"
    worktree_parent = tmp_path / "worktrees"
    remote = tmp_path / "managed.origin.git"

    with isolated_pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        project = Project(
            project_id=project_id,
            display_name="N01 AUTH_REQUIRED recovery regression",
            repository=str(remote),
            base_branch="main",
            openspec_path="openspec",
            implementer="codex",
        )
        uow.projects.save(project)
        setup_managed_repository_fixture(
            uow,
            project_id=project_id,
            repo_root=managed_root,
            worktree_parent_dir=worktree_parent,
            canonical_repository_identity=str(remote),
            remote_url=str(remote),
        )
        _git(managed_root, "push", "origin", "main")
        base_sha = _git(managed_root, "rev-parse", "main")
        publish = publish_verified_intake_workspace(uow, project, managed_root, change_name)
        assert publish.published_sha

        job = Job(
            job_id=job_id,
            project_id=project_id,
            change_name=change_name,
            implementer_role="codex",
            current_executor="codex",
            reassignment_count=1,
            status=JobStatus.FAILED,
            base_sha=base_sha,
            attempt_count=3,
        )
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name=change_name,
            base_sha=base_sha,
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            active_job_id=job_id,
            current_candidate_sha=None,
            is_active=False,
            stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
            human_gate=HumanGate.NEEDS_HUMAN,
        )
        uow.jobs.save(job)
        uow.orchestration_runs.save(run)
        uow.provider_health.save(
            ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
        )
        uow.commit()

        manager = WorktreeManager(managed_root, uow)
        worktree = asyncio.run(
            manager.create_worktree(
                job_id,
                change_name,
                base_branch="main",
                project_id=project_id,
                branch_name=recovery_branch,
                run_id=run_id,
            )
        )
        snapshot_sha = asyncio.run(manager.create_recovery_snapshot(job_id, project_id))
        assert snapshot_sha and snapshot_sha != base_sha
        attempt_one_started = utc_now() - timedelta(hours=16)
        attempt_one_completed = attempt_one_started + timedelta(milliseconds=967)
        attempt_two_started = attempt_one_completed + timedelta(hours=14, minutes=13)
        attempt_two_completed = attempt_two_started + timedelta(milliseconds=2591)
        attempt_three_started = attempt_two_completed + timedelta(milliseconds=66)
        attempt_three_completed = attempt_three_started + timedelta(milliseconds=747)
        historical_attempts = [
            JobAttempt(
                attempt_id=f"att-{job_id}-1",
                job_id=job_id,
                attempt_number=1,
                executor_role="codex",
                model_identity="codex",
                start_sha=base_sha,
                end_sha=base_sha,
                normalized_outcome=ExecutionOutcome.PROVIDER_FAILURE,
                progress_classification=ProgressClassification.NO_PROGRESS,
                continuation_decision=ContinuationDecision.NEEDS_HUMAN,
                productivity_class=AttemptProductivityClass.PROVIDER_FAILURE,
                is_same_sha_duplicate=False,
                started_at=attempt_one_started,
                completed_at=attempt_one_completed,
                duration_ms=960,
            ),
            JobAttempt(
                attempt_id=f"att-{job_id}-2",
                job_id=job_id,
                attempt_number=2,
                executor_role="codex",
                model_identity="codex",
                start_sha=snapshot_sha,
                end_sha=snapshot_sha,
                normalized_outcome=ExecutionOutcome.AUTH_REQUIRED,
                progress_classification=ProgressClassification.NO_PROGRESS,
                continuation_decision=ContinuationDecision.CORRECT_AND_RETRY,
                productivity_class=AttemptProductivityClass.PROVIDER_PREFLIGHT_FAILURE,
                is_same_sha_duplicate=False,
                started_at=attempt_two_started,
                completed_at=attempt_two_completed,
                duration_ms=2591,
            ),
            JobAttempt(
                attempt_id=f"att-{job_id}-3",
                job_id=job_id,
                attempt_number=3,
                executor_role="antigravity",
                model_identity="antigravity",
                start_sha=snapshot_sha,
                end_sha=snapshot_sha,
                normalized_outcome=ExecutionOutcome.AUTH_REQUIRED,
                progress_classification=ProgressClassification.NO_PROGRESS,
                continuation_decision=ContinuationDecision.NEEDS_HUMAN,
                productivity_class=AttemptProductivityClass.SAME_SHA_NO_PROGRESS,
                is_same_sha_duplicate=True,
                started_at=attempt_three_started,
                completed_at=attempt_three_completed,
                duration_ms=741,
            ),
        ]
        for attempt in historical_attempts:
            uow.job_attempts.save(attempt)
        uow.events.save(
            Event(
                event_type=EventType.SAME_SHA_RETRY_SUPPRESSED,
                project_id=project_id,
                change_id=change_name,
                operation_id=job_id,
                payload={
                    "attempt": 3,
                    "candidate_sha": snapshot_sha,
                    "reason": (
                        "SAME_SHA_RETRY_SUPPRESSED: Candidate SHA is unchanged from previous attempt "
                        "with identical failure reason and no new material evidence. Duplicate full-provider retry suppressed."
                    ),
                },
                timestamp=attempt_three_completed + timedelta(milliseconds=7),
            )
        )
        ownership_before = uow.orchestration_worktree_ownerships.get_by_job_id(job_id)
        assert ownership_before.creation_state == WorktreeCreationState.CREATED
        uow.events.save(
            Event(
                event_type=EventType.WORKTREE_RECOVERY_SNAPSHOT,
                project_id=project_id,
                change_id=change_name,
                operation_id=job_id,
                payload={
                    "job_id": job_id,
                    "branch": recovery_branch,
                    "recovery_sha": snapshot_sha,
                    "worktree_path": str(worktree.path.resolve()),
                    "authoritative_candidate": False,
                },
            )
        )
        uow.commit()
        assert _git(worktree.path, "status", "--porcelain=v1", "--untracked-files=all") == ""
        assert not any(
            event.event_type
            in {
                EventType.JOB_INTERRUPTED,
                EventType.JOB_RECOVERED,
                EventType.ORCHESTRATION_RECOVERED,
            }
            for event in uow.events.list_events(
                project_id=project_id, change_id=change_name, limit=10000
            )
        )
        original_attempts = uow.job_attempts.list_by_job(job_id)
        assert [
            (
                attempt.executor_role,
                attempt.normalized_outcome,
                attempt.productivity_class,
                attempt.progress_classification,
                attempt.is_same_sha_duplicate,
                attempt.start_sha,
                attempt.end_sha,
                attempt.duration_ms,
                attempt.continuation_decision,
            )
            for attempt in original_attempts
        ] == [
            (
                "codex",
                ExecutionOutcome.PROVIDER_FAILURE,
                AttemptProductivityClass.PROVIDER_FAILURE,
                ProgressClassification.NO_PROGRESS,
                False,
                base_sha,
                base_sha,
                960,
                ContinuationDecision.NEEDS_HUMAN,
            ),
            (
                "codex",
                ExecutionOutcome.AUTH_REQUIRED,
                AttemptProductivityClass.PROVIDER_PREFLIGHT_FAILURE,
                ProgressClassification.NO_PROGRESS,
                False,
                snapshot_sha,
                snapshot_sha,
                2591,
                ContinuationDecision.CORRECT_AND_RETRY,
            ),
            (
                "antigravity",
                ExecutionOutcome.AUTH_REQUIRED,
                AttemptProductivityClass.SAME_SHA_NO_PROGRESS,
                ProgressClassification.NO_PROGRESS,
                True,
                snapshot_sha,
                snapshot_sha,
                741,
                ContinuationDecision.NEEDS_HUMAN,
            ),
        ]
        saga_count_before = session.scalar(
            select(func.count())
            .select_from(DurableSagaModel)
            .where(DurableSagaModel.project_id == project_id)
        )

        runtime_root = tmp_path / "runtime"
        runtime_root.mkdir()
        monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime_root))
        diagnostic_cli = tmp_path / "diagnostic-cli"
        diagnostic_cli.write_text(
            "#!/usr/bin/env python3\nimport sys\n"
            "if '--help' in sys.argv:\n    print('diagnostic cli help')\n"
            "else:\n    print('diagnostic runner reached; no inference')\n",
            encoding="utf-8",
        )
        diagnostic_cli.chmod(0o700)
        profile = CliInvocationProfile(
            provider="diagnostic-cli",
            role="implementer",
            executable=str(diagnostic_cli),
            args=(),
            prompt_transport="stdin",
        )

        class RecordingRunner:
            def __init__(self):
                self.delegate = CliImplementerRunner(profile)
                self.reached = False
                self.head_sha = None
                self.branch = None
                self.ownership_id = None
                self.ownership_state = None

            async def run(self, candidate_path, prompt_context, timeout_seconds):
                self.reached = True
                self.head_sha = _git(Path(candidate_path), "rev-parse", "HEAD")
                self.branch = _git(Path(candidate_path), "branch", "--show-current")
                ownership = uow.orchestration_worktree_ownerships.get_by_job_id(job_id)
                self.ownership_id = ownership.worktree_id
                self.ownership_state = ownership.creation_state
                return await self.delegate.run(candidate_path, prompt_context, timeout_seconds)

        runner = RecordingRunner()
        monkeypatch.setattr(execution_pipeline, "runner_for_implementer", lambda _provider: runner)
        result = ControlPlaneService(uow, project_root=managed_root).execute_action(
            OperatorActionRequest(
                action_request_id=str(uuid.uuid4()),
                project_id=project_id,
                change_name=change_name,
                run_id=run_id,
                action_type=OperatorActionType.CONTINUE,
                actor_identity="test-operator-auth-required-recovery",
                source_interface="cli",
                expected_stage=OrchestrationStage.IMPLEMENTING,
                expected_generation=1,
                expected_candidate_sha=None,
            )
        )

        assert result.status == OperatorActionStatus.COMPLETED, result.summary
        assert runner.reached is True
        assert runner.head_sha == snapshot_sha
        assert runner.branch == recovery_branch
        assert runner.ownership_state == WorktreeCreationState.CREATED
        assert runner.ownership_id == ownership_before.worktree_id
        assert uow.jobs.get_by_id(job_id).current_executor == "codex"
        attempts_after = uow.job_attempts.list_by_job(job_id)
        assert uow.jobs.get_by_id(job_id).attempt_count == len(attempts_after)
        assert len(attempts_after) > 3
        assert [attempt.attempt_id for attempt in attempts_after[:3]] == [
            attempt.attempt_id for attempt in original_attempts
        ]
        assert [attempt.normalized_outcome for attempt in attempts_after[:3]] == [
            ExecutionOutcome.PROVIDER_FAILURE,
            ExecutionOutcome.AUTH_REQUIRED,
            ExecutionOutcome.AUTH_REQUIRED,
        ]
        assert [attempt.attempt_number for attempt in attempts_after] == list(
            range(1, len(attempts_after) + 1)
        )
        assert uow.orchestration_runs.get_by_id(run_id).run_id == run_id
        assert (
            uow.orchestration_worktree_ownerships.get_by_job_id(job_id).worktree_id
            == ownership_before.worktree_id
        )
        assert (
            uow.orchestration_worktree_ownerships.get_by_job_id(job_id).source_base_sha == base_sha
        )
        assert _git(managed_root, "rev-parse", f"refs/heads/{recovery_branch}") == snapshot_sha
        assert (
            session.scalar(
                select(func.count())
                .select_from(OrchestrationRunModel)
                .where(OrchestrationRunModel.project_id == project_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(JobModel).where(JobModel.project_id == project_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(DurableSagaModel)
                .where(DurableSagaModel.project_id == project_id)
            )
            == saga_count_before
        )


def test_postgres_control_plane_continue_rebuilds_same_run_job_and_worktree(
    isolated_pg_session_factory, tmp_path: Path, monkeypatch
):
    """Exercise durable CP/claim/recovery and real Git worktree authorities; no provider is invoked."""
    from conftest import publish_verified_intake_workspace, setup_managed_repository_fixture

    project_id = f"n01-cont-{uuid.uuid4().hex[:8]}"
    change_name = "operational-blocker-visibility"
    run_id = "627adcf0-ee2a-4e3b-8211-1972c7dbec00"
    job_id = "7c6c20dd-cf8f-486d-ad3e-e0e5de1b19e0"
    recovery_branch = f"minime/{change_name}-{job_id}"
    managed_root = tmp_path / "managed"
    worktree_parent = tmp_path / "worktrees"
    local_bare_remote = tmp_path / "managed.origin.git"

    with isolated_pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        project = Project(
            project_id=project_id,
            display_name="N01 continuation regression",
            repository=str(local_bare_remote),
            base_branch="main",
            openspec_path="openspec",
            implementer="codex",
        )
        uow.projects.save(project)
        binding = setup_managed_repository_fixture(
            uow,
            project_id=project_id,
            repo_root=managed_root,
            worktree_parent_dir=worktree_parent,
            canonical_repository_identity=str(local_bare_remote),
            remote_url=str(local_bare_remote),
        )
        assert project.repository == binding.canonical_repository_identity
        _git(managed_root, "push", "origin", "main")
        base_sha = _git(managed_root, "rev-parse", "main")

        published = publish_verified_intake_workspace(uow, project, managed_root, change_name)
        assert published.published_sha
        worktree_path = worktree_parent / job_id

        job = Job(
            job_id=job_id,
            project_id=project_id,
            change_name=change_name,
            implementer_role="codex",
            current_executor="codex",
            status=JobStatus.NEEDS_HUMAN,
            base_sha=base_sha,
            attempt_count=1,
        )
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name=change_name,
            base_sha=base_sha,
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            active_job_id=job_id,
            current_candidate_sha=None,
            is_active=False,
            stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
            human_gate=HumanGate.NEEDS_HUMAN,
            stop_reason="Runner runtime unavailable before implementation began.",
        )
        uow.jobs.save(job)
        uow.orchestration_runs.save(run)
        # Persist real health evidence so the continuation reaches worktree
        # reconstruction; no health service is mocked or marked successful later.
        uow.provider_health.save(
            ProviderHealth(
                provider="codex",
                status=ProviderHealthStatus.AVAILABLE,
                consecutive_failures=0,
            )
        )
        uow.job_attempts.save(
            JobAttempt(
                job_id=job_id,
                attempt_number=1,
                executor_role="codex",
                model_identity="codex",
                normalized_outcome=ExecutionOutcome.ENVIRONMENT_UNAVAILABLE,
            )
        )
        uow.commit()

        # Create, snapshot, and delete through WorktreeManager's durable
        # ownership lifecycle rather than manufacturing a DELETED row/event.
        manager = WorktreeManager(managed_root, uow)
        original_worktree = asyncio.run(
            manager.create_worktree(
                job_id,
                change_name,
                base_branch="main",
                project_id=project_id,
                branch_name=recovery_branch,
                run_id=run_id,
            )
        )
        assert original_worktree.base_sha == base_sha
        assert _git(original_worktree.path, "rev-parse", "HEAD") == base_sha
        recovered_sha = asyncio.run(manager.create_recovery_snapshot(job_id, project_id))
        assert recovered_sha and recovered_sha != base_sha
        uow.events.save(
            Event(
                event_type=EventType.WORKTREE_RECOVERY_SNAPSHOT,
                project_id=project_id,
                change_id=change_name,
                operation_id=job_id,
                payload={
                    "job_id": job_id,
                    "branch": recovery_branch,
                    "recovery_sha": recovered_sha,
                    "worktree_path": str(worktree_path.resolve()),
                    "authoritative_candidate": False,
                },
            )
        )
        uow.commit()
        cleanup_result = asyncio.run(manager.remove_clean_worktree(job_id, project_id))
        assert cleanup_result.outcome == ExternalOutcome.SUCCESS
        assert not worktree_path.exists()
        initial_ownership = uow.orchestration_worktree_ownerships.get_by_job_id(job_id)
        assert initial_ownership.creation_state == WorktreeCreationState.DELETED
        assert initial_ownership.source_base_sha == base_sha
        ownership_id_before_continue = initial_ownership.worktree_id
        saga_count_before_continue = session.scalar(
            select(func.count())
            .select_from(DurableSagaModel)
            .where(DurableSagaModel.project_id == project_id)
        )

        # A legitimate remote main advance B -> C leaves the managed local
        # base at B; authenticated object fetch resolves C without moving that
        # base. Recovery branch and durable Run/Job lineage remain rooted at B.
        advancing_clone = tmp_path / "advancing-clone"
        subprocess.run(
            ["git", "clone", str(local_bare_remote), str(advancing_clone)],
            check=True,
            capture_output=True,
            text=True,
        )
        _git(advancing_clone, "config", "user.name", "Remote Main Advance")
        _git(advancing_clone, "config", "user.email", "advance@localhost")
        (advancing_clone / "unrelated-main-advance.txt").write_text("unrelated\n")
        _git(advancing_clone, "add", "unrelated-main-advance.txt")
        _git(advancing_clone, "commit", "-m", "unrelated main advance")
        _git(advancing_clone, "push", "origin", "main")
        advanced_main_sha = _git(advancing_clone, "rev-parse", "main")
        managed_base_sha = _git(managed_root, "rev-parse", "main")
        assert advanced_main_sha != base_sha
        assert managed_base_sha == base_sha
        _git(advancing_clone, "merge-base", "--is-ancestor", base_sha, advanced_main_sha)
        manager = WorktreeManager(managed_root, uow)

        def assert_recreation_refused(reason: str, **identity_overrides) -> None:
            with pytest.raises(RuntimeError, match=reason):
                asyncio.run(
                    manager._verify_deleted_worktree_recreation(
                        job_id=job_id,
                        project_id=identity_overrides.get("project_id", project_id),
                        run_id=run_id,
                        change_name=identity_overrides.get("change_name", change_name),
                        path=worktree_path.resolve(),
                        branch=identity_overrides.get("branch", recovery_branch),
                        base_branch="main",
                        current_base_sha=managed_base_sha,
                    )
                )

        # The exact B-based snapshot is admissible under descendant C.
        assert (
            asyncio.run(
                manager._verify_deleted_worktree_recreation(
                    job_id=job_id,
                    project_id=project_id,
                    run_id=run_id,
                    change_name=change_name,
                    path=worktree_path.resolve(),
                    branch=recovery_branch,
                    base_branch="main",
                    current_base_sha=managed_base_sha,
                )
            )
            == recovered_sha
        )

        # Contradictory request identity, candidate evidence, terminal run
        # outcome, and ownership base all fail closed before worktree mutation.
        assert_recreation_refused(
            "project, job, run, change, or persisted branch", project_id="other"
        )
        assert_recreation_refused(
            "project, job, run, change, or persisted branch", change_name="other-change"
        )
        uow.projects.save(
            Project(
                project_id="foreign-project",
                display_name="Foreign project fixture",
                repository="foreign/repository",
                base_branch="main",
            )
        )
        uow.commit()
        job_identity = session.get(JobModel, job_id)
        job_identity.project_id = "foreign-project"
        session.commit()
        assert_recreation_refused("linked job identity or resumable status")
        job_identity.project_id = project_id
        run_identity = session.get(OrchestrationRunModel, run_id)
        run_identity.project_id = "foreign-project"
        session.commit()
        assert_recreation_refused("linked orchestration run identity or stage")
        run_identity.project_id = project_id
        session.commit()
        job_for_candidate = uow.jobs.get_by_id(job_id)
        run_for_candidate = uow.orchestration_runs.get_by_id(run_id)
        job_for_candidate.candidate_sha = "candidate-that-must-block"
        run_for_candidate.current_candidate_sha = "candidate-that-must-block"
        uow.jobs.save(job_for_candidate)
        uow.orchestration_runs.save(run_for_candidate)
        uow.commit()
        assert_recreation_refused("candidate evidence exists")
        job_for_candidate.candidate_sha = None
        run_for_candidate.current_candidate_sha = None
        uow.jobs.save(job_for_candidate)
        uow.orchestration_runs.save(run_for_candidate)
        run_for_candidate.stop_outcome = OrchestrationStopOutcome.CANCELLED
        uow.orchestration_runs.save(run_for_candidate)
        uow.commit()
        assert_recreation_refused("run is terminal")
        run_for_candidate.stop_outcome = OrchestrationStopOutcome.NEEDS_HUMAN
        uow.orchestration_runs.save(run_for_candidate)
        job_for_candidate.status = JobStatus.COMPLETED
        uow.jobs.save(job_for_candidate)
        uow.commit()
        assert_recreation_refused("linked job identity or resumable status")
        job_for_candidate.status = JobStatus.NEEDS_HUMAN
        uow.jobs.save(job_for_candidate)
        uow.commit()

        ownership_for_base = uow.orchestration_worktree_ownerships.get_by_job_id(job_id)
        ownership_for_base.source_base_sha = "0" * len(base_sha)
        uow.orchestration_worktree_ownerships.save(ownership_for_base)
        uow.commit()
        assert_recreation_refused("not provably a descendant")
        ownership_for_base.source_base_sha = base_sha
        uow.orchestration_worktree_ownerships.save(ownership_for_base)
        uow.commit()

        # The event must bind the exact branch SHA. A missing/mismatched durable
        # snapshot event cannot be replaced by Git branch contents alone.
        snapshot_event = next(
            event
            for event in uow.events.list_events(
                project_id=project_id, change_id=change_name, limit=1000
            )
            if event.event_type == EventType.WORKTREE_RECOVERY_SNAPSHOT
        )
        original_snapshot_payload = dict(snapshot_event.payload)
        persisted_snapshot_event = session.get(EventModel, snapshot_event.event_id)
        persisted_snapshot_event.payload = {
            **original_snapshot_payload,
            "recovery_sha": "contradictory",
        }
        uow.commit()
        assert_recreation_refused("no unique durable recovery-snapshot event")
        persisted_snapshot_event.payload = original_snapshot_payload
        uow.commit()

        # An adulterated recovery branch (extra commit) cannot be adopted even
        # though its tree is still under the change directory.
        _git(managed_root, "checkout", recovery_branch)
        unexpected_artifact = managed_root / "openspec" / "changes" / change_name / "unexpected.md"
        unexpected_artifact.write_text("not in the durable snapshot\n", encoding="utf-8")
        _git(managed_root, "add", str(unexpected_artifact.relative_to(managed_root)))
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Unauthorized Writer",
                "-c",
                "user.email=unauthorized@localhost",
                "commit",
                "-m",
                "unauthorized recovery branch change",
            ],
            cwd=managed_root,
            check=True,
            capture_output=True,
        )
        _git(managed_root, "checkout", "main")
        assert_recreation_refused("branch tip is not one exact artifact-only recovery snapshot")
        _git(managed_root, "branch", "-f", recovery_branch, recovered_sha)

        # A caller cannot adopt an arbitrary occupied canonical worktree path.
        worktree_path.mkdir()
        (worktree_path / "foreign-content").write_text("foreign\n", encoding="utf-8")
        with pytest.raises(ValueError, match="already exists and is not empty"):
            asyncio.run(
                manager.create_worktree(
                    job_id,
                    change_name,
                    base_branch="main",
                    project_id=project_id,
                    branch_name=recovery_branch,
                    run_id=run_id,
                )
            )
        (worktree_path / "foreign-content").unlink()
        worktree_path.rmdir()

        # Exercise real ControlPlane -> RecoveryConvergence -> Orchestration -> pipeline
        # -> WorktreeManager -> confined CLI runner. The command is a deterministic local
        # Python diagnostic, not a model/provider; its EROFS marker stops continuation.
        runtime_root = tmp_path / "runtime"
        runtime_root.mkdir()
        monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime_root))
        diagnostic_cli = tmp_path / "diagnostic-cli"
        diagnostic_cli.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "if '--help' in sys.argv:\n"
            "    print('diagnostic cli help')\n"
            "else:\n"
            f"    assert __import__('pathlib').Path('openspec/changes/{change_name}/proposal.md').is_file()\n"
            "    print('EROFS: test-only local environment stop', file=sys.stderr)\n",
            encoding="utf-8",
        )
        diagnostic_cli.chmod(0o700)
        test_profile = CliInvocationProfile(
            provider="diagnostic-cli",
            role="implementer",
            executable=str(diagnostic_cli),
            args=(),
            prompt_transport="stdin",
        )

        class RecordingRunner:
            def __init__(self):
                self.delegate = CliImplementerRunner(test_profile)
                self.result = None
                self.worktree_head_sha = None
                self.worktree_branch = None
                self.marker_source_base_sha = None
                self.ownership_source_base_sha = None

            async def run(self, worktree_path, prompt_context, timeout_seconds):
                self.worktree_head_sha = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=worktree_path,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                self.worktree_branch = subprocess.run(
                    ["git", "branch", "--show-current"],
                    cwd=worktree_path,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                self.marker_source_base_sha = json.loads(
                    (Path(worktree_path) / ".minime_worktree_ownership.json").read_text(
                        encoding="utf-8"
                    )
                )["source_base_sha"]
                self.ownership_source_base_sha = (
                    uow.orchestration_worktree_ownerships.get_by_job_id(job_id).source_base_sha
                )
                self.result = await self.delegate.run(
                    worktree_path, prompt_context, timeout_seconds
                )
                return self.result

        recording_runner = RecordingRunner()
        monkeypatch.setattr(
            execution_pipeline,
            "runner_for_implementer",
            lambda _provider: recording_runner,
        )
        request = OperatorActionRequest(
            action_request_id=str(uuid.uuid4()),
            project_id=project_id,
            change_name=change_name,
            run_id=run_id,
            action_type=OperatorActionType.CONTINUE,
            actor_identity="test-operator-n01-continuation",
            source_interface="cli",
            expected_stage=OrchestrationStage.IMPLEMENTING,
            expected_generation=1,
            expected_candidate_sha=None,
        )
        result = ControlPlaneService(uow, project_root=managed_root).execute_action(request)
        assert result.status == OperatorActionStatus.COMPLETED, result.summary
        assert "run_active=true" in result.summary
        assert "linked_job_status=WAITING_CAPACITY" in result.summary
        assert "execution_active=false" in result.summary
        assert "resumed successfully" not in result.summary.lower()
        assert result.payload["run_active"] is True
        assert result.payload["execution_active"] is False
        assert result.payload["linked_job_status"] == JobStatus.WAITING_CAPACITY.value

        persisted_run = uow.orchestration_runs.get_by_id(run_id)
        persisted_job = uow.jobs.get_by_id(job_id)
        assert persisted_run.run_id == run_id and persisted_run.active_job_id == job_id
        assert persisted_run.is_active is True
        assert persisted_run.base_sha == base_sha
        assert persisted_job.base_sha == base_sha
        assert persisted_run.stop_outcome == OrchestrationStopOutcome.WAITING_CAPACITY
        assert persisted_job.job_id == job_id and persisted_job.attempt_count == 1
        assert persisted_job.reassignment_count == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(OrchestrationRunModel)
                .where(OrchestrationRunModel.project_id == project_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(JobModel).where(JobModel.project_id == project_id)
            )
            == 1
        )
        assert _git(managed_root, "rev-parse", "main") == base_sha
        assert recording_runner.result is not None
        assert recording_runner.worktree_head_sha == recovered_sha
        assert recording_runner.worktree_branch == recovery_branch
        assert recording_runner.marker_source_base_sha == base_sha
        assert recording_runner.ownership_source_base_sha == base_sha
        if AgentProcessConfinement.is_host_confinement_available():
            assert recording_runner.result.exit_code == 0
            assert recording_runner.result.stderr == ["EROFS: test-only local environment stop"]
        else:
            assert recording_runner.result.environment_error is True
        assert persisted_job.status == JobStatus.WAITING_CAPACITY
        attempts = uow.job_attempts.list_by_job(job_id)
        assert attempts[0].attempt_number == 1
        assert attempts[0].normalized_outcome == ExecutionOutcome.ENVIRONMENT_UNAVAILABLE
        assert len(attempts) == 2
        assert attempts[-1].normalized_outcome == ExecutionOutcome.ENVIRONMENT_UNAVAILABLE
        assert attempts[-1].continuation_decision == ContinuationDecision.WAIT_EXTERNAL
        assert attempts[-1].corrective_retries_count == 0
        assert uow.provider_health.get_by_provider("codex").status == ProviderHealthStatus.AVAILABLE
        assert len(uow.operator_actions.list_by_run(run_id)) == 1
        assert (
            uow.operator_actions.list_by_run(run_id)[0].action_type == OperatorActionType.CONTINUE
        )

        persisted_ownership = uow.orchestration_worktree_ownerships.get_by_job_id(job_id)
        assert persisted_ownership.creation_state == WorktreeCreationState.DELETED
        assert persisted_ownership.source_base_sha == base_sha
        assert persisted_ownership.worktree_id == ownership_id_before_continue
        assert (
            session.scalar(
                select(func.count())
                .select_from(DurableSagaModel)
                .where(DurableSagaModel.project_id == project_id)
            )
            == saga_count_before_continue
        )
        assert not _git(
            managed_root,
            "for-each-ref",
            "--format=%(refname)",
            "refs/minime/observed-base",
        )
        assert _git(managed_root, "rev-parse", f"refs/heads/{recovery_branch}") == recovered_sha
        assert not worktree_path.exists()

        # A further remote-only descendant advance can also be resolved by the
        # authenticated fetch, while a divergent local managed base is refused.
        _git(advancing_clone, "commit", "--allow-empty", "-m", "remote-only advance")
        _git(advancing_clone, "push", "origin", "main")

        manager = WorktreeManager(managed_root, uow)
        second_remote_advance = _git(advancing_clone, "rev-parse", "main")
        assert second_remote_advance != advanced_main_sha
        _git(advancing_clone, "merge-base", "--is-ancestor", base_sha, second_remote_advance)
        assert (
            asyncio.run(
                manager._verify_deleted_worktree_recreation(
                    job_id=job_id,
                    project_id=project_id,
                    run_id=run_id,
                    change_name=change_name,
                    path=worktree_path.resolve(),
                    branch=recovery_branch,
                    base_branch="main",
                    current_base_sha=managed_base_sha,
                )
            )
            == recovered_sha
        )

        _git(managed_root, "checkout", "--orphan", "local-diverged-main")
        subprocess.run(
            ["git", "rm", "-rf", "."],
            cwd=managed_root,
            check=True,
            capture_output=True,
            text=True,
        )
        (managed_root / "local-divergence.txt").write_text("diverged\n", encoding="utf-8")
        _git(managed_root, "add", "local-divergence.txt")
        _git(managed_root, "-c", "user.name=Local Divergence", "commit", "-m", "local divergence")
        local_diverged_sha = _git(managed_root, "rev-parse", "HEAD")
        _git(managed_root, "checkout", "--detach", local_diverged_sha)
        _git(managed_root, "branch", "-f", "main", local_diverged_sha)
        _git(managed_root, "checkout", "main")
        with pytest.raises(RuntimeError, match="local managed base branch diverges"):
            asyncio.run(
                manager._verify_deleted_worktree_recreation(
                    job_id=job_id,
                    project_id=project_id,
                    run_id=run_id,
                    change_name=change_name,
                    path=worktree_path.resolve(),
                    branch=recovery_branch,
                    base_branch="main",
                    current_base_sha=local_diverged_sha,
                )
            )

        # A rewritten remote main that no longer descends from B is refused.
        _git(advancing_clone, "checkout", "--orphan", "rewritten-main")
        subprocess.run(
            ["git", "rm", "-rf", "."],
            cwd=advancing_clone,
            check=True,
            capture_output=True,
            text=True,
        )
        (advancing_clone / "rewritten-history.txt").write_text("new root\n")
        _git(advancing_clone, "add", "rewritten-history.txt")
        _git(advancing_clone, "commit", "-m", "rewritten main history")
        _git(advancing_clone, "push", "--force", "origin", "HEAD:refs/heads/main")
        _git(managed_root, "checkout", "--detach", base_sha)
        _git(managed_root, "branch", "-f", "main", base_sha)
        _git(managed_root, "checkout", "main")

        with pytest.raises(RuntimeError, match="not provably a descendant"):
            asyncio.run(
                manager._verify_deleted_worktree_recreation(
                    job_id=job_id,
                    project_id=project_id,
                    run_id=run_id,
                    change_name=change_name,
                    path=worktree_path.resolve(),
                    branch=recovery_branch,
                    base_branch="main",
                    current_base_sha=base_sha,
                )
            )


def test_postgres_continue_adopts_created_recovery_worktree_and_repairs_only_final_lf(
    isolated_pg_session_factory, tmp_path: Path, monkeypatch
):
    """Recover the exact CREATED production shape without rewriting its snapshot lineage."""
    from conftest import publish_verified_intake_workspace, setup_managed_repository_fixture

    project_id = f"n01-created-{uuid.uuid4().hex[:8]}"
    change_name = "operational-blocker-visibility"
    run_id = "627adcf0-ee2a-4e3b-8211-1972c7dbec00"
    job_id = "7c6c20dd-cf8f-486d-ad3e-e0e5de1b19e0"
    recovery_branch = f"minime/{change_name}-{job_id}"
    managed_root = tmp_path / "managed"
    worktree_parent = tmp_path / "worktrees"
    remote = tmp_path / "managed.origin.git"

    with isolated_pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        project = Project(
            project_id=project_id,
            display_name="N01 CREATED recovery regression",
            repository=str(remote),
            base_branch="main",
            openspec_path="openspec",
            implementer="codex",
        )
        uow.projects.save(project)
        binding = setup_managed_repository_fixture(
            uow,
            project_id=project_id,
            repo_root=managed_root,
            worktree_parent_dir=worktree_parent,
            canonical_repository_identity=str(remote),
            remote_url=str(remote),
        )
        assert project.repository == binding.canonical_repository_identity
        _git(managed_root, "push", "origin", "main")
        base_sha = _git(managed_root, "rev-parse", "main")
        published = publish_verified_intake_workspace(uow, project, managed_root, change_name)
        published_sha = published.published_sha
        assert published_sha and published.published_ref == f"refs/minime/intake/{change_name}"

        uow.jobs.save(
            Job(
                job_id=job_id,
                project_id=project_id,
                change_name=change_name,
                implementer_role="codex",
                current_executor="codex",
                status=JobStatus.NEEDS_HUMAN,
                base_sha=base_sha,
                attempt_count=1,
            )
        )
        uow.orchestration_runs.save(
            OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name=change_name,
                base_sha=base_sha,
                current_stage=OrchestrationStage.IMPLEMENTING,
                resumable_stage=OrchestrationStage.IMPLEMENTING,
                active_job_id=job_id,
                current_candidate_sha=None,
                is_active=False,
                stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
                human_gate=HumanGate.NEEDS_HUMAN,
            )
        )
        uow.provider_health.save(
            ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
        )
        uow.job_attempts.save(
            JobAttempt(
                job_id=job_id,
                attempt_number=1,
                executor_role="codex",
                model_identity="codex",
                normalized_outcome=ExecutionOutcome.ENVIRONMENT_UNAVAILABLE,
            )
        )
        uow.commit()

        manager = WorktreeManager(managed_root, uow)
        original = asyncio.run(
            manager.create_worktree(
                job_id,
                change_name,
                base_branch="main",
                project_id=project_id,
                branch_name=recovery_branch,
                run_id=run_id,
            )
        )
        assert original.base_sha == base_sha
        worktree_path = original.path
        artifact_root = worktree_path / "openspec" / "changes" / change_name
        artifact_files = sorted(path for path in artifact_root.rglob("*") if path.is_file())
        assert len(artifact_files) == 4
        historical_contents: dict[str, bytes] = {}
        for artifact_path in artifact_files:
            relative = artifact_path.relative_to(artifact_root).as_posix()
            contents = artifact_path.read_bytes()
            assert contents.endswith(b"\n")
            artifact_path.write_bytes(contents[:-1])
            historical_contents[relative] = contents[:-1]

        snapshot_sha = asyncio.run(manager.create_recovery_snapshot(job_id, project_id))
        assert snapshot_sha and snapshot_sha != base_sha
        ownership_id = uow.orchestration_worktree_ownerships.get_by_job_id(job_id).worktree_id
        uow.events.save(
            Event(
                event_type=EventType.WORKTREE_RECOVERY_SNAPSHOT,
                project_id=project_id,
                change_id=change_name,
                operation_id=job_id,
                payload={
                    "job_id": job_id,
                    "branch": recovery_branch,
                    "recovery_sha": snapshot_sha,
                    "worktree_path": str(worktree_path.resolve()),
                    "authoritative_candidate": False,
                },
            )
        )
        uow.commit()
        assert (
            asyncio.run(manager.remove_clean_worktree(job_id, project_id)).outcome
            == ExternalOutcome.SUCCESS
        )
        assert not worktree_path.exists()
        assert _git(managed_root, "rev-parse", f"refs/heads/{recovery_branch}") == snapshot_sha

        clone = tmp_path / "advancing-clone"
        subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True)
        _git(clone, "config", "user.name", "Remote Main Advance")
        _git(clone, "config", "user.email", "advance@localhost")
        (clone / "unrelated-main-advance.txt").write_text("unrelated\n")
        _git(clone, "add", "unrelated-main-advance.txt")
        _git(clone, "commit", "-m", "unrelated main advance")
        _git(clone, "push", "origin", "main")
        current_main_sha = _git(clone, "rev-parse", "main")
        assert _git(managed_root, "rev-parse", "main") == base_sha
        _git(clone, "merge-base", "--is-ancestor", base_sha, current_main_sha)

        runtime_root = tmp_path / "runtime"
        runtime_root.mkdir()
        monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime_root))
        diagnostic_cli = tmp_path / "diagnostic-cli"
        diagnostic_cli.write_text(
            "#!/usr/bin/env python3\nimport sys\n"
            "if '--help' in sys.argv:\n    print('diagnostic cli help')\n"
            "else:\n"
            f"    assert __import__('pathlib').Path('openspec/changes/{change_name}/proposal.md').is_file()\n"
            "    print('EROFS: test-only local environment stop', file=sys.stderr)\n",
            encoding="utf-8",
        )
        diagnostic_cli.chmod(0o700)
        profile = CliInvocationProfile(
            provider="diagnostic-cli",
            role="implementer",
            executable=str(diagnostic_cli),
            args=(),
            prompt_transport="stdin",
        )

        class RecordingRunner:
            def __init__(self):
                self.delegate = CliImplementerRunner(profile)
                self.result = None
                self.head_sha = None
                self.branch = None
                self.marker_base_sha = None
                self.ownership_base_sha = None
                self.artifact_bytes: dict[str, bytes] = {}
                self.repair_only_pending = None

            async def run(self, candidate_path, prompt_context, timeout_seconds):
                candidate_path = Path(candidate_path)
                self.head_sha = _git(candidate_path, "rev-parse", "HEAD")
                self.branch = _git(candidate_path, "branch", "--show-current")
                marker = json.loads(
                    (candidate_path / ".minime_worktree_ownership.json").read_text()
                )
                self.marker_base_sha = marker["source_base_sha"]
                self.ownership_base_sha = uow.orchestration_worktree_ownerships.get_by_job_id(
                    job_id
                ).source_base_sha
                candidate_artifacts = candidate_path / "openspec" / "changes" / change_name
                self.artifact_bytes = {
                    path.relative_to(candidate_artifacts).as_posix(): path.read_bytes()
                    for path in candidate_artifacts.rglob("*")
                    if path.is_file()
                }
                self.repair_only_pending = await manager._only_published_intake_repair_is_pending(
                    candidate_path, job_id, project_id
                )
                self.result = await self.delegate.run(
                    candidate_path, prompt_context, timeout_seconds
                )
                return self.result

        runner = RecordingRunner()
        monkeypatch.setattr(execution_pipeline, "runner_for_implementer", lambda _provider: runner)
        original_materialize = WorktreeManager._materialize_verified_published_intake_artifacts

        async def fail_first_materialization(self, **kwargs):
            raise RuntimeError(
                "Execution handoff denied: existing OpenSpec materialization content differs from the published tree."
            )

        monkeypatch.setattr(
            WorktreeManager,
            "_materialize_verified_published_intake_artifacts",
            fail_first_materialization,
        )

        def make_request(action_request_id: str) -> OperatorActionRequest:
            current_run = uow.orchestration_runs.get_by_id(run_id)
            return OperatorActionRequest(
                action_request_id=action_request_id,
                project_id=project_id,
                change_name=change_name,
                run_id=run_id,
                action_type=OperatorActionType.CONTINUE,
                actor_identity="test-operator-legacy-artifact-recovery",
                source_interface="cli",
                expected_stage=current_run.current_stage,
                expected_generation=current_run.current_generation,
                expected_candidate_sha=current_run.current_candidate_sha,
            )

        first_result = ControlPlaneService(uow, project_root=managed_root).execute_action(
            make_request(str(uuid.uuid4()))
        )
        created_ownership = uow.orchestration_worktree_ownerships.get_by_job_id(job_id)
        assert created_ownership.creation_state == WorktreeCreationState.CREATED
        assert worktree_path.exists()
        assert _git(worktree_path, "rev-parse", "HEAD") == snapshot_sha
        assert _git(managed_root, "rev-parse", f"refs/heads/{recovery_branch}") == snapshot_sha
        assert runner.result is None
        assert first_result.status in {OperatorActionStatus.COMPLETED, OperatorActionStatus.FAILED}

        staged_artifact = Path("openspec/changes") / change_name / "design.md"
        staged_file = worktree_path / staged_artifact
        original_staged_bytes = staged_file.read_bytes()
        staged_file.write_bytes(original_staged_bytes + b"unauthorized staged change")
        _git(worktree_path, "add", str(staged_artifact))
        staged_file.write_bytes(original_staged_bytes)
        with pytest.raises(RuntimeError, match="changes outside the historical artifact tree"):
            asyncio.run(
                manager._verify_deleted_worktree_recreation(
                    job_id=job_id,
                    project_id=project_id,
                    run_id=run_id,
                    change_name=change_name,
                    path=worktree_path.resolve(),
                    branch=recovery_branch,
                    base_branch="main",
                    current_base_sha=base_sha,
                )
            )
        _git(worktree_path, "reset", "HEAD", "--", str(staged_artifact))
        failed_job = uow.jobs.get_by_id(job_id)
        failed_run = uow.orchestration_runs.get_by_id(run_id)
        assert failed_job.status == JobStatus.FAILED
        assert failed_job.attempt_count == 1
        assert failed_run.is_active is False
        assert failed_run.stop_outcome == OrchestrationStopOutcome.NEEDS_HUMAN
        assert first_result.payload["run_active"] is False
        assert first_result.payload["execution_active"] is False
        assert first_result.payload["linked_job_status"] == JobStatus.FAILED.value
        assert "resumed successfully" not in first_result.summary.lower()

        artifact_root = worktree_path / "openspec" / "changes" / change_name

        async def materialize_recovery() -> None:
            await original_materialize(
                manager,
                destination_worktree=worktree_path,
                project_id=project_id,
                change_name=change_name,
                job_id=job_id,
                recovery_snapshot_sha=snapshot_sha,
            )

        # A non-LF byte mutation, extra/missing path, symlink and contradictory
        # persisted publication all fail before any eligible file is repaired.
        proposal_path = artifact_root / "proposal.md"
        proposal_bytes = proposal_path.read_bytes()
        proposal_path.write_bytes(b"X" + proposal_bytes[1:])
        with pytest.raises(RuntimeError, match="unauthorized content"):
            asyncio.run(materialize_recovery())
        proposal_path.write_bytes(proposal_bytes)

        unexpected_path = artifact_root / "unexpected.md"
        unexpected_path.write_text("not in published manifest\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="manifest"):
            asyncio.run(materialize_recovery())
        unexpected_path.unlink()

        tasks_path = artifact_root / "tasks.md"
        tasks_bytes = tasks_path.read_bytes()
        tasks_path.unlink()
        with pytest.raises(RuntimeError, match="manifest"):
            asyncio.run(materialize_recovery())
        tasks_path.write_bytes(tasks_bytes)

        design_path = artifact_root / "design.md"
        design_bytes = design_path.read_bytes()
        design_path.unlink()
        design_path.symlink_to(tmp_path / "outside-design.md")
        with pytest.raises(RuntimeError, match="symlink"):
            asyncio.run(materialize_recovery())
        design_path.unlink()
        design_path.write_bytes(design_bytes)

        persisted_ownership = uow.intake_workspace_ownerships.get_by_item_key(
            project_id, change_name
        )
        valid_published_sha = persisted_ownership.published_sha
        persisted_ownership.published_sha = "0" * len(valid_published_sha)
        uow.intake_workspace_ownerships.save(persisted_ownership)
        uow.commit()
        with pytest.raises(RuntimeError, match="ref drifted or is unobservable"):
            asyncio.run(materialize_recovery())
        persisted_ownership.published_sha = valid_published_sha
        uow.intake_workspace_ownerships.save(persisted_ownership)
        uow.commit()

        # Simulate interruption after one atomic LF append. A subsequent
        # canonical CONTINUE must recognize the exact published/snapshot mix.
        real_write = os.write
        writes = 0

        def interrupt_after_one_write(fd: int, data: bytes) -> int:
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("test-only interruption after one verified repair")
            return real_write(fd, data)

        with monkeypatch.context() as patcher:
            patcher.setattr(os, "write", interrupt_after_one_write)
            with pytest.raises(OSError, match="test-only interruption"):
                asyncio.run(materialize_recovery())
        assert writes == 2

        monkeypatch.setattr(
            WorktreeManager,
            "_materialize_verified_published_intake_artifacts",
            original_materialize,
        )
        second_result = ControlPlaneService(uow, project_root=managed_root).execute_action(
            make_request(str(uuid.uuid4()))
        )
        assert second_result.status == OperatorActionStatus.COMPLETED, second_result.summary
        assert second_result.payload["execution_active"] is False
        assert second_result.payload["linked_job_status"] == JobStatus.WAITING_CAPACITY.value
        assert "resumed successfully" not in second_result.summary.lower()
        assert runner.result is not None
        assert runner.head_sha == snapshot_sha
        assert runner.branch == recovery_branch
        assert runner.marker_base_sha == base_sha
        assert runner.ownership_base_sha == base_sha
        assert runner.repair_only_pending is True
        assert runner.artifact_bytes == {
            relative: _git_bytes(
                managed_root,
                "show",
                f"{published_sha}:openspec/changes/{change_name}/{relative}",
            )
            for relative in historical_contents
        }
        assert runner.result.stderr == ["EROFS: test-only local environment stop"]

        repaired_stats = {
            relative: (artifact_root / relative).stat().st_mtime_ns
            for relative in historical_contents
        }
        asyncio.run(materialize_recovery())
        assert {
            relative: (artifact_root / relative).stat().st_mtime_ns
            for relative in historical_contents
        } == repaired_stats
        assert (
            len(
                [
                    event
                    for event in uow.events.list_events(
                        project_id=project_id, change_id=change_name, limit=10000
                    )
                    if event.event_type == EventType.INTAKE_ARTIFACT_HANDOFF_RECONCILED
                ]
            )
            == 1
        )

        snapshot_event = next(
            event
            for event in uow.events.list_events(
                project_id=project_id, change_id=change_name, limit=10000
            )
            if event.event_type == EventType.WORKTREE_RECOVERY_SNAPSHOT
        )
        persisted_snapshot_event = session.get(EventModel, snapshot_event.event_id)
        original_snapshot_payload = dict(persisted_snapshot_event.payload)
        persisted_snapshot_event.payload = {
            **original_snapshot_payload,
            "recovery_sha": "contradictory-created-snapshot",
        }
        uow.commit()
        with pytest.raises(RuntimeError, match="snapshot event"):
            asyncio.run(
                manager._verify_deleted_worktree_recreation(
                    job_id=job_id,
                    project_id=project_id,
                    run_id=run_id,
                    change_name=change_name,
                    path=worktree_path.resolve(),
                    branch=recovery_branch,
                    base_branch="main",
                    current_base_sha=base_sha,
                )
            )
        persisted_snapshot_event.payload = original_snapshot_payload
        uow.commit()

        persisted_job = uow.jobs.get_by_id(job_id)
        persisted_run = uow.orchestration_runs.get_by_id(run_id)
        persisted_ownership = uow.orchestration_worktree_ownerships.get_by_job_id(job_id)
        assert persisted_job.job_id == job_id and persisted_job.base_sha == base_sha
        assert persisted_run.run_id == run_id and persisted_run.base_sha == base_sha
        assert persisted_run.active_job_id == job_id and persisted_run.current_candidate_sha is None
        assert persisted_job.candidate_sha is None
        assert persisted_ownership.worktree_id == ownership_id
        assert persisted_ownership.source_base_sha == base_sha
        assert _git(managed_root, "rev-parse", "main") == base_sha
        assert _git(managed_root, "rev-parse", f"refs/heads/{recovery_branch}") == snapshot_sha
        assert len(uow.job_attempts.list_by_job(job_id)) == 2
        assert len(uow.operator_actions.list_by_run(run_id)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(OrchestrationRunModel)
                .where(OrchestrationRunModel.project_id == project_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(JobModel).where(JobModel.project_id == project_id)
            )
            == 1
        )
        reconciliation_events = [
            event
            for event in uow.events.list_events(
                project_id=project_id, change_id=change_name, limit=10000
            )
            if event.event_type == EventType.INTAKE_ARTIFACT_HANDOFF_RECONCILED
        ]
        assert len(reconciliation_events) == 1
        assert set(reconciliation_events[0].payload["reconciled_paths"]) == set(historical_contents)
        assert set(reconciliation_events[0].payload["prior_sha256"]) == set(historical_contents)


def test_postgres_continue_accepts_only_recovery_evidenced_incomplete_premature_stop(
    isolated_pg_session_factory, tmp_path: Path, monkeypatch
):
    """One canonical CONTINUE emits recovery evidence and adopts the same CREATED worktree."""
    from datetime import timedelta

    from conftest import publish_verified_intake_workspace, setup_managed_repository_fixture

    project_id = f"n01-crash-{uuid.uuid4().hex[:8]}"
    change_name = "operational-blocker-visibility"
    run_id = "627adcf0-ee2a-4e3b-8211-1972c7dbec00"
    job_id = "7c6c20dd-cf8f-486d-ad3e-e0e5de1b19e0"
    recovery_branch = f"minime/{change_name}-{job_id}"
    managed_root = tmp_path / "managed"
    worktree_parent = tmp_path / "worktrees"
    remote = tmp_path / "managed.origin.git"

    with isolated_pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        project = Project(
            project_id=project_id,
            display_name="N01 crash recovery regression",
            repository=str(remote),
            base_branch="main",
            openspec_path="openspec",
            implementer="codex",
        )
        uow.projects.save(project)
        setup_managed_repository_fixture(
            uow,
            project_id=project_id,
            repo_root=managed_root,
            worktree_parent_dir=worktree_parent,
            canonical_repository_identity=str(remote),
            remote_url=str(remote),
        )
        _git(managed_root, "push", "origin", "main")
        base_sha = _git(managed_root, "rev-parse", "main")
        intake_ownership = publish_verified_intake_workspace(
            uow, project, managed_root, change_name
        )
        published_sha = intake_ownership.published_sha
        assert published_sha

        job = Job(
            job_id=job_id,
            project_id=project_id,
            change_name=change_name,
            implementer_role="codex",
            current_executor="codex",
            status=JobStatus.FAILED,
            base_sha=base_sha,
            attempt_count=1,
        )
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name=change_name,
            base_sha=base_sha,
            current_stage=OrchestrationStage.IMPLEMENTING,
            resumable_stage=OrchestrationStage.IMPLEMENTING,
            active_job_id=job_id,
            current_candidate_sha=None,
            is_active=False,
            stop_outcome=OrchestrationStopOutcome.NEEDS_HUMAN,
            human_gate=HumanGate.NEEDS_HUMAN,
            stop_reason="Host interrupted the in-flight executor process.",
        )
        uow.jobs.save(job)
        uow.orchestration_runs.save(run)
        uow.provider_health.save(
            ProviderHealth(provider="codex", status=ProviderHealthStatus.AVAILABLE)
        )
        first_attempt_at = utc_now() - timedelta(minutes=5)
        crash_attempt_at = utc_now() - timedelta(minutes=3)
        uow.job_attempts.save(
            JobAttempt(
                job_id=job_id,
                attempt_number=1,
                executor_role="codex",
                model_identity="codex",
                normalized_outcome=ExecutionOutcome.ENVIRONMENT_UNAVAILABLE,
                completed_at=first_attempt_at + timedelta(seconds=4),
                duration_ms=4000,
                started_at=first_attempt_at,
            )
        )
        crash_attempt = JobAttempt(
            job_id=job_id,
            attempt_number=2,
            executor_role="codex",
            model_identity="codex",
            start_sha=base_sha,
            normalized_outcome=ExecutionOutcome.PREMATURE_STOP,
            started_at=crash_attempt_at,
            completed_at=None,
            duration_ms=None,
        )
        uow.job_attempts.save(crash_attempt)
        uow.commit()

        manager = WorktreeManager(managed_root, uow)
        worktree = asyncio.run(
            manager.create_worktree(
                job_id,
                change_name,
                base_branch="main",
                project_id=project_id,
                branch_name=recovery_branch,
                run_id=run_id,
            )
        )
        assert worktree.base_sha == base_sha
        artifact_root = worktree.path / "openspec" / "changes" / change_name
        published_paths = _git(
            managed_root,
            "ls-tree",
            "-r",
            "--name-only",
            published_sha,
            "--",
            f"openspec/changes/{change_name}/",
        ).splitlines()
        assert len(published_paths) >= 4
        for repository_path in published_paths:
            relative = Path(repository_path).relative_to(Path("openspec/changes") / change_name)
            content = _git_bytes(managed_root, "show", f"{published_sha}:{repository_path}")
            assert content.endswith(b"\n")
            target = artifact_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content[:-1])

        snapshot_sha = asyncio.run(manager.create_recovery_snapshot(job_id, project_id))
        assert snapshot_sha and snapshot_sha != base_sha
        ownership_before = uow.orchestration_worktree_ownerships.get_by_job_id(job_id)
        assert ownership_before.creation_state == WorktreeCreationState.CREATED
        assert ownership_before.source_base_sha == base_sha
        snapshot_payload = {
            "job_id": job_id,
            "branch": recovery_branch,
            "recovery_sha": snapshot_sha,
            "worktree_path": str(worktree.path.resolve()),
            "authoritative_candidate": False,
        }
        uow.events.save(
            Event(
                event_type=EventType.WORKTREE_RECOVERY_SNAPSHOT,
                project_id=project_id,
                change_id=change_name,
                operation_id=job_id,
                payload=snapshot_payload,
            )
        )
        uow.commit()
        assert _git(worktree.path, "rev-parse", "HEAD") == snapshot_sha
        assert _git(worktree.path, "status", "--porcelain=v1", "--untracked-files=all") == ""

        advancing_clone = tmp_path / "crash-recovery-main-advance"
        subprocess.run(
            ["git", "clone", str(remote), str(advancing_clone)],
            check=True,
            capture_output=True,
            text=True,
        )
        _git(advancing_clone, "config", "user.name", "Remote Main Advance")
        _git(advancing_clone, "config", "user.email", "advance@localhost")
        (advancing_clone / "unrelated-main-advance.txt").write_text("unrelated\n")
        _git(advancing_clone, "add", "unrelated-main-advance.txt")
        _git(advancing_clone, "commit", "-m", "unrelated main advance")
        _git(advancing_clone, "push", "origin", "main")
        advanced_main_sha = _git(advancing_clone, "rev-parse", "main")
        assert advanced_main_sha != base_sha
        assert _git(managed_root, "rev-parse", "main") == base_sha
        _git(advancing_clone, "merge-base", "--is-ancestor", base_sha, advanced_main_sha)

        def verify_recovery_denied(reason: str) -> None:
            with pytest.raises(RuntimeError, match=reason):
                asyncio.run(
                    manager._verify_deleted_worktree_recreation(
                        job_id=job_id,
                        project_id=project_id,
                        run_id=run_id,
                        change_name=change_name,
                        path=worktree.path.resolve(),
                        branch=recovery_branch,
                        base_branch="main",
                        current_base_sha=base_sha,
                    )
                )

        # The production-equivalent pre-CONTINUE state contains no startup
        # interruption/recovery events. A CREATED snapshot alone is not enough.
        verify_recovery_denied("does not prove an environment/provider")
        assert not any(
            event.event_type
            in {
                EventType.JOB_INTERRUPTED,
                EventType.JOB_RECOVERED,
                EventType.ORCHESTRATION_RECOVERED,
            }
            for event in uow.events.list_events(
                project_id=project_id, change_id=change_name, limit=10000
            )
        )

        # A finalized PREMATURE_STOP is never covered by the crash exception.
        persisted_attempt = session.get(JobAttemptModel, crash_attempt.attempt_id)
        persisted_attempt.completed_at = crash_attempt_at + timedelta(seconds=5)
        persisted_attempt.duration_ms = 1
        session.commit()
        verify_recovery_denied("does not prove an environment/provider")
        persisted_attempt.completed_at = None
        persisted_attempt.duration_ms = None
        session.commit()

        # Restore the intentionally incomplete attempt without manufacturing
        # any recovery events. The single real CONTINUE below must create the
        # JOB_RECOVERED evidence through RecoveryConvergenceService itself.
        persisted_attempt.completed_at = None
        persisted_attempt.duration_ms = None
        session.commit()

        persisted_job_before_continue = uow.jobs.get_by_id(job_id)
        persisted_attempts_before_continue = uow.job_attempts.list_by_job(job_id)
        assert persisted_job_before_continue.attempt_count == 1
        assert persisted_attempts_before_continue[-1].attempt_number == 2
        assert (
            persisted_attempts_before_continue[-1].normalized_outcome
            == ExecutionOutcome.PREMATURE_STOP
        )
        assert persisted_attempts_before_continue[-1].completed_at is None
        assert persisted_attempts_before_continue[-1].duration_ms is None

        persisted_job_for_candidate = session.get(JobModel, job_id)
        persisted_run_for_candidate = session.get(OrchestrationRunModel, run_id)
        persisted_job_for_candidate.candidate_sha = "unauthorized-candidate"
        persisted_run_for_candidate.current_candidate_sha = "unauthorized-candidate"
        session.commit()
        with pytest.raises(RuntimeError, match="candidate evidence exists"):
            asyncio.run(
                manager._verify_deleted_worktree_recreation(
                    job_id=job_id,
                    project_id=project_id,
                    run_id=run_id,
                    change_name=change_name,
                    path=worktree.path.resolve(),
                    branch=recovery_branch,
                    base_branch="main",
                    current_base_sha=base_sha,
                )
            )
        persisted_job_for_candidate.candidate_sha = None
        persisted_run_for_candidate.current_candidate_sha = None
        session.commit()

        untracked = worktree.path / "unauthorized.txt"
        untracked.write_text("must block\n", encoding="utf-8")
        # Exercise the shared Git cleanliness guard independently of the new
        # crash-evidence predicate; no recovery event is fabricated here.
        persisted_attempt.normalized_outcome = ExecutionOutcome.ENVIRONMENT_UNAVAILABLE.value
        session.commit()
        with pytest.raises(RuntimeError, match="CREATED recovery worktree contains changes"):
            asyncio.run(
                manager._verify_deleted_worktree_recreation(
                    job_id=job_id,
                    project_id=project_id,
                    run_id=run_id,
                    change_name=change_name,
                    path=worktree.path.resolve(),
                    branch=recovery_branch,
                    base_branch="main",
                    current_base_sha=base_sha,
                )
            )
        persisted_attempt.normalized_outcome = ExecutionOutcome.PREMATURE_STOP.value
        session.commit()
        untracked.unlink()

        ownership = uow.orchestration_worktree_ownerships.get_by_job_id(job_id)
        ownership.creation_state = WorktreeCreationState.DELETED
        uow.orchestration_worktree_ownerships.save(ownership)
        uow.commit()
        with pytest.raises(RuntimeError, match="DELETED worktree path is not absent"):
            asyncio.run(
                manager._verify_deleted_worktree_recreation(
                    job_id=job_id,
                    project_id=project_id,
                    run_id=run_id,
                    change_name=change_name,
                    path=worktree.path.resolve(),
                    branch=recovery_branch,
                    base_branch="main",
                    current_base_sha=base_sha,
                )
            )
        ownership.creation_state = WorktreeCreationState.CREATED
        uow.orchestration_worktree_ownerships.save(ownership)
        uow.commit()

        runtime_root = tmp_path / "runtime"
        runtime_root.mkdir()
        monkeypatch.setenv("MINIME_RUNTIME_ROOT", str(runtime_root))
        diagnostic_cli = tmp_path / "diagnostic-cli"
        diagnostic_cli.write_text(
            "#!/usr/bin/env python3\nimport sys\n"
            "if '--help' in sys.argv:\n    print('diagnostic cli help')\n"
            "else:\n    print('diagnostic runner reached')\n",
            encoding="utf-8",
        )
        diagnostic_cli.chmod(0o700)
        profile = CliInvocationProfile(
            provider="diagnostic-cli",
            role="implementer",
            executable=str(diagnostic_cli),
            args=(),
            prompt_transport="stdin",
        )

        class RecordingRunner:
            def __init__(self):
                self.delegate = CliImplementerRunner(profile)
                self.result = None

            async def run(self, candidate_path, prompt_context, timeout_seconds):
                assert Path(candidate_path).resolve() == worktree.path.resolve()
                assert _git(Path(candidate_path), "rev-parse", "HEAD") == snapshot_sha
                assert _git(Path(candidate_path), "branch", "--show-current") == recovery_branch
                self.result = await self.delegate.run(
                    candidate_path, prompt_context, timeout_seconds
                )
                return self.result

        runner = RecordingRunner()
        monkeypatch.setattr(execution_pipeline, "runner_for_implementer", lambda _provider: runner)
        before_runs = session.scalar(
            select(func.count())
            .select_from(OrchestrationRunModel)
            .where(OrchestrationRunModel.project_id == project_id)
        )
        before_jobs = session.scalar(
            select(func.count()).select_from(JobModel).where(JobModel.project_id == project_id)
        )
        action_run = uow.orchestration_runs.get_by_id(run_id)
        result = ControlPlaneService(uow, project_root=managed_root).execute_action(
            OperatorActionRequest(
                action_request_id=str(uuid.uuid4()),
                project_id=project_id,
                change_name=change_name,
                run_id=run_id,
                action_type=OperatorActionType.CONTINUE,
                actor_identity="test-crash-recovery-operator",
                source_interface="cli",
                expected_stage=action_run.current_stage,
                expected_generation=action_run.current_generation,
                expected_candidate_sha=action_run.current_candidate_sha,
            )
        )
        assert result.status == OperatorActionStatus.COMPLETED, result.summary
        generated_recovery_events = [
            event
            for event in uow.events.list_events(
                project_id=project_id, change_id=change_name, limit=10000
            )
            if event.event_type == EventType.JOB_RECOVERED
            and event.operation_id == job_id
            and event.timestamp > crash_attempt.started_at
        ]
        assert generated_recovery_events, "canonical CONTINUE did not persist JOB_RECOVERED"
        assert any(
            event.payload.get("run_id") == run_id
            and event.payload.get("run_generation") == run.current_generation
            and event.payload.get("recovery_source") == "CONTROL_PLANE"
            and event.payload.get("interrupted_stage") == "implementer"
            and event.payload.get("recovered_status") == JobStatus.QUEUED.value
            for event in generated_recovery_events
        )
        assert not any(
            event.event_type in {EventType.JOB_INTERRUPTED, EventType.ORCHESTRATION_RECOVERED}
            for event in uow.events.list_events(
                project_id=project_id, change_id=change_name, limit=10000
            )
        )
        assert runner.result is not None
        assert "diagnostic runner reached" in "\n".join(runner.result.stdout)
        persisted_job = uow.jobs.get_by_id(job_id)
        persisted_run = uow.orchestration_runs.get_by_id(run_id)
        persisted_ownership = uow.orchestration_worktree_ownerships.get_by_job_id(job_id)
        assert persisted_job.job_id == job_id and persisted_job.base_sha == base_sha
        assert persisted_job.attempt_count >= 1
        original_inflight_attempt = uow.job_attempts.get_by_id(crash_attempt.attempt_id)
        assert original_inflight_attempt.normalized_outcome == ExecutionOutcome.PREMATURE_STOP
        assert original_inflight_attempt.completed_at is None
        assert original_inflight_attempt.duration_ms is None
        assert persisted_run.run_id == run_id and persisted_run.base_sha == base_sha
        assert persisted_run.active_job_id == job_id
        assert persisted_job.candidate_sha is None and persisted_run.current_candidate_sha is None
        assert persisted_ownership.creation_state == WorktreeCreationState.CREATED
        assert persisted_ownership.source_base_sha == base_sha
        assert (
            _git(advancing_clone, "ls-remote", "origin", "refs/heads/main").split()[0]
            == advanced_main_sha
        )
        assert _git(managed_root, "rev-parse", f"refs/heads/{recovery_branch}") == snapshot_sha
        assert (
            _git(managed_root, "ls-remote", "origin", f"refs/minime/intake/{change_name}").split()[
                0
            ]
            == published_sha
        )
        assert len(uow.job_attempts.list_by_job(job_id)) >= 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(OrchestrationRunModel)
                .where(OrchestrationRunModel.project_id == project_id)
            )
            == before_runs
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(JobModel).where(JobModel.project_id == project_id)
            )
            == before_jobs
            == 1
        )


@pytest.mark.parametrize(
    "payload_update,event_age_seconds,expected",
    [
        ({}, 1, True),  # positive control: fully valid event, decision, and live claim
        ({"recovery_source": "STARTUP"}, 1, False),
        ({"run_id": "different-run"}, 1, False),
        ({"run_generation": 2}, 1, False),
        ({"recovered_status": JobStatus.FAILED.value}, 1, False),
        ({}, 600, False),  # recovery event predates the interrupted attempt
    ],
)
def test_crash_recovery_predicate_accepts_valid_and_rejects_contradictory_evidence(
    tmp_path: Path, payload_update: dict, event_age_seconds: int, expected: bool
):
    """Exercise event-specific checks with otherwise valid recovery authority."""
    from datetime import timedelta

    project_id = "predicate-project"
    change_name = "operational-blocker-visibility"
    run_id = "predicate-run"
    job_id = "predicate-job"
    base_sha = "b" * 40
    attempt_started = utc_now() - timedelta(minutes=2)
    event = Event(
        event_type=EventType.JOB_RECOVERED,
        project_id=project_id,
        change_id=change_name,
        operation_id=job_id,
        timestamp=attempt_started - timedelta(seconds=event_age_seconds)
        if event_age_seconds > 10
        else attempt_started + timedelta(seconds=event_age_seconds),
        payload={
            "job_id": job_id,
            "run_id": run_id,
            "run_generation": 1,
            "recovery_source": "CONTROL_PLANE",
            "interrupted_stage": "implementer",
            "recovered_status": JobStatus.QUEUED.value,
            "recovery_cycle_id": "cycle-1",
            **payload_update,
        },
    )

    class EventRepository:
        def list_events(self, **_kwargs):
            return [event]

    class ExternalActions:
        def list_by_run(self, _run_id):
            return []

    class Decisions:
        def list_by_cycle(self, cycle_id):
            if cycle_id != "cycle-1":
                return []
            return [
                SimpleNamespace(
                    claim_key=f"run:{run_id}",
                    identity_type="RUN",
                    identity_id=run_id,
                    project_id=project_id,
                    change_name=change_name,
                    source="CONTROL_PLANE",
                    planned_action="DRIVE_CONTINUATION",
                    status="EXECUTING",
                    fence_token=7,
                )
            ]

    class Claims:
        def get_by_key(self, claim_key):
            if claim_key != f"run:{run_id}":
                return None
            return SimpleNamespace(is_active=True, fence_token=7, owner_instance_id="worker")

        def validate_cas(self, *, claim_key, owner_instance_id, fence_token):
            return (
                claim_key == f"run:{run_id}" and owner_instance_id == "worker" and fence_token == 7
            )

    manager = WorktreeManager(
        tmp_path,
        SimpleNamespace(
            events=EventRepository(),
            orchestration_external_actions=ExternalActions(),
            recovery_decisions=Decisions(),
            claims=Claims(),
        ),
    )
    accepted = manager._has_durable_crash_interruption_recovery(
        latest_attempt=SimpleNamespace(
            normalized_outcome=ExecutionOutcome.PREMATURE_STOP,
            completed_at=None,
            duration_ms=None,
            attempt_number=2,
            started_at=attempt_started,
        ),
        job=SimpleNamespace(
            job_id=job_id,
            attempt_count=1,
            project_id=project_id,
            change_name=change_name,
            candidate_sha=None,
            base_sha=base_sha,
        ),
        run=SimpleNamespace(
            run_id=run_id,
            project_id=project_id,
            change_name=change_name,
            active_job_id=job_id,
            current_stage=OrchestrationStage.IMPLEMENTING,
            current_generation=1,
            current_candidate_sha=None,
            base_sha=base_sha,
        ),
        source_base=base_sha,
        project_id=project_id,
        change_name=change_name,
    )
    assert accepted is expected


@pytest.mark.parametrize("pending_external_action,claim_valid", [(True, True), (False, False)])
def test_crash_recovery_predicate_rejects_stale_claim_or_pending_external_action(
    tmp_path: Path, pending_external_action: bool, claim_valid: bool
):
    """A stale fence or unresolved external effect blocks this no-candidate path."""
    from datetime import timedelta

    project_id = "predicate-project"
    change_name = "operational-blocker-visibility"
    run_id = "predicate-run"
    job_id = "predicate-job"
    base_sha = "b" * 40
    started_at = utc_now() - timedelta(minutes=1)
    event = Event(
        event_type=EventType.JOB_RECOVERED,
        project_id=project_id,
        change_id=change_name,
        operation_id=job_id,
        timestamp=utc_now(),
        payload={
            "job_id": job_id,
            "run_id": run_id,
            "run_generation": 1,
            "recovery_source": "CONTROL_PLANE",
            "interrupted_stage": "implementer",
            "recovered_status": JobStatus.QUEUED.value,
            "recovery_cycle_id": "cycle-1",
        },
    )

    class Repository:
        def list_events(self, **_kwargs):
            return [event]

        def list_by_run(self, _run_id):
            return (
                [
                    SimpleNamespace(
                        candidate_sha=None,
                        status=ExternalActionStatus.AMBIGUOUS,
                    )
                ]
                if pending_external_action
                else []
            )

        def list_by_cycle(self, cycle_id):
            assert cycle_id == "cycle-1"
            return [
                SimpleNamespace(
                    claim_key=f"run:{run_id}",
                    identity_type="RUN",
                    identity_id=run_id,
                    project_id=project_id,
                    change_name=change_name,
                    source="CONTROL_PLANE",
                    planned_action="DRIVE_CONTINUATION",
                    status="EXECUTING",
                    fence_token=7,
                )
            ]

    class Claims:
        def get_by_key(self, claim_key):
            assert claim_key == f"run:{run_id}"
            return SimpleNamespace(is_active=True, fence_token=7, owner_instance_id="worker")

        def validate_cas(self, *, claim_key, owner_instance_id, fence_token):
            return (
                claim_key == f"run:{run_id}" and owner_instance_id == "worker" and fence_token == 7
            ) and claim_valid

    manager = WorktreeManager(
        tmp_path,
        SimpleNamespace(
            events=Repository(),
            orchestration_external_actions=Repository(),
            recovery_decisions=Repository(),
            claims=Claims(),
        ),
    )
    assert not manager._has_durable_crash_interruption_recovery(
        latest_attempt=SimpleNamespace(
            normalized_outcome=ExecutionOutcome.PREMATURE_STOP,
            completed_at=None,
            duration_ms=None,
            attempt_number=2,
            started_at=started_at,
        ),
        job=SimpleNamespace(
            job_id=job_id,
            attempt_count=1,
            project_id=project_id,
            change_name=change_name,
            candidate_sha=None,
            base_sha=base_sha,
        ),
        run=SimpleNamespace(
            run_id=run_id,
            project_id=project_id,
            change_name=change_name,
            active_job_id=job_id,
            current_stage=OrchestrationStage.IMPLEMENTING,
            current_generation=1,
            current_candidate_sha=None,
            base_sha=base_sha,
        ),
        source_base=base_sha,
        project_id=project_id,
        change_name=change_name,
    )
