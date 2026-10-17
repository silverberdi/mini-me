"""Isolated PostgreSQL proof for the post-READY intake publication authority."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from minime.db.models import Base
from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import EXPECTED_ALEMBIC_HEAD
from minime.domain.enums import (
    ChangeStatus,
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    ExternalReasonCode,
    IntakeWorkspaceCreationState,
    IntakeWorkspacePublicationState,
    ProviderHealthStatus,
    ReadinessState,
    RetrySafety,
    SagaStatus,
    SagaType,
    WorkItemStatus,
)
from minime.domain.exceptions import StaleClaimError
from minime.domain.models import (
    BacklogItem,
    Change,
    DurableSaga,
    ExternalActionResult,
    IntakeWorkspaceOwnership,
    OrchestrationExternalAction,
    Project,
    ProjectBinding,
    ProjectManagedRepositoryBinding,
    ProviderHealth,
    generate_uuid,
)
from minime.services.intake_service import IntakeService
from minime.services.recovery_convergence_service import RecoveryConvergenceService
from minime.services.saga_engine import SagaEngine
from minime.services.worktree_manager import WorktreeManager


def _admin_url() -> URL:
    configured = os.environ.get("MINIME_TEST_ADMIN_DATABASE_URL")
    raw = configured or "postgresql+psycopg://silveriobernal@localhost:54333/postgres"
    url = make_url(raw)
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Post-READY saga PostgreSQL tests require a local isolated server.")
    return url


@pytest.fixture
def isolated_pg_session_factory():
    """Create a uniquely named throwaway database; never reuse an app/production database."""
    admin_url = _admin_url()
    admin_engine = create_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    database_name = f"minime_postready_{uuid.uuid4().hex[:12]}"
    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    test_engine = create_engine(admin_url.set(database=database_name), pool_pre_ping=True)
    Base.metadata.create_all(test_engine)
    with test_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(64) PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            f"INSERT INTO alembic_version (version_num) VALUES ('{EXPECTED_ALEMBIC_HEAD}')"
        )
    try:
        yield sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    finally:
        test_engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": database_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE "{database_name}"')
        admin_engine.dispose()


def _seed_post_ready_dispatch(
    session: Session,
    *,
    saga_status: SagaStatus = SagaStatus.COMPLETED,
    phase: str = "READY",
    action_type: ExternalActionType = ExternalActionType.INTAKE_ARTIFACT_PUBLISH,
    published: bool = True,
):
    project_id = f"postready-{uuid.uuid4().hex[:10]}"
    change_name = "operational-blocker-visibility"
    item_key = "item-n01"
    old_base = "a" * 40
    old_published = "b" * 40
    new_base = "c" * 40
    repository_identity = "silverberdi/mini-me"
    saga_id = generate_uuid()
    action_key = f"intake_main_advance_publish:{project_id}:{change_name}:{new_base}"
    fingerprint = hashlib.sha256(f"{old_base}:{old_published}:{new_base}".encode()).hexdigest()
    uow = PostgresPersistenceUnitOfWork(session)
    project = Project(
        project_id=project_id,
        display_name="Post-ready test",
        repository=repository_identity,
        base_branch="main",
    )
    uow.projects.save(project)
    uow.project_managed_repository_bindings.save(
        ProjectManagedRepositoryBinding(
            project_id=project_id,
            canonical_repository_identity=repository_identity,
            managed_repository_root="/tmp/managed",
            worktree_parent_dir="/tmp/worktrees",
            remote_name="origin",
            is_valid=True,
            mismatch_reasons=[],
        )
    )
    saga = DurableSaga(
        id=saga_id,
        saga_type=SagaType.INTAKE,
        project_id=project_id,
        work_item_key=item_key,
        change_name=change_name,
        current_phase=phase,
        status=saga_status,
    )
    uow.durable_sagas.save(saga)
    ownership = IntakeWorkspaceOwnership(
        workspace_id=generate_uuid(),
        project_id=project_id,
        item_key=item_key,
        saga_id=saga_id,
        change_name=change_name,
        canonical_workspace_path=f"/tmp/intake/{saga_id}",
        canonical_repository_identity=repository_identity,
        base_sha=old_base,
        head_sha=old_published if published else None,
        creation_state=IntakeWorkspaceCreationState.ACTIVE,
        publication_state=(
            IntakeWorkspacePublicationState.PUBLISHED
            if published
            else IntakeWorkspacePublicationState.UNPUBLISHED
        ),
        published_ref=f"refs/minime/intake/{change_name}" if published else None,
        published_sha=old_published if published else None,
    )
    uow.intake_workspace_ownerships.save(ownership)
    action = OrchestrationExternalAction(
        action_id=generate_uuid(),
        saga_id=saga_id,
        action_key=action_key,
        action_type=action_type,
        status=ExternalActionStatus.RESERVED,
        target_identity=change_name,
        request_fingerprint=fingerprint,
        generation=1,
    )
    uow.orchestration_external_actions.reserve(action)
    session.commit()
    claim = RecoveryConvergenceService(uow, owner_instance_id=f"owner-{project_id}").acquire_claim(
        f"intake:{project_id}:{item_key}", lease_seconds=60
    )
    assert claim is not None
    return uow, saga, ownership, action, claim, action_key, fingerprint


def test_completed_ready_saga_allows_only_fenced_post_ready_publication_dispatch(
    isolated_pg_session_factory,
):
    with isolated_pg_session_factory() as session:
        uow, saga, ownership, action, claim, action_key, fingerprint = _seed_post_ready_dispatch(
            session
        )
        mutations: list[str] = []

        result = SagaEngine(uow).execute_fenced_external_action(
            claim_context=claim,
            action_key=action_key,
            action_type=ExternalActionType.INTAKE_ARTIFACT_PUBLISH,
            target_identity=ownership.change_name,
            request_fingerprint=fingerprint,
            saga_id=saga.id,
            observation_fn=lambda: ExternalActionResult(
                outcome=ExternalOutcome.FAILURE,
                source_adapter="isolated-test-remote",
                reason_code=ExternalReasonCode.NOT_FOUND,
                retry_safety=RetrySafety.SAFE,
            ),
            mutation_fn=lambda: (
                mutations.append("cas-p-to-p2")
                or ExternalActionResult(
                    outcome=ExternalOutcome.SUCCESS,
                    source_adapter="isolated-test-remote",
                    reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                    retry_safety=RetrySafety.SAFE,
                    external_id="c" * 40,
                    data={"published_sha": "c" * 40},
                )
            ),
        )
        assert result.outcome == ExternalOutcome.SUCCESS
        assert result.result_application_authorized is True
        assert mutations == ["cas-p-to-p2"]
        assert uow.external_action_attempts.list_by_action_key(action_key)
        completed = uow.orchestration_external_actions.get_by_action_key(action_key)
        assert completed.status == ExternalActionStatus.COMPLETED
        persisted_saga = uow.durable_sagas.get_by_id(saga.id)
        assert persisted_saga.status == SagaStatus.COMPLETED
        assert persisted_saga.current_phase == "READY"


@pytest.mark.parametrize(
    ("saga_status", "phase", "action_type", "published"),
    [
        (SagaStatus.COMPLETED, "READY", ExternalActionType.ISSUE_CLOSE, True),
        (
            SagaStatus.COMPLETED,
            "READINESS_EVALUATED",
            ExternalActionType.INTAKE_ARTIFACT_PUBLISH,
            True,
        ),
        (SagaStatus.FAILED, "READY", ExternalActionType.INTAKE_ARTIFACT_PUBLISH, True),
        (SagaStatus.CANCELLED, "READY", ExternalActionType.INTAKE_ARTIFACT_PUBLISH, True),
        (SagaStatus.COMPLETED, "READY", ExternalActionType.INTAKE_ARTIFACT_PUBLISH, False),
    ],
)
def test_terminal_saga_authority_denies_unqualified_dispatch(
    isolated_pg_session_factory, saga_status, phase, action_type, published
):
    with isolated_pg_session_factory() as session:
        uow, _saga, _ownership, _action, claim, action_key, _fp = _seed_post_ready_dispatch(
            session,
            saga_status=saga_status,
            phase=phase,
            action_type=action_type,
            published=published,
        )
        from minime.domain.models import DispatchAuthorization

        authorization = DispatchAuthorization(
            action_key=action_key,
            is_authorized=True,
            authorization_reason="unit test proves durable repository authority is independent",
        )
        with pytest.raises(StaleClaimError):
            uow.claims.commit_fenced_dispatch_intent(
                claim_key=claim.claim_key,
                owner_instance_id=claim.owner_instance_id,
                fence_token=claim.fence_token,
                action_key=action_key,
                authorization=authorization,
            )


def test_post_ready_dispatch_rejects_wrong_fence_and_expired_claim(isolated_pg_session_factory):
    with isolated_pg_session_factory() as session:
        uow, _saga, _ownership, _action, claim, action_key, _fp = _seed_post_ready_dispatch(session)
        from minime.domain.models import DispatchAuthorization

        authorization = DispatchAuthorization(
            action_key=action_key,
            is_authorized=True,
            authorization_reason="test",
        )
        with pytest.raises(StaleClaimError):
            uow.claims.commit_fenced_dispatch_intent(
                claim_key=claim.claim_key,
                owner_instance_id=claim.owner_instance_id,
                fence_token=claim.fence_token + 1,
                action_key=action_key,
                authorization=authorization,
            )
        session.execute(
            text(
                "UPDATE recovery_claims SET lease_expires_at = now() - interval '1 second' "
                "WHERE claim_key = :key"
            ),
            {"key": claim.claim_key},
        )
        session.commit()
        with pytest.raises(StaleClaimError):
            uow.claims.commit_fenced_dispatch_intent(
                claim_key=claim.claim_key,
                owner_instance_id=claim.owner_instance_id,
                fence_token=claim.fence_token,
                action_key=action_key,
                authorization=authorization,
            )


def test_post_ready_dispatch_rejects_contradictory_publication_fingerprint(
    isolated_pg_session_factory,
):
    with isolated_pg_session_factory() as session:
        uow, _saga, _ownership, action, claim, action_key, _fp = _seed_post_ready_dispatch(session)
        from minime.db.models import OrchestrationExternalActionModel
        from minime.domain.models import DispatchAuthorization

        action_model = session.get(OrchestrationExternalActionModel, action.action_id)
        assert action_model is not None
        action_model.request_fingerprint = "f" * 64
        session.commit()
        with pytest.raises(StaleClaimError):
            uow.claims.commit_fenced_dispatch_intent(
                claim_key=claim.claim_key,
                owner_instance_id=claim.owner_instance_id,
                fence_token=claim.fence_token,
                action_key=action_key,
                authorization=DispatchAuthorization(
                    action_key=action_key,
                    is_authorized=True,
                    authorization_reason="test",
                ),
            )


def test_post_ready_dispatch_rejects_claim_for_another_item(isolated_pg_session_factory):
    with isolated_pg_session_factory() as session:
        uow, _saga, _ownership, _action, _claim, action_key, _fp = _seed_post_ready_dispatch(
            session
        )
        wrong_claim = RecoveryConvergenceService(
            uow, owner_instance_id="wrong-item-owner"
        ).acquire_claim(f"intake:other-project:{uuid.uuid4().hex}", lease_seconds=60)
        assert wrong_claim is not None
        from minime.domain.models import DispatchAuthorization

        with pytest.raises(ValueError, match="Cross-parent action dispatch rejected"):
            uow.claims.commit_fenced_dispatch_intent(
                claim_key=wrong_claim.claim_key,
                owner_instance_id=wrong_claim.owner_instance_id,
                fence_token=wrong_claim.fence_token,
                action_key=action_key,
                authorization=DispatchAuthorization(
                    action_key=action_key,
                    is_authorized=True,
                    authorization_reason="test",
                ),
            )


def test_post_ready_dispatch_rejects_action_rebound_to_another_saga(
    isolated_pg_session_factory,
):
    with isolated_pg_session_factory() as session:
        uow, saga, _ownership, action, claim, action_key, _fp = _seed_post_ready_dispatch(session)
        from minime.db.models import OrchestrationExternalActionModel
        from minime.domain.models import DispatchAuthorization

        other_saga = DurableSaga(
            id=generate_uuid(),
            saga_type=SagaType.INTAKE,
            project_id=saga.project_id,
            work_item_key="different-item",
            change_name="different-change",
            current_phase="OPENSPEC_AUTHORED",
            status=SagaStatus.IN_PROGRESS,
        )
        uow.durable_sagas.save(other_saga)
        action_model = session.get(OrchestrationExternalActionModel, action.action_id)
        assert action_model is not None
        action_model.saga_id = other_saga.id
        session.commit()

        with pytest.raises(ValueError, match="Cross-parent action dispatch rejected"):
            uow.claims.commit_fenced_dispatch_intent(
                claim_key=claim.claim_key,
                owner_instance_id=claim.owner_instance_id,
                fence_token=claim.fence_token,
                action_key=action_key,
                authorization=DispatchAuthorization(
                    action_key=action_key,
                    is_authorized=True,
                    authorization_reason="test",
                ),
            )


def test_post_ready_main_advancement_reaches_readiness_admission_and_job_handoff(
    isolated_pg_session_factory, tmp_path, monkeypatch
):
    from tests.conftest import setup_managed_repository_fixture
    from typer.testing import CliRunner

    from minime.adapters.github import GitHubAdapter
    from minime.cli.main import app as cli_app
    from minime.domain.enums import ExternalReasonCode
    from minime.services.readiness_service import ReadinessService

    project_id = f"postready-e2e-{uuid.uuid4().hex[:8]}"
    change_name = "operational-blocker-visibility"
    repo = tmp_path / "managed"
    worktrees = tmp_path / "worktrees"

    with isolated_pg_session_factory() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        project = Project(
            project_id=project_id,
            display_name="Post-ready E2E",
            repository="silverberdi/mini-me",
            base_branch="main",
            openspec_path="openspec",
        )
        uow.projects.save(project)
        session.commit()
        setup_managed_repository_fixture(
            uow,
            project_id,
            repo,
            worktrees,
            canonical_repository_identity="github.com/silverberdi/mini-me",
        )
        session.commit()
        managed_binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
        assert managed_binding is not None
        local_remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        managed_binding.canonical_repository_identity = local_remote
        uow.project_managed_repository_bindings.save(managed_binding)
        project = project.model_copy(update={"repository": local_remote})
        uow.projects.save(project)
        marker_path = repo / ".minime-managed-project.json"
        marker_path.write_text(
            json.dumps(
                {"project_id": project_id, "canonical_repository_identity": local_remote},
                indent=2,
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "add", marker_path.name], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                "bind local test remote",
            ],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True)
        uow.bindings.save(
            ProjectBinding(
                project_id=project_id,
                repository=project.repository,
                github_issue_number=133,
                openspec_change_name=change_name,
            )
        )
        item = BacklogItem(
            project_id=project_id,
            item_key=change_name,
            title="Operational blocker visibility",
            description="Expose operational blocker details for N01.",
            acceptance_criteria=["Published artifacts are admitted from verified Git state."],
            openspec_change_name=change_name,
            status=WorkItemStatus.READY,
            readiness_state=ReadinessState.READY,
        )
        uow.backlog_items.save(item)
        uow.changes.save(
            Change(
                project_id=project_id,
                name=change_name,
                schema_name="feature",
                status=ChangeStatus.READY,
                last_readiness_status=ReadinessState.READY,
            )
        )
        session.commit()

        saga_engine = SagaEngine(uow)
        saga = saga_engine.start_saga(
            SagaType.INTAKE,
            project_id,
            item.item_key,
            change_name=change_name,
            initial_phase="READY",
        )
        intake = IntakeService(uow, project_root=repo)
        ownership = intake._reserve_intake_workspace(project, item, saga)
        intake._activate_intake_workspace(ownership, project)
        generated = intake.openspec_generator.generate_from_backlog_item(item, project.display_name)
        intake.openspec_generator.write_change_to_disk(
            project.openspec_path,
            generated,
            project_id=project_id,
            target_workspace_path=ownership.canonical_workspace_path,
        )
        intake._commit_intake_artifacts(ownership, generated, project)
        published_p = intake._publish_intake_artifacts_cas(ownership, project)
        saga_engine.complete_saga(saga, evidence_references={"published_sha": published_p})
        saga_before = uow.durable_sagas.get_by_id(saga.id)
        assert saga_before.status == SagaStatus.COMPLETED
        assert saga_before.current_phase == "READY"

        # The test helper creates a bare remote beside the managed checkout. Resolve the actual
        # configured URL instead of assuming its generated path.
        remote = Path(
            subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
        )
        base_a = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True
        ).stdout.strip()
        changed = repo / "src" / "merged_elsewhere.py"
        changed.parent.mkdir(parents=True, exist_ok=True)
        changed.write_text("# unrelated merged change\n", encoding="utf-8")
        subprocess.run(["git", "add", "src/merged_elsewhere.py"], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                "advance main",
            ],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True)
        base_b = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True
        ).stdout.strip()
        assert base_b != base_a

        # setup_managed_repository_fixture makes the local bare remote the canonical test identity.
        binding = uow.project_managed_repository_bindings.get_by_project_id(project_id)
        assert binding.canonical_repository_identity == project.repository

        monkeypatch.setattr(
            GitHubAdapter,
            "_git_auth_bundle",
            lambda _adapter, _url: type("Auth", (), {"env": {}, "secrets": ()})(),
        )
        observed_readiness_shas: list[str] = []
        original_tree_evaluation = ReadinessService._evaluate_verified_published_tree

        def track_published_tree_evaluation(service, **kwargs):
            observed_readiness_shas.append(kwargs["published_sha"])
            return original_tree_evaluation(service, **kwargs)

        monkeypatch.setattr(
            ReadinessService,
            "_evaluate_verified_published_tree",
            track_published_tree_evaluation,
        )
        monkeypatch.setattr(
            GitHubAdapter,
            "validate_issue_binding",
            lambda _adapter, *_args, **_kwargs: ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="isolated-postgres-test",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                retry_safety=RetrySafety.SAFE,
                data=True,
            ),
        )
        for provider in ("codex", "antigravity"):
            uow.provider_health.save(
                ProviderHealth(provider=provider, status=ProviderHealthStatus.AVAILABLE)
            )
        session.commit()

        created_worktrees: list[Path] = []
        original_materialize = WorktreeManager._materialize_verified_published_intake_artifacts

        async def materialize_then_stop_before_provider(manager, **kwargs):
            await original_materialize(manager, **kwargs)
            created_worktrees.append(
                kwargs["destination_worktree"]
                / "openspec"
                / "changes"
                / kwargs["change_name"]
                / "proposal.md"
            )
            raise RuntimeError("stop test after authoritative published-artifact handoff")

        monkeypatch.setattr(
            WorktreeManager,
            "_materialize_verified_published_intake_artifacts",
            materialize_then_stop_before_provider,
        )

        class SessionContext:
            def __enter__(self):
                return session

            def __exit__(self, *_args):
                return False

        monkeypatch.setattr("minime.cli.main.db_manager.session", lambda: SessionContext())
        result = CliRunner().invoke(
            cli_app,
            ["orchestrate", "start", project_id, change_name, "--path", str(repo)],
        )

        updated = uow.intake_workspace_ownerships.get_by_id(ownership.workspace_id)
        assert updated.base_sha == base_b
        assert updated.published_sha != published_p
        assert updated.published_ref == f"refs/minime/intake/{change_name}"
        saga_after = uow.durable_sagas.get_by_id(saga.id)
        assert saga_after.status == SagaStatus.COMPLETED
        assert saga_after.current_phase == "READY"
        action_key = f"intake_main_advance_publish:{project_id}:{change_name}:{base_b}"
        action = uow.orchestration_external_actions.get_by_action_key(action_key)
        assert action is not None and action.status == ExternalActionStatus.COMPLETED
        assert uow.external_action_attempts.list_by_action_key(action_key)
        assert uow.orchestration_runs.list_runs(), (
            f"CLI admission did not create a run; exit={result.exit_code}; "
            f"output={result.output}; exception={result.exception}"
        )
        run = uow.orchestration_runs.list_runs()[0]
        assert run.active_job_id
        job = uow.jobs.get_by_id(run.active_job_id)
        assert job is not None
        worktree_ownership = uow.orchestration_worktree_ownerships.get_by_job_id(job.job_id)
        assert worktree_ownership is not None
        assert Path(worktree_ownership.canonical_worktree_path).exists()
        assert observed_readiness_shas and set(observed_readiness_shas) == {updated.published_sha}
        assert created_worktrees and created_worktrees[0].is_file(), result.output
        assert "COORDINATOR STAGE: IMPLEMENTING" in result.output
        assert "stop test after authoritative published-artifact handoff" in result.output
        assert "LIFECYCLE_DRIFT" not in result.output
        assert (
            updated.published_sha
            in subprocess.run(
                ["git", "ls-remote", str(remote), updated.published_ref],
                text=True,
                capture_output=True,
                check=True,
            ).stdout
        )
        assert "stop test after authoritative" in str(result.exception) or result.exit_code == 0
