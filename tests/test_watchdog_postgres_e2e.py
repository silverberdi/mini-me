import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.domain.enums import OrchestrationStage, WorktreeCreationState
from minime.domain.models import (
    Job,
    OrchestrationRun,
    OrchestrationStageEvent,
    OrchestrationWorktreeOwnership,
    Project,
    ProjectManagedRepositoryBinding,
)
from minime.services.agent_confinement import process_identity
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.watchdog_service import WatchdogObservationService
from minime.services.worktree_manager import WorktreeManager

DATABASE_URL = os.environ.get("MINIME_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MINIME_TEST_DATABASE_URL must point to the disposable PostgreSQL test database",
)


def test_watchdog_migration_and_postgres_persistence_are_idempotent():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    project_id = f"watchdog-e2e-{uuid4().hex}"
    run_id = f"watchdog-run-{uuid4().hex}"
    settings_before = None
    session = None
    try:
        with engine.connect() as connection:
            database_name = connection.execute(text("select current_database()")).scalar_one()
            assert "test" in database_name.lower(), "Refusing to write outside a test database"
        assert inspect(engine).has_table("watchdog_settings")
        assert inspect(engine).has_table("watchdog_diagnoses")
        assert "affected_component" in {
            column["name"] for column in inspect(engine).get_columns("watchdog_diagnoses")
        }

        session = session_factory()
        uow = PostgresPersistenceUnitOfWork(session)
        settings_before = uow.watchdog.get_settings()
        saved_settings = uow.watchdog.save_settings(
            {
                "provider_id": None,
                "harness_id": None,
                "canonical_model_id": None,
                "inactivity_threshold_minutes": 19,
                "mode": "diagnostic_only",
            }
        )
        uow.commit()
        assert saved_settings["inactivity_threshold_minutes"] == 19
        assert uow.watchdog.get_settings()["inactivity_threshold_minutes"] == 19

        uow.projects.save(
            Project(
                project_id=project_id,
                display_name="Watchdog PostgreSQL E2E",
                repository="test/watchdog-e2e",
            )
        )
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name="watchdog-e2e-change",
            base_sha="base-sha",
            current_candidate_sha="candidate-sha",
            current_generation=3,
        )
        uow.orchestration_runs.save(run)
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            run_id=run_id,
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            event_type="SRE_UNBLOCKER_ATTEMPTED",
            transition_key=f"sre-unblocker:attempt:{run_id}",
            actor="sre_unblocker",
            evidence_references={"trigger": "no_recent_activity"},
        ))
        uow.commit()
        attempt_key = f"sre-unblocker:attempt:{run_id}"
        assert WatchdogObservationService.record_intervention_event(
            uow,
            run,
            event_type="SRE_UNBLOCKER_ATTEMPTED",
            transition_key=attempt_key,
            evidence={"trigger": "no_recent_activity", "action": "inspect"},
        ) is False
        assert WatchdogObservationService.record_intervention_event(
            uow,
            run,
            event_type="SRE_UNBLOCKER_RESOLVED",
            transition_key=f"sre-unblocker:resolved:{run_id}",
            evidence={"observed_result": "recovered"},
        ) is True
        uow.commit()
        intervention_events = [
            event for event in uow.orchestration_stage_events.list_by_run(run_id)
            if event.event_type.startswith("SRE_UNBLOCKER_")
        ]
        assert [event.event_type for event in intervention_events] == [
            "SRE_UNBLOCKER_ATTEMPTED",
            "SRE_UNBLOCKER_RESOLVED",
        ]
        assert intervention_events[0].evidence_references["trigger"] == "no_recent_activity"
        assert "action" not in intervention_events[0].evidence_references

        diagnosis = {
            "project_id": project_id,
            "run_id": run_id,
            "change_name": run.change_name,
            "stage": "IMPLEMENTING",
            "candidate_sha": "candidate-sha",
            "candidate_generation": 3,
            "status": "OBSERVED",
            "root_cause": "no_recent_activity",
            "affected_component": "apply",
            "summary": "No durable activity observed.",
            "evidence": {
                "inactive_seconds": 1200,
                "sre_intervention_transition_key": f"sre-unblocker:attempt:{run_id}",
            },
            "action": None,
            "action_result": {"status": "NOT_ATTEMPTED"},
            "improvement_suggestion": "Review observable stage activity.",
        }
        first = uow.watchdog.save_diagnosis(diagnosis)
        uow.commit()
        second = uow.watchdog.save_diagnosis(diagnosis)
        uow.commit()
        assert first["id"] == second["id"]
        assert second["candidate_sha"] == "candidate-sha"
        assert second["affected_component"] == "apply"
        assert second["source_intervention_transition_key"] == f"sre-unblocker:attempt:{run_id}"
        mismatched_candidate = {**diagnosis, "candidate_sha": "different-candidate"}
        with pytest.raises(ValueError, match="identity changed"):
            uow.watchdog.save_diagnosis(mismatched_candidate)
        assert (
            uow.watchdog.set_suggestion_status(first["id"], "converted")["suggestion_status"]
            == "converted"
        )
        uow.commit()
        assert (
            uow.watchdog.list_diagnoses(project_id=project_id, suggestions_only=True)[0][
                "suggestion_status"
            ]
            == "converted"
        )
    finally:
        if session is not None:
            session.rollback()
            session.execute(
                text("DELETE FROM orchestration_runs WHERE id = :run_id"), {"run_id": run_id}
            )
            session.execute(
                text("DELETE FROM projects WHERE id = :project_id"), {"project_id": project_id}
            )
            if settings_before is not None:
                session.execute(text("DELETE FROM watchdog_settings WHERE settings_id = 'global'"))
                session.execute(
                    text("""INSERT INTO watchdog_settings
                    (settings_id, provider_id, harness_id, canonical_model_id,
                     inactivity_threshold_minutes, mode, updated_at)
                    VALUES ('global', :provider_id, :harness_id, :canonical_model_id,
                            :threshold, :mode, CURRENT_TIMESTAMP)"""),
                    {
                        "provider_id": settings_before["provider_id"],
                        "harness_id": settings_before["harness_id"],
                        "canonical_model_id": settings_before["canonical_model_id"],
                        "threshold": settings_before["inactivity_threshold_minutes"],
                        "mode": settings_before["mode"],
                    },
                )
            session.commit()
            session.close()
        engine.dispose()


