"""Isolated PostgreSQL proof of CONTINUE reusing a deleted N01 worktree identity."""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from minime.config import CliInvocationProfile
from minime.db.models import Base, JobModel, OrchestrationRunModel
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    ContinuationDecision,
    EventType,
    ExecutionOutcome,
    HumanGate,
    JobStatus,
    OperatorActionStatus,
    OperatorActionType,
    OrchestrationStage,
    OrchestrationStopOutcome,
    ProviderHealthStatus,
    WorktreeCreationState,
)
from minime.domain.models import (
    Event,
    Job,
    JobAttempt,
    OperatorActionRequest,
    OrchestrationRun,
    OrchestrationWorktreeOwnership,
    Project,
    ProviderHealth,
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


def _create_recovery_snapshot(
    repo: Path, change_name: str, branch: str, base_sha: str, job_id: str
) -> str:
    _git(repo, "checkout", "-b", branch, base_sha)
    _git(repo, "fetch", "origin", f"refs/minime/intake/{change_name}")
    _git(repo, "checkout", "FETCH_HEAD", "--", f"openspec/changes/{change_name}")
    _git(repo, "add", f"openspec/changes/{change_name}")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=mini me recovery",
            "-c",
            "user.email=mini-me-recovery@localhost",
            "commit",
            "-m",
            f"mini me recovery snapshot for {job_id}",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return _git(repo, "rev-parse", "HEAD")


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
        recovered_sha = _create_recovery_snapshot(
            managed_root, change_name, recovery_branch, base_sha, job_id
        )
        _git(managed_root, "checkout", "main")
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
        ownership = OrchestrationWorktreeOwnership(
            project_id=project_id,
            job_id=job_id,
            run_id=run_id,
            change_name=change_name,
            canonical_worktree_path=str(worktree_path.resolve()),
            source_repository_identity=binding.canonical_repository_identity,
            source_base_sha=base_sha,
            branch=recovery_branch,
            creation_state=WorktreeCreationState.DELETED,
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
        uow.orchestration_worktree_ownerships.save(ownership)
        uow.job_attempts.save(
            JobAttempt(
                job_id=job_id,
                attempt_number=1,
                executor_role="codex",
                model_identity="codex",
                normalized_outcome=ExecutionOutcome.ENVIRONMENT_UNAVAILABLE,
            )
        )
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

            async def run(self, worktree_path, prompt_context, timeout_seconds):
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

        persisted_run = uow.orchestration_runs.get_by_id(run_id)
        persisted_job = uow.jobs.get_by_id(job_id)
        assert persisted_run.run_id == run_id and persisted_run.active_job_id == job_id
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
        assert recording_runner.result is not None
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
        assert not worktree_path.exists()

        # A remote-only main advance must block a later reconstruction even when the
        # managed checkout's local `main` ref has not moved.
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

        manager = WorktreeManager(managed_root, uow)
        with pytest.raises(RuntimeError, match="canonical remote base branch advanced"):
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
