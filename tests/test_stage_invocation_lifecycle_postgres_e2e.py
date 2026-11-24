"""PostgreSQL integration proof for real coordinator stage claims (mock-free dispatch boundary)."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, text, update
from sqlalchemy.orm import sessionmaker
from tests.conftest import setup_managed_repository_fixture

from minime.db.models import ProviderHealthModel, RecoveryClaimModel
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import (
    OrchestrationStage,
    ProviderHealthStatus,
    ProviderResultClass,
)
from minime.domain.models import (
    OrchestrationRun,
    OrchestrationStageEvent,
    Project,
    ProviderHealth,
    utc_now,
)
from minime.services import agent_runner as agent_runner_module
from minime.services import orchestration_coordinator as coordinator_module
from minime.services.agent_confinement import process_identity
from minime.services.agent_runner import CapacityExhaustedError, CliAgentRunner, ResolvedWorkflow
from minime.services.capacity_lifecycle_service import CapacityLifecycleService
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeManager

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["SYNC", "ARCHIVE"])
async def test_postgres_doc_closing_recovers_owned_worktree_before_fingerprinting(
    tmp_path, monkeypatch, stage,
):
    """Use the disposable PostgreSQL DB to prove DOC_CLOSING ownership and fenced reset."""
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, run_id = str(uuid4()), str(uuid4())
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    repo = tmp_path / "managed"
    path = None
    try:
        with engine.connect() as connection:
            assert connection.execute(text("select current_database()")).scalar_one() == "minime_test"
        uow = PostgresPersistenceUnitOfWork(session)
        project = Project(
            project_id=project_id,
            display_name="DOC_CLOSING recovery integration",
            repository="org/doc-closing-recovery-test",
        )
        uow.projects.save(project)
        uow.flush()
        repo.mkdir(parents=True, exist_ok=True)
        (repo / ".gitignore").write_text("node_modules\n", encoding="utf-8")
        setup_managed_repository_fixture(
            uow, project_id, repo, repo / ".minime" / "worktrees",
            canonical_repository_identity="github.com/org/doc-closing-recovery-test",
            local_remote=False,
        )
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name="issue-517-worktree-recovery-test-isolation",
            base_sha="main",
            current_stage=OrchestrationStage.DOC_CLOSING,
        )
        uow.orchestration_runs.save(run)
        uow.commit()

        manager = WorktreeManager(repo, uow=uow)
        original_git = manager._git

        async def no_remote_fetch(args, **kwargs):
            if args[:2] == ["fetch", "origin"]:
                raise RuntimeError("network disabled in PostgreSQL recovery test")
            return await original_git(args, **kwargs)

        manager._git = no_remote_fetch
        info = await manager.create_documentation_worktree(
            project_id=project_id,
            issue_number=517,
            issue_title="DOC Closing Recovery Integration",
            change_name=run.change_name,
            run_id=run_id,
        )
        path = info.path
        owner = uow.orchestration_worktree_ownerships.get_by_canonical_path(str(path.resolve()))
        assert owner is not None and owner.run_id == run_id

        dirty_file = path / "openspec" / "specs" / "recovery" / "spec.md"
        dirty_file.parent.mkdir(parents=True)
        dirty_file.write_text("uncommitted sync effect\n", encoding="utf-8")
        ignored_file = path / "node_modules" / "retained-cache" / "entry"
        ignored_file.parent.mkdir(parents=True)
        ignored_file.write_text("keep ignored dependencies\n", encoding="utf-8")
        coordinator = NativeOrchestrationCoordinator(
            uow_factory=lambda: uow,
            github_adapter=object(),
            worktree_manager=manager,
            agent_runner=object(),
        )
        candidate = await coordinator._stage_candidate_identity(run, path, stage)
        prior_claim = uow.claims.acquire_or_reacquire(
            claim_key=f"stage-invocation:{run_id}:{stage}:{candidate['fingerprint']}",
            owner_instance_id="previous-doc-close-worker",
            lease_seconds=120,
        )
        assert prior_claim is not None
        prior_claim_key = prior_claim.claim_key
        prior_fence = prior_claim.fence_token
        old_identity = {
            "status": "AVAILABLE", "host": socket.gethostname(), "boot_id": "previous-boot",
            "pid": 2147480000, "pgid": 2147480000, "start_marker": "previous",
        }
        current_identity = {**old_identity, "boot_id": "current-boot", "pid": os.getpid()}
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            run_id=run_id,
            from_stage=OrchestrationStage.DOC_CLOSING,
            to_stage=OrchestrationStage.DOC_CLOSING,
            event_type="STAGE_INVOCATION_STARTED",
            evidence_references={
                "attempt_id": "abandoned-archive",
                "claim_key": prior_claim_key,
                "fence_token": prior_fence,
                "candidate": candidate,
                "coordinator_process": old_identity,
                "recovery_count": 0,
            },
        ))
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            run_id=run_id,
            from_stage=OrchestrationStage.DOC_CLOSING,
            to_stage=OrchestrationStage.DOC_CLOSING,
            event_type="STAGE_INVOCATION_PROCESS_STARTED",
            evidence_references={
                "attempt_id": "abandoned-archive",
                "claim_key": prior_claim_key,
                "process_identity": old_identity,
            },
        ))
        uow.commit()
        session.execute(
            update(RecoveryClaimModel)
            .where(RecoveryClaimModel.claim_key == prior_claim_key)
            .values(lease_expires_at=utc_now() - timedelta(seconds=1))
        )
        session.commit()
        monkeypatch.setattr(coordinator_module, "process_identity", lambda: current_identity)

        recovered = await coordinator._begin_stage_invocation(uow, run, path, stage)
        assert recovered is not None
        assert recovered.attempt_id != "abandoned-archive"
        assert uow.claims.get_by_key(prior_claim_key).fence_token > prior_fence
        assert recovered.claim.claim_key != prior_claim_key
        assert not dirty_file.exists()
        assert ignored_file.read_text(encoding="utf-8") == "keep ignored dependencies\n"
        assert coordinator._doc_archive_reset_requires_sync_replay(
            uow.orchestration_stage_events.list_by_run(run_id), run_id, path
        ) is (stage == "ARCHIVE")

        events = uow.orchestration_stage_events.list_by_run(run_id)
        abandoned = [e for e in events if e.event_type == "STAGE_INVOCATION_ABANDONED"]
        starts = [e for e in events if e.event_type == "STAGE_INVOCATION_STARTED"]
        assert len(abandoned) == 1 and len(starts) == 2
        assert abandoned[0].evidence_references["worktree_reset"] is True
        assert abandoned[0].evidence_references["recovery_proof"] == "previous_boot"
        assert starts[-1].evidence_references["candidate"]["candidate_fingerprint"] == recovered.candidate[
            "candidate_fingerprint"
        ]
        assert uow.claims.validate_cas(
            recovered.claim.claim_key,
            recovered.claim.owner_instance_id,
            recovered.claim.fence_token,
        )
    finally:
        session.rollback()
        if path is not None and path.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=repo, check=False, capture_output=True,
            )
        session.execute(
            text("delete from recovery_claims where claim_key like :pattern"),
            {"pattern": f"stage-invocation:{run_id}:%"},
        )
        session.execute(text("delete from orchestration_runs where id = :id"), {"id": run_id})
        session.execute(text("delete from projects where id = :id"), {"id": project_id})
        session.commit()
        session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_postgres_legacy_doc_worktree_adoption_is_evidence_bound(tmp_path):
    """Adopt only an exact legacy Git worktree and preserve one without evidence."""
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id = str(uuid4())
    run_ids = [str(uuid4()), str(uuid4())]
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    repo = tmp_path / "managed"
    paths: list[Path] = []
    try:
        with engine.connect() as connection:
            assert connection.execute(text("select current_database()")).scalar_one() == "minime_test"
        uow = PostgresPersistenceUnitOfWork(session)
        project = Project(
            project_id=project_id,
            display_name="Legacy DOC_CLOSING adoption integration",
            repository="org/legacy-doc-adoption-test",
        )
        uow.projects.save(project)
        uow.flush()
        setup_managed_repository_fixture(
            uow, project_id, repo, repo / ".minime" / "worktrees",
            canonical_repository_identity="github.com/org/legacy-doc-adoption-test",
            local_remote=False,
        )
        runs = [
            OrchestrationRun(
                run_id=run_id,
                project_id=project_id,
                change_name=f"issue-517-legacy-adoption-{index}",
                base_sha="main",
                current_stage=OrchestrationStage.DOC_CLOSING,
            )
            for index, run_id in enumerate(run_ids)
        ]
        for run in runs:
            uow.orchestration_runs.save(run)
        uow.commit()

        manager = WorktreeManager(repo, uow=uow)
        original_git = manager._git

        async def no_remote_fetch(args, **kwargs):
            if args[:2] == ["fetch", "origin"]:
                raise RuntimeError("network disabled in PostgreSQL adoption test")
            return await original_git(args, **kwargs)

        manager._git = no_remote_fetch

        def create_legacy_path(issue_number: int, title: str) -> tuple[str, Path]:
            branch = manager.format_documentation_branch_name(issue_number, title)
            path = repo / ".minime" / "worktrees" / branch
            return branch, path

        branch, path = create_legacy_path(518, "Legacy Adoption With Evidence")
        paths.append(path)
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(path), "main"],
            cwd=repo, check=True, capture_output=True,
        )
        head = (await manager._git(["rev-parse", "HEAD"], cwd=path)).strip()
        run = runs[0]
        candidate = {
            "run_id": run.run_id,
            "stage": "SYNC",
            "worktree": str(path.resolve()),
            "branch": branch,
            "generation": int(run.current_generation or 0),
            "candidate_sha": head,
        }
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            run_id=run.run_id,
            from_stage=OrchestrationStage.DOC_CLOSING,
            to_stage=OrchestrationStage.DOC_CLOSING,
            event_type="STAGE_INVOCATION_STARTED",
            evidence_references={
                "attempt_id": "legacy-doc-adoption",
                "claim_key": f"stage-invocation:{run.run_id}:SYNC:legacy-fingerprint",
                "candidate": candidate,
            },
        ))
        uow.commit()
        adopted = await manager.create_documentation_worktree(
            project_id=project_id,
            issue_number=518,
            issue_title="Legacy Adoption With Evidence",
            change_name=run.change_name,
            run_id=run.run_id,
        )
        owner = uow.orchestration_worktree_ownerships.get_by_canonical_path(
            str(adopted.path.resolve())
        )
        assert owner is not None and owner.run_id == run.run_id
        assert (adopted.path / ".minime_worktree_ownership.json").is_file()

        unproven_run = runs[1]
        unproven_branch, unproven_path = create_legacy_path(
            519, "Legacy Worktree Without Evidence"
        )
        paths.append(unproven_path)
        subprocess.run(
            ["git", "worktree", "add", "-b", unproven_branch, str(unproven_path), "main"],
            cwd=repo, check=True, capture_output=True,
        )
        preserved = unproven_path / "preserve.txt"
        preserved.write_text("fail closed\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="identity is absent or ambiguous"):
            await manager.create_documentation_worktree(
                project_id=project_id,
                issue_number=519,
                issue_title="Legacy Worktree Without Evidence",
                change_name=unproven_run.change_name,
                run_id=unproven_run.run_id,
            )
        assert preserved.read_text(encoding="utf-8") == "fail closed\n"
        assert uow.orchestration_worktree_ownerships.get_by_canonical_path(
            str(unproven_path.resolve())
        ) is None
    finally:
        session.rollback()
        for path in reversed(paths):
            if path.exists():
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(path)],
                    cwd=repo, check=False, capture_output=True,
                )
        for run_id in run_ids:
            session.execute(
                text("delete from orchestration_runs where id = :id"), {"id": run_id}
            )
        session.execute(text("delete from projects where id = :id"), {"id": project_id})
        session.commit()
        session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_postgres_stage_claim_suppresses_concurrent_and_completed_verify_dispatch(tmp_path):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, run_id = str(uuid4()), str(uuid4())
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    first_session = second_session = None
    try:
        with engine.connect() as connection:
            name = connection.execute(text("select current_database()")).scalar_one()
            assert "test" in name.lower(), "Refusing to write outside a test database"
        first_session, second_session = sessions(), sessions()
        first_uow = PostgresPersistenceUnitOfWork(first_session)
        second_uow = PostgresPersistenceUnitOfWork(second_session)
        first_uow.projects.save(Project(
            project_id=project_id,
            display_name="Stage invocation integration",
            repository="org/stage-invocation-test",
        ))
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name="stage-invocation-test",
            base_sha="main",
            current_stage=OrchestrationStage.VERIFYING,
        )
        first_uow.orchestration_runs.save(run)
        first_uow.commit()

        candidate = tmp_path / "candidate"
        candidate.mkdir()
        subprocess.run(["git", "init", "-q", str(candidate)], check=True)
        subprocess.run(["git", "-C", str(candidate), "config", "user.name", "integration"], check=True)
        subprocess.run(["git", "-C", str(candidate), "config", "user.email", "integration@example.com"], check=True)
        (candidate / "README.md").write_text("candidate\n")
        subprocess.run(["git", "-C", str(candidate), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(candidate), "commit", "-qm", "candidate"], check=True)

        coordinator = NativeOrchestrationCoordinator(
            uow_factory=lambda: first_uow,
            github_adapter=object(),
            worktree_manager=object(),
            agent_runner=object(),
        )
        first = await coordinator._begin_stage_invocation(
            first_uow, run, candidate, "VERIFY"
        )
        concurrent = await coordinator._begin_stage_invocation(
            second_uow, run, candidate, "VERIFY"
        )
        assert first is not None
        assert concurrent is None

        initial_claim = first_uow.claims.get_by_key(first.claim_key)
        coordinator._claim_heartbeat_interval_seconds = 0.01
        observed_heartbeat = []

        async def observe_renewal():
            await asyncio.sleep(0.06)
            with sessions() as observer:
                observed_heartbeat.append(
                    PostgresPersistenceUnitOfWork(observer)
                    .claims.get_by_key(first.claim_key).heartbeat_at
                )

        await coordinator._run_claimed(first_uow, first.claim, observe_renewal)
        assert observed_heartbeat[0] >= initial_claim.heartbeat_at

        await coordinator._finish_stage_invocation(
            first_uow, run, first, "COMPLETE", {"summary": "observed native result"}
        )
        reentry = await coordinator._begin_stage_invocation(
            first_uow, run, candidate, "VERIFY"
        )
        assert reentry is None
        events = first_uow.orchestration_stage_events.list_by_run(run_id)
        assert [event.event_type for event in events] == [
            "STAGE_INVOCATION_STARTED", "STAGE_INVOCATION_COMPLETED"
        ]
    finally:
        if first_session is not None:
            first_session.execute(text("delete from orchestration_runs where id = :id"), {"id": run_id})
            first_session.execute(text("delete from projects where id = :id"), {"id": project_id})
            first_session.commit()
            first_session.close()
        if second_session is not None:
            second_session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_postgres_expired_invocation_recovers_once_only_after_processes_are_gone(
    tmp_path, monkeypatch,
):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, run_id = str(uuid4()), str(uuid4())
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    sessions = []

    def exited_process_identity():
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
        )
        identity = process_identity(process.pid)
        process.terminate()
        process.wait(timeout=5)
        if identity.get("status") != "AVAILABLE":
            # Some managed runners isolate /proc, so the child identity cannot
            # be observed even though its exit is observable. Keep the test's
            # recovery proof deterministic without weakening production logic.
            identity = {
                "status": "AVAILABLE",
                "host": socket.gethostname(),
                # Use an impossible PID because this runner may expose a
                # different PID namespace to the test process.
                "pid": 2_000_000_000,
                "pgid": 2_000_000_000,
                "start_marker": f"unobserved-{process.pid}",
            }
        return identity

    def expire_claim(session, claim_key):
        session.execute(
            update(RecoveryClaimModel)
            .where(RecoveryClaimModel.claim_key == claim_key)
            .values(lease_expires_at=utc_now() - timedelta(seconds=1))
        )
        session.commit()

    try:
        with engine.connect() as connection:
            assert connection.execute(text("select current_database()")).scalar_one().endswith("test")

        candidate = tmp_path / "candidate"
        candidate.mkdir()
        subprocess.run(["git", "init", "-q", str(candidate)], check=True)
        subprocess.run(["git", "-C", str(candidate), "config", "user.name", "integration"], check=True)
        subprocess.run(["git", "-C", str(candidate), "config", "user.email", "integration@example.com"], check=True)
        (candidate / "README.md").write_text("same candidate\n")
        subprocess.run(["git", "-C", str(candidate), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(candidate), "commit", "-qm", "candidate"], check=True)

        current_boot_id = process_identity().get("boot_id") or "unavailable-runtime-boot"
        prior_boot_id = f"previous-{current_boot_id}"
        coordinator_identity = {**exited_process_identity(), "boot_id": prior_boot_id}
        first_workflow_identity = {**exited_process_identity(), "boot_id": prior_boot_id}
        identities = [coordinator_identity]
        real_identity = coordinator_module.process_identity

        def coordinator_identity_for_attempt(pid=None):
            if pid is None and identities:
                return identities.pop(0)
            identity = real_identity(pid)
            if pid is None and identity.get("status") != "AVAILABLE":
                return {
                    "status": "AVAILABLE",
                    "host": socket.gethostname(),
                    "boot_id": current_boot_id,
                    "pid": os.getpid(),
                    "pgid": os.getpgid(os.getpid()),
                    "start_marker": "current-process-unobserved",
                }
            return identity

        monkeypatch.setattr(coordinator_module, "process_identity", coordinator_identity_for_attempt)
        coordinator = NativeOrchestrationCoordinator(
            uow_factory=lambda: None,
            github_adapter=object(),
            worktree_manager=object(),
            agent_runner=object(),
        )

        first_session = session_factory()
        sessions.append(first_session)
        first_uow = PostgresPersistenceUnitOfWork(first_session)
        first_uow.projects.save(Project(
            project_id=project_id,
            display_name="Stage invocation recovery integration",
            repository="org/stage-invocation-recovery-test",
        ))
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name="stage-invocation-recovery-test",
            base_sha="main",
            current_stage=OrchestrationStage.VERIFYING,
        )
        first_uow.orchestration_runs.save(run)
        first_uow.commit()

        first = await coordinator._begin_stage_invocation(
            first_uow, run, candidate, "VERIFY"
        )
        assert first is not None
        coordinator._observe_stage_process(first_uow, run, first)(first_workflow_identity)
        expire_claim(first_session, first.claim_key)

        recovery_session = session_factory()
        sessions.append(recovery_session)
        recovery_uow = PostgresPersistenceUnitOfWork(recovery_session)
        recovered = await coordinator._begin_stage_invocation(
            recovery_uow, run, candidate, "VERIFY"
        )
        assert recovered is not None
        assert recovered.attempt_id != first.attempt_id
        assert recovered.claim.fence_token > first.claim.fence_token
        assert recovered.recovery_count == 1
        with pytest.raises(RuntimeError, match="stale fence"):
            await coordinator._finish_stage_invocation(
                first_uow, run, first, "COMPLETE", {"summary": "stale worker"}
            )

        second_workflow_identity = exited_process_identity()
        coordinator._observe_stage_process(recovery_uow, run, recovered)(second_workflow_identity)
        expire_claim(recovery_session, recovered.claim_key)

        final_session = session_factory()
        sessions.append(final_session)
        final_uow = PostgresPersistenceUnitOfWork(final_session)
        second_recovery = await coordinator._begin_stage_invocation(
            final_uow, run, candidate, "VERIFY"
        )
        assert second_recovery is None
        events = final_uow.orchestration_stage_events.list_by_run(run_id)
        assert [event.event_type for event in events].count("STAGE_INVOCATION_ABANDONED") == 1
        assert [event.event_type for event in events].count("STAGE_INVOCATION_STARTED") == 2
        abandoned = next(
            event for event in events if event.event_type == "STAGE_INVOCATION_ABANDONED"
        )
        assert abandoned.evidence_references["recovery_proof"] == "previous_boot"
        assert (
            abandoned.evidence_references["previous_coordinator_process"]["boot_id"]
            == prior_boot_id
        )
        assert all(
            event.evidence_references["candidate"] == first.candidate
            for event in events
            if event.event_type in {"STAGE_INVOCATION_STARTED", "STAGE_INVOCATION_ABANDONED"}
        )
    finally:
        cleanup = session_factory()
        try:
            cleanup.execute(
                text("delete from recovery_claims where claim_key like :key"),
                {"key": f"stage-invocation:{run_id}:VERIFY:%"},
            )
            cleanup.execute(text("delete from orchestration_runs where id = :id"), {"id": run_id})
            cleanup.execute(text("delete from projects where id = :id"), {"id": project_id})
            cleanup.commit()
        finally:
            cleanup.close()
            for session in sessions:
                session.close()
            engine.dispose()


@pytest.mark.asyncio
async def test_postgres_apply_preflight_failure_is_terminal_and_recoverable_once(
    tmp_path, monkeypatch,
):
    """Exercise real Apply dispatch preflight without launching a paid provider process."""
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    project_id, run_id = str(uuid4()), str(uuid4())
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = None
    launched_processes = []
    previous_health = None
    real_create_subprocess_exec = agent_runner_module.asyncio.create_subprocess_exec

    async def record_process_launch(*args, **kwargs):
        if args and args[0] == "git":
            return await real_create_subprocess_exec(*args, **kwargs)
        launched_processes.append(True)
        raise AssertionError("Capacity preflight must stop before process creation")

    try:
        with engine.connect() as connection:
            assert connection.execute(text("select current_database()")).scalar_one() == "minime_test"

        session = sessions()
        uow = PostgresPersistenceUnitOfWork(session)
        previous_health = {
            provider: uow.provider_health.get_by_provider(provider)
            for provider in ("codex", "antigravity")
        }
        project = Project(
            project_id=project_id,
            display_name="Apply preflight recovery integration",
            repository="org/apply-preflight-test",
            implementer="codex",
            reviewer="antigravity",
        )
        run = OrchestrationRun(
            run_id=run_id, project_id=project_id,
            change_name="apply-preflight-test", base_sha="main",
            current_stage=OrchestrationStage.IMPLEMENTING,
        )
        uow.projects.save(project)
        uow.orchestration_runs.save(run)
        uow.provider_health.save(ProviderHealth(
            provider="codex", status=ProviderHealthStatus.EXHAUSTED,
            last_result_class=ProviderResultClass.QUOTA_LIMIT,
            consecutive_failures=1, updated_at=utc_now(),
        ))
        uow.provider_health.save(ProviderHealth(
            provider="antigravity", status=ProviderHealthStatus.AVAILABLE,
            last_result_class=ProviderResultClass.SUCCESS,
            last_success_at=utc_now(), updated_at=utc_now(),
        ))
        uow.commit()

        candidate = tmp_path / "apply-candidate"
        candidate.mkdir()
        subprocess.run(["git", "init", "-q", str(candidate)], check=True)
        subprocess.run(["git", "-C", str(candidate), "config", "user.name", "integration"], check=True)
        subprocess.run(["git", "-C", str(candidate), "config", "user.email", "integration@example.com"], check=True)
        change_dir = candidate / "openspec" / "changes" / run.change_name
        change_dir.mkdir(parents=True)
        (change_dir / "tasks.md").write_text("- [ ] 1.1 Apply task\n")
        (candidate / "README.md").write_text("candidate\n")
        subprocess.run(["git", "-C", str(candidate), "add", "."], check=True)
        subprocess.run(["git", "-C", str(candidate), "commit", "-qm", "candidate"], check=True)

        runner = CliAgentRunner(capacity_service=CapacityLifecycleService(uow))
        runner.resolve_workflow = lambda **_kwargs: ResolvedWorkflow(
            provider="codex", operation="apply", workflow_name="apply",
            workflow_path=".agents/workflows/openspec-apply.md",
            workflow_sha256="workflow-sha", change_name=run.change_name,
            dispatch_command="openspec apply apply-preflight-test",
        )
        coordinator = NativeOrchestrationCoordinator(
            uow_factory=lambda: uow, github_adapter=object(),
            worktree_manager=object(), agent_runner=runner,
        )
        monkeypatch.setattr(agent_runner_module.asyncio, "create_subprocess_exec", record_process_launch)

        first = await coordinator._begin_stage_invocation(uow, run, candidate, "APPLY")
        assert first is not None
        with pytest.raises(CapacityExhaustedError) as first_failure:
            await coordinator._run_claimed(
                uow, first.claim,
                lambda: coordinator._run_apply(
                    candidate, "codex", run.change_name,
                    project_id=project_id, run_id=run_id,
                    process_start_observer=coordinator._observe_stage_process(uow, run, first),
                ),
            )
        closed = await coordinator._close_preflight_failed_invocation(
            uow, run, first, first_failure.value,
        )
        assert closed is True
        assert launched_processes == []
        claim = uow.claims.get_by_key(first.claim_key)
        assert claim is None or not claim.is_active

        retry = await coordinator._begin_stage_invocation(uow, run, candidate, "APPLY")
        assert retry is not None
        assert retry.recovery_count == 1
        assert retry.recovered_from_attempt_id == first.attempt_id
        with pytest.raises(CapacityExhaustedError) as second_failure:
            await coordinator._run_claimed(
                uow, retry.claim,
                lambda: coordinator._run_apply(
                    candidate, "codex", run.change_name,
                    project_id=project_id, run_id=run_id,
                    process_start_observer=coordinator._observe_stage_process(uow, run, retry),
                ),
            )
        assert await coordinator._close_preflight_failed_invocation(
            uow, run, retry, second_failure.value
        )
        assert await coordinator._begin_stage_invocation(uow, run, candidate, "APPLY") is None

        events = uow.orchestration_stage_events.list_by_run(run_id)
        assert [event.event_type for event in events] == [
            "STAGE_INVOCATION_STARTED", "STAGE_INVOCATION_FAILED",
            "STAGE_INVOCATION_STARTED", "STAGE_INVOCATION_FAILED",
        ]
        for event in events:
            evidence = event.evidence_references
            assert evidence["candidate"] == first.candidate
            assert evidence["claim_key"] == first.claim_key
        assert events[1].evidence_references["result"]["preflight_failure_proven"] is True
        assert events[2].evidence_references["recovered_from_attempt_id"] == first.attempt_id
        assert all(event.from_stage == event.to_stage == OrchestrationStage.IMPLEMENTING for event in events)
    finally:
        if session is not None:
            if previous_health is not None:
                for provider, health in previous_health.items():
                    if health is None:
                        session.execute(
                            delete(ProviderHealthModel).where(
                                ProviderHealthModel.provider == provider
                            )
                        )
                        continue
                    session.execute(
                        update(ProviderHealthModel)
                        .where(ProviderHealthModel.provider == provider)
                        .values(
                            id=health.health_id,
                            model=health.model,
                            status=health.status.value,
                            consecutive_failures=health.consecutive_failures,
                            last_probe_at=health.last_probe_at,
                            consecutive_probe_failures=health.consecutive_probe_failures,
                            probe_window_started_at=health.probe_window_started_at,
                            probe_count_in_window=health.probe_count_in_window,
                            last_result_class=(
                                health.last_result_class.value
                                if health.last_result_class else None
                            ),
                            last_error_summary=health.last_error_summary,
                            last_success_at=health.last_success_at,
                            last_failure_at=health.last_failure_at,
                            updated_at=health.updated_at,
                        )
                    )
            session.execute(
                text("delete from recovery_claims where claim_key like :key"),
                {"key": f"stage-invocation:{run_id}:APPLY:%"},
            )
            session.execute(text("delete from orchestration_runs where id = :id"), {"id": run_id})
            session.execute(text("delete from projects where id = :id"), {"id": project_id})
            session.commit()
            session.close()
        engine.dispose()