def test_scheduler_does_not_diagnose_or_mutate_a_progressing_run(monkeypatch, tmp_path):
    from minime.cli import main as cli_main
    from minime.services import watchdog_service

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    project_id = f"watchdog-progress-{uuid4().hex}"
    run_id = f"watchdog-progress-run-{uuid4().hex}"
    job_id = f"watchdog-progress-job-{uuid4().hex}"
    repository_root = tmp_path / "managed-repo"
    repository_root.mkdir()
    session = session_factory()
    try:
        database_name = session.execute(text("select current_database()")).scalar_one()
        assert database_name.lower().endswith("_test"), "Refusing to execute outside a test database"
        uow = PostgresPersistenceUnitOfWork(session)
        uow.projects.save(Project(
            project_id=project_id,
            display_name="Watchdog progressing-run scheduler E2E",
            repository="watchdog-e2e/progress-fixture",
        ))
        uow.project_managed_repository_bindings.save(ProjectManagedRepositoryBinding(
            project_id=project_id,
            canonical_repository_identity="watchdog-e2e/progress-fixture",
            managed_repository_root=str(repository_root),
            worktree_parent_dir=str(repository_root / ".minime" / "worktrees"),
            default_base_branch="main",
            is_valid=True,
        ))
        now = datetime.now(UTC)
        uow.jobs.save(Job(
            job_id=job_id,
            project_id=project_id,
            change_name="progressing-change",
            implementer_role="codex",
        ))
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name="progressing-change",
            base_sha="a" * 40,
            current_stage=OrchestrationStage.IMPLEMENTING,
            current_candidate_sha="a" * 40,
            current_generation=1,
            active_job_id=job_id,
            is_active=True,
            updated_at=now,
            stop_details={"sentinel": "unchanged"},
        )
        uow.orchestration_runs.save(run)
        uow.orchestration_stage_events.save(OrchestrationStageEvent(
            run_id=run_id,
            from_stage=OrchestrationStage.IMPLEMENTING,
            to_stage=OrchestrationStage.IMPLEMENTING,
            event_type="STAGE_INVOCATION_STARTED",
            evidence_references={"attempt_id": "progressing-attempt"},
            created_at=now - timedelta(seconds=20),
        ))
        uow.commit()
        prior = uow.orchestration_runs.get_by_id(run_id)
        prior_event_count = len(uow.orchestration_stage_events.list_by_run(run_id))
        assert uow.watchdog.list_diagnoses(run_id=run_id, limit=10) == []

        def unexpected_semantic_call(*_args, **_kwargs):
            raise AssertionError("A progressing run must not invoke Watchdog model diagnosis")

        monkeypatch.setattr(
            watchdog_service.WatchdogObservationService,
            "add_semantic_diagnosis",
            unexpected_semantic_call,
        )

        class Wakeup:
            def __init__(self, *_args, **_kwargs):
                pass

            def start(self):
                pass

            def wait(self, *_args, **_kwargs):
                pass

            def stop(self):
                pass

        class Runner:
            @classmethod
            def for_project_profiles(cls, *_args, **_kwargs):
                return cls()

            @staticmethod
            def provider_for_role(role):
                return f"test-{role}"

        class Coordinator:
            def __init__(self, **_kwargs):
                pass

            async def execute_project_request(self, **_kwargs):
                return SimpleNamespace(
                    status="PAUSED",
                    run_id=run_id,
                    current_stage=OrchestrationStage.IMPLEMENTING,
                    message="Progressing-run fixture; no stage dispatch requested.",
                    human_payload=None,
                )

        @contextmanager
        def scheduler_session():
            scheduler_db_session = session_factory()
            try:
                yield scheduler_db_session
            finally:
                scheduler_db_session.close()

        monkeypatch.setattr(
            cli_main,
            "db_manager",
            SimpleNamespace(engine=engine, session=scheduler_session),
        )
        monkeypatch.setattr("minime.services.scheduler_wakeup.SchedulerWakeupBridge", Wakeup)
        monkeypatch.setattr("minime.adapters.github.GitHubAdapter", lambda: object())
        monkeypatch.setattr("minime.services.worktree_manager.WorktreeManager", lambda **_: object())
        monkeypatch.setattr(
            "minime.services.capacity_lifecycle_service.CapacityLifecycleService",
            lambda _uow: object(),
        )
        monkeypatch.setattr(
            "minime.services.agent_runner.CliAgentRunner.for_project_profiles",
            Runner.for_project_profiles,
        )
        monkeypatch.setattr(
            "minime.services.orchestration_coordinator.NativeOrchestrationCoordinator",
            Coordinator,
        )

        cli_main.scheduler_run_cmd(poll_interval=0, max_iterations=1)

        verification_uow = PostgresPersistenceUnitOfWork(session_factory())
        try:
            current = verification_uow.orchestration_runs.get_by_id(run_id)
            assert current.current_stage == prior.current_stage
            assert current.current_generation == prior.current_generation
            assert current.stop_details == prior.stop_details
            assert current.updated_at == prior.updated_at
            assert len(verification_uow.orchestration_stage_events.list_by_run(run_id)) == prior_event_count
            assert verification_uow.watchdog.list_diagnoses(run_id=run_id, limit=10) == []
        finally:
            verification_uow.session.close()
    finally:
        session.rollback()
        session.execute(text("DELETE FROM watchdog_diagnoses WHERE run_id = :run_id"), {"run_id": run_id})
        session.execute(text("DELETE FROM orchestration_stage_events WHERE run_id = :run_id"), {"run_id": run_id})
        session.execute(text("DELETE FROM orchestration_runs WHERE id = :run_id"), {"run_id": run_id})
        session.execute(text("DELETE FROM jobs WHERE id = :job_id"), {"job_id": job_id})
        session.execute(text("DELETE FROM project_managed_repository_bindings WHERE project_id = :project_id"), {"project_id": project_id})
        session.execute(text("DELETE FROM projects WHERE id = :project_id"), {"project_id": project_id})
        session.commit()
        session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_watchdog_recovery_and_ambiguous_escalation_use_postgres_git_and_canonical_coordinator():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    suffix = uuid4().hex
    project_id = f"watchdog-recovery-{suffix}"
    run_ids = [f"watchdog-run-{suffix}-{index}" for index in range(2)]
    job_ids = [f"watchdog-job-{suffix}-{index}" for index in range(2)]
    change_names = [f"watchdog-change-{suffix}-{index}" for index in range(2)]
    session = None
    with tempfile.TemporaryDirectory(prefix="minime-watchdog-pg-e2e-") as temp_root:
        repository_root = Path(temp_root) / "repo"
        repository_root.mkdir()
        remote_identity = "watchdog-e2e/fixture"
        remote_url = "https://github.com/watchdog-e2e/fixture.git"

        def git(cwd: Path, *args: str) -> str:
            result = subprocess.run(
                ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
            )
            return result.stdout.strip()

        git(repository_root, "init", "-b", "main")
        git(repository_root, "config", "user.name", "Watchdog E2E")
        git(repository_root, "config", "user.email", "watchdog-e2e@example.invalid")
        git(repository_root, "remote", "add", "origin", remote_url)
        (repository_root / ".gitignore").write_text(".minime_worktree_ownership.json\n")
        (repository_root / ".minime-managed-project.json").write_text(json.dumps({
            "project_id": project_id,
            "canonical_repository_identity": remote_identity,
        }))
        (repository_root / "candidate.txt").write_text("immutable candidate\n")
        git(repository_root, "add", ".gitignore", ".minime-managed-project.json", "candidate.txt")
        git(repository_root, "commit", "-m", "watchdog recovery fixture")
        candidate_sha = git(repository_root, "rev-parse", "HEAD")

        session = session_factory()
        try:
            database_name = session.execute(text("select current_database()")).scalar_one()
            assert "test" in database_name.lower(), "Refusing to execute against a non-test database"
            uow = PostgresPersistenceUnitOfWork(session)
            uow.projects.save(Project(
                project_id=project_id,
                display_name="Watchdog Recovery PostgreSQL E2E",
                repository=remote_identity,
            ))
            worktree_parent = repository_root / ".minime" / "worktrees"
            uow.project_managed_repository_bindings.save(ProjectManagedRepositoryBinding(
                project_id=project_id,
                canonical_repository_identity=remote_identity,
                managed_repository_root=str(repository_root),
                worktree_parent_dir=str(worktree_parent),
                default_base_branch="main",
                is_valid=True,
            ))
            for index, (run_id, job_id, change_name) in enumerate(zip(run_ids, job_ids, change_names, strict=True)):
                stale_at = datetime.now(UTC) - timedelta(minutes=5)
                uow.jobs.save(Job(
                    job_id=job_id,
                    project_id=project_id,
                    change_name=change_name,
                    implementer_role="codex",
                ))
                uow.commit()
                run = OrchestrationRun(
                    run_id=run_id,
                    project_id=project_id,
                    change_name=change_name,
                    base_sha=candidate_sha,
                    current_stage=OrchestrationStage.IMPLEMENTING,
                    current_candidate_sha=candidate_sha,
                    current_generation=1,
                    active_job_id=job_id,
                    is_active=True,
                    updated_at=stale_at,
                )
                uow.orchestration_runs.save(run)
                branch = f"watchdog-{suffix}-{index}"
                worktree_path = worktree_parent / job_id
                git(repository_root, "worktree", "add", "-b", branch, str(worktree_path), candidate_sha)
                ownership = OrchestrationWorktreeOwnership(
                    project_id=project_id,
                    job_id=job_id,
                    run_id=run_id,
                    change_name=change_name,
                    canonical_worktree_path=str(worktree_path.resolve()),
                    source_repository_identity=remote_identity,
                    source_base_sha=candidate_sha,
                    branch=branch,
                    creation_state=WorktreeCreationState.CREATED,
                )
                uow.orchestration_worktree_ownerships.save(ownership)
                uow.commit()
                manager = WorktreeManager(project_root=repository_root, uow=uow)
                manager._write_ownership_marker(worktree_path, ownership)
                git_dir = Path(git(worktree_path, "rev-parse", "--absolute-git-dir"))
                lock_path = git_dir / "index.lock"
                lock_path.write_text(f"orphan lock {index}\n")

                candidate_identity = await NativeOrchestrationCoordinator(
                    uow_factory=lambda: uow,
                    github_adapter=object(),
                    worktree_manager=manager,
                    agent_runner=object(),
                    watchdog_mechanical_remediation=True,
                )._stage_candidate_identity(run, worktree_path, "APPLY")
                claim_key = f"stage-invocation:{run_id}:APPLY:{candidate_identity['fingerprint']}"
                prior_claim = uow.claims.acquire_or_reacquire(
                    claim_key=claim_key, owner_instance_id=f"abandoned-{index}", lease_seconds=120
                )
                assert prior_claim is not None
                uow.commit()
                session.execute(text(
                    "UPDATE recovery_claims SET lease_expires_at = :expired WHERE claim_key = :key"
                ), {"expired": datetime.now(UTC) - timedelta(minutes=5), "key": claim_key})
                uow.commit()
                current_identity = process_identity()
                old_boot_identity = {
                    **current_identity,
                    "boot_id": f"{current_identity['boot_id']}-previous",
                }
                prior_event = {
                    "attempt_id": f"old-attempt-{index}",
                    "claim_key": claim_key,
                    "candidate": candidate_identity,
                    "coordinator_process": old_boot_identity,
                    "recovery_count": 0,
                }
                uow.orchestration_stage_events.save(OrchestrationStageEvent(
                    run_id=run_id,
                    from_stage=OrchestrationStage.IMPLEMENTING,
                    to_stage=OrchestrationStage.IMPLEMENTING,
                    event_type="STAGE_INVOCATION_STARTED",
                    evidence_references=prior_event,
                    created_at=stale_at,
                ))
                uow.orchestration_stage_events.save(OrchestrationStageEvent(
                    run_id=run_id,
                    from_stage=OrchestrationStage.IMPLEMENTING,
                    to_stage=OrchestrationStage.IMPLEMENTING,
                    event_type="STAGE_INVOCATION_PROCESS_STARTED",
                    evidence_references={
                        "attempt_id": f"old-attempt-{index}",
                        "process_identity": (
                            old_boot_identity if index == 0 else {"status": "UNAVAILABLE"}
                        ),
                    },
                    created_at=stale_at,
                ))
                observation = WatchdogObservationService().observe(
                    run,
                    uow.orchestration_stage_events.list_by_run(run_id),
                    threshold_minutes=1,
                    now=datetime.now(UTC),
                )
                assert observation is not None
                assert observation["candidate_sha"] == candidate_sha
                assert observation["candidate_generation"] == 1
                if index == 1:
                    observation.update({
                        "status": "OBSERVED",
                        "root_cause": "ambiguous_recovery_evidence",
                        "summary": "Proceso y ownership ambiguos; se conserva el worktree.",
                    })
                    uow.watchdog.save_diagnosis({**observation,
                        "project_id": project_id,
                        "run_id": run_id,
                        "change_name": change_name,
                        "stage": "IMPLEMENTING",
                        "candidate_sha": candidate_sha,
                        "candidate_generation": 1,
                        "affected_component": "apply",
                        "action": None,
                        "action_result": {"status": "NOT_ATTEMPTED"},
                    })
                else:
                    assert observation["root_cause"] in {
                        "orphaned_stage_process",
                        "no_recent_activity",
                    }
                    uow.watchdog.save_diagnosis(observation)
                uow.commit()

                coordinator = NativeOrchestrationCoordinator(
                    uow_factory=lambda: uow,
                    github_adapter=object(),
                    worktree_manager=manager,
                    agent_runner=object(),
                    watchdog_mechanical_remediation=True,
                )
                recovery_claim, recovery_evidence = await coordinator._recover_orphaned_stage_index_lock(
                    uow, run, worktree_path, "APPLY"
                )
                if index == 0:
                    assert recovery_claim is not None
                    assert recovery_evidence["candidate_sha"] == candidate_sha
                    assert not lock_path.exists()
                    assert any(
                        event.event_type == "WORKTREE_LOCK_RECOVERED"
                        for event in uow.orchestration_stage_events.list_by_run(run_id)
                    )
                    uow.claims.release_claim(recovery_claim)
                    uow.commit()
                    repeated_claim, repeated_evidence = await coordinator._recover_orphaned_stage_index_lock(
                        uow, run, worktree_path, "APPLY"
                    )
                    assert repeated_claim is None
                    assert repeated_evidence is None
                else:
                    assert recovery_claim is None
                    assert recovery_evidence is None
                    assert lock_path.exists(), "Ambiguous process evidence must preserve the lock"
                    gate = coordinator._escalate_observed_watchdog_stall(
                        uow,
                        run,
                        reason="No se pudo probar la ausencia del proceso del Apply.",
                        evidence={"candidate_sha": candidate_sha},
                    )
                    assert gate and gate["gate"] == "watchdog_escalation"
                    diagnosis = uow.watchdog.get_by_run_stage_generation(run_id, "IMPLEMENTING", 1)
                    assert diagnosis["status"] == "ESCALATED"
                    assert any(
                        event.event_type == "WATCHDOG_ESCALATED_TO_HUMAN"
                        for event in uow.orchestration_stage_events.list_by_run(run_id)
                    )
        finally:
            session.rollback()
            session.execute(text(
                "DELETE FROM watchdog_diagnoses WHERE project_id = :project_id"
            ), {"project_id": project_id})
            session.execute(text(
                "DELETE FROM orchestration_stage_events WHERE run_id LIKE :prefix"
            ), {"prefix": f"watchdog-run-{suffix}-%"})
            session.execute(text(
                "DELETE FROM recovery_claims WHERE claim_key LIKE :prefix"
            ), {"prefix": f"stage-invocation:watchdog-run-{suffix}:%"})
            session.execute(text(
                "DELETE FROM orchestration_worktree_ownerships WHERE project_id = :project_id"
            ), {"project_id": project_id})
            session.execute(text(
                "DELETE FROM orchestration_runs WHERE id LIKE :prefix"
            ), {"prefix": f"watchdog-run-{suffix}-%"})
            session.execute(text("DELETE FROM jobs WHERE id LIKE :prefix"), {"prefix": f"watchdog-job-{suffix}-%"})
            session.execute(text(
                "DELETE FROM project_managed_repository_bindings WHERE project_id = :project_id"
            ), {"project_id": project_id})
            session.execute(text("DELETE FROM projects WHERE id = :project_id"), {"project_id": project_id})
            session.commit()
            session.close()
            engine.dispose()


