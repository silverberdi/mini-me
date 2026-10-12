"""Isolated PostgreSQL proof of CONTINUE reusing a deleted N01 worktree identity."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from minime.config import CliInvocationProfile
from minime.db.models import Base, DurableSagaModel, EventModel, JobModel, OrchestrationRunModel
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    ContinuationDecision,
    EventType,
    ExecutionOutcome,
    ExternalOutcome,
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