@pytest.mark.skipif(
    not all(os.environ.get(name) for name in (
        "MINIME_SRE_E2E_PROVIDER_ID",
        "MINIME_SRE_E2E_HARNESS_ID",
        "MINIME_SRE_E2E_MODEL_ID",
    )),
    reason="Set the configured Watchdog provider, harness and model to authorize the real SRE E2E",
)
def test_watchdog_real_configured_role_invocation_is_persisted_in_postgres(tmp_path, monkeypatch):
    from minime.cli import main as cli_main
    from minime.config import load_config, resolve_cli_invocation

    provider_id = os.environ["MINIME_SRE_E2E_PROVIDER_ID"]
    harness_id = os.environ["MINIME_SRE_E2E_HARNESS_ID"]
    model_id = os.environ["MINIME_SRE_E2E_MODEL_ID"]
    config = load_config()
    invocation = resolve_cli_invocation(
        harness_id, "thinking", config=config, model=model_id
    )
    assert invocation.provider == harness_id
    assert invocation.model == model_id

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    suffix = uuid4().hex
    project_id = f"sre-role-e2e-{suffix}"
    run_id = f"sre-role-run-{suffix}"
    job_id = f"sre-role-job-{suffix}"
    change_name = f"sre-role-change-{suffix}"
    repository_root = Path(__file__).resolve().parents[1]
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    before_worktree_status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"], cwd=repository_root, check=True,
        capture_output=True,
    ).stdout
    session = session_factory()
    settings_before = None
    try:
        database_name = session.execute(text("select current_database()")).scalar_one()
        assert database_name.lower().endswith("_test"), "Refusing to invoke a role outside test DB"
        uow = PostgresPersistenceUnitOfWork(session)
        settings_before = uow.watchdog.get_settings()
        selected_settings = uow.watchdog.save_settings({
            "provider_id": provider_id,
            "harness_id": harness_id,
            "canonical_model_id": model_id,
            "inactivity_threshold_minutes": 1,
            "mode": "diagnostic_only",
        })
        assert selected_settings["provider_id"] == provider_id
        uow.projects.save(Project(
            project_id=project_id,
            display_name="SRE real role PostgreSQL E2E",
            repository="test/sre-role-e2e",
        ))
        uow.project_managed_repository_bindings.save(ProjectManagedRepositoryBinding(
            project_id=project_id,
            canonical_repository_identity="test/sre-role-e2e",
            managed_repository_root=str(repository_root),
            worktree_parent_dir=str(repository_root),
            default_base_branch="main",
            is_valid=True,
        ))
        uow.jobs.save(Job(
            job_id=job_id,
            project_id=project_id,
            change_name=change_name,
            implementer_role="codex",
        ))
        original_question = "Should this technical feasibility gate continue?"
        original_options = [
            {"id": "continue", "label": "Continue with mapped fallback"},
            {"id": "wait", "label": "Wait for operator review"},
        ]
        human_payload = {
            "gate": "proposal_feasibility",
            "gate_id": f"sre-gate-{suffix}",
            "question": original_question,
            "options": original_options,
            "blockers": ["Fallback status is under technical review."],
            "task_feasibility": [{"task_id": "1.1", "status": "FEASIBLE_WITH_FALLBACK"}],
        }
        now = datetime.now(UTC)
        run = OrchestrationRun(
            run_id=run_id,
            project_id=project_id,
            change_name=change_name,
            base_sha=candidate_sha,
            current_stage=OrchestrationStage.IMPLEMENTING,
            current_candidate_sha=candidate_sha,
            current_generation=1,
            active_job_id=job_id,
            is_active=True,
            human_gate="NEEDS_HUMAN",
            stop_details={"human_payload": human_payload},
            updated_at=now,
        )
        uow.orchestration_runs.save(run)
        uow.orchestration_worktree_ownerships.save(OrchestrationWorktreeOwnership(
            project_id=project_id,
            job_id=job_id,
            run_id=run_id,
            change_name=change_name,
            canonical_worktree_path=str(repository_root.resolve()),
            source_repository_identity="test/sre-role-e2e",
            source_base_sha=candidate_sha,
            branch=f"sre-role-{suffix[:12]}",
            creation_state=WorktreeCreationState.CREATED,
        ))
        uow.commit()

        class Wakeup:
            def __init__(self, *_args, **_kwargs):
                pass

            def start(self):
                pass

            def wait(self, *_args, **_kwargs):
                pass

            def stop(self):
                pass

        class Runner:
            @classmethod
            def for_project_profiles(cls, *_args, **_kwargs):
                return cls()

            @staticmethod
            def provider_for_role(_role):
                return provider_id

        class Coordinator:
            def __init__(self, **_kwargs):
                pass

            async def execute_project_request(self, **_kwargs):
                return SimpleNamespace(
                    status="PAUSED",
                    run_id=run_id,
                    current_stage=OrchestrationStage.IMPLEMENTING,
                    message="Real SRE provider PostgreSQL fixture.",
                    human_payload=human_payload,
                )

        @contextmanager
        def scheduler_session():
            scheduler_db_session = session_factory()
            try:
                yield scheduler_db_session
            finally:
                scheduler_db_session.close()

        monkeypatch.setattr(
            cli_main, "db_manager", SimpleNamespace(engine=engine, session=scheduler_session)
        )
        monkeypatch.setattr("minime.services.scheduler_wakeup.SchedulerWakeupBridge", Wakeup)
        monkeypatch.setattr("minime.adapters.github.GitHubAdapter", lambda: object())
        monkeypatch.setattr("minime.services.worktree_manager.WorktreeManager", lambda **_: object())
        monkeypatch.setattr(
            "minime.services.capacity_lifecycle_service.CapacityLifecycleService",
            lambda _uow: object(),
        )
        monkeypatch.setattr(
            "minime.services.agent_runner.CliAgentRunner.for_project_profiles",
            Runner.for_project_profiles,
        )
        monkeypatch.setattr(
            "minime.services.orchestration_coordinator.NativeOrchestrationCoordinator",
            Coordinator,
        )

        cli_main.scheduler_run_cmd(poll_interval=0, max_iterations=1)

        verification_uow = PostgresPersistenceUnitOfWork(session_factory())
        try:
            persisted_run = verification_uow.orchestration_runs.get_by_id(run_id)
            persisted_gate = persisted_run.stop_details["human_payload"]
            assert persisted_gate["question"] == original_question
            assert persisted_gate["options"] == original_options
            assert persisted_gate["sre_unblocker_diagnostic"]["status"] == "COMPLETED"
            events = verification_uow.orchestration_stage_events.list_by_run(run_id)
            intervention_events = [
                event for event in events if event.event_type.startswith("SRE_UNBLOCKER_")
            ]
            assert [event.event_type for event in intervention_events] == [
                "SRE_UNBLOCKER_ATTEMPTED",
                "SRE_UNBLOCKER_ESCALATED",
            ]
            assert intervention_events[1].evidence_references["provider_id"] == provider_id
            assert intervention_events[1].evidence_references["harness_id"] == harness_id
            assert intervention_events[1].evidence_references["model_id"] == model_id
            assert intervention_events[1].evidence_references["original_question"] == original_question
            assert intervention_events[1].evidence_references["original_options"] == original_options
        finally:
            verification_uow.session.close()
        after_worktree_status = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z"], cwd=repository_root, check=True,
            capture_output=True,
        )
        assert after_worktree_status.stdout == before_worktree_status
    finally:
        session.rollback()
        session.execute(text("DELETE FROM orchestration_stage_events WHERE run_id = :run_id"),
                        {"run_id": run_id})
        session.execute(text(
            "DELETE FROM orchestration_worktree_ownerships WHERE project_id = :project_id"
        ), {"project_id": project_id})
        session.execute(text("DELETE FROM orchestration_runs WHERE id = :run_id"), {"run_id": run_id})
        session.execute(text("DELETE FROM jobs WHERE id = :job_id"), {"job_id": job_id})
        session.execute(text(
            "DELETE FROM project_managed_repository_bindings WHERE project_id = :project_id"
        ), {"project_id": project_id})
        session.execute(text("DELETE FROM projects WHERE id = :project_id"), {"project_id": project_id})
        if settings_before is not None:
            session.execute(text("DELETE FROM watchdog_settings WHERE settings_id = 'global'"))
            session.execute(text("""INSERT INTO watchdog_settings
                (settings_id, provider_id, harness_id, canonical_model_id,
                 inactivity_threshold_minutes, mode, updated_at)
                VALUES ('global', :provider_id, :harness_id, :canonical_model_id,
                        :threshold, :mode, CURRENT_TIMESTAMP)"""), {
                "provider_id": settings_before["provider_id"],
                "harness_id": settings_before["harness_id"],
                "canonical_model_id": settings_before["canonical_model_id"],
                "threshold": settings_before["inactivity_threshold_minutes"],
                "mode": settings_before["mode"],
            })
        session.commit()
        session.close()
        engine.dispose()
