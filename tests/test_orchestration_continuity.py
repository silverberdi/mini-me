from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.conftest import InMemoryPersistenceUnitOfWork, setup_managed_repository_fixture

from minime.domain.enums import ExternalOutcome, ExternalReasonCode, OrchestrationStage, RetrySafety
from minime.domain.models import ExternalActionResult, OrchestrationRun
from minime.services.agent_runner import CliAgentRunner
from minime.services.orchestration_coordinator import NativeOrchestrationCoordinator
from minime.services.worktree_manager import WorktreeInfo, WorktreeManager


@pytest.mark.asyncio
async def test_orchestration_continuity_worktree_preserved_on_failure(tmp_path: Path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    managed_root = tmp_path / "worktrees"
    managed_root.mkdir()

    candidate_worktree = managed_root / "request-401-database-connection-pooling"
    candidate_worktree.mkdir(parents=True, exist_ok=True)

    # Dummy workflows inside candidate worktree
    skill_dir = candidate_worktree / ".agents" / "skills"
    for skill in ["openspec-explore", "openspec-propose", "openspec-apply-change", "openspec-verify-change", "openspec-sync-specs", "openspec-archive-change"]:
        d = skill_dir / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\n---\n# {skill}")

    uow = InMemoryPersistenceUnitOfWork()
    setup_managed_repository_fixture(
        uow,
        "proj-1",
        repo_dir,
        managed_root,
        canonical_repository_identity="github.com/org/proj-1",
    )

    github_mock = MagicMock()
    github_mock.list_issues.side_effect = lambda repo, state="open", limit=None: ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        retry_safety=RetrySafety.SAFE,
        data=[
            {
                "number": 401,
                "title": "Database connection pooling",
                "body": "Add pooling",
                "labels": [],
                "created_at": "2026-10-23T10:00:00Z",
                "updated_at": "2026-10-23T10:00:00Z",
                "html_url": "https://github.com/org/proj-1/issues/401",
            }
        ],
    )
    github_mock.create_pull_request = AsyncMock(return_value={"number": 20, "html_url": "https://github.com/org/proj-1/pull/20"})
    github_mock.merge_pull_request = AsyncMock(return_value={"merged": False, "message": "Branch protection required review"})

    wt_manager = WorktreeManager(repo_dir, uow=uow)
    candidate_worktree = managed_root / "request-401-database-connection-pooling"
    candidate_worktree.mkdir(parents=True, exist_ok=True)
    wt_manager.create_request_worktree = AsyncMock(
        return_value=WorktreeInfo(path=candidate_worktree, branch_name="request-401-database-connection-pooling", base_sha="sha1")
    )

    agent_runner = CliAgentRunner()
    openspec_mock = MagicMock()
    openspec_mock.validate_change_strict = MagicMock(return_value={"status": "PASS", "returncode": 0})

    coordinator = NativeOrchestrationCoordinator(
        uow_factory=lambda: uow,
        github_adapter=github_mock,
        worktree_manager=wt_manager,
        agent_runner=agent_runner,
        openspec_adapter=openspec_mock,
    )
    coordinator._push_branch = AsyncMock()
    coordinator._get_git_head_sha = AsyncMock(return_value="head_sha_401")
    coordinator._git_run = AsyncMock(return_value="")

    # Run should encounter PR1 merge failure due to branch protection
    result = await coordinator.execute_project_request(
        "proj-1",
        thinker_provider="codex",
        implementer_provider="codex",
        reviewer_provider="codex",
    )

    assert result.status == "PAUSED"
    assert result.current_stage == OrchestrationStage.EXPLORING
    assert "Explore" in result.message
    # Critical requirement: Worktree MUST be preserved, not deleted!
    assert candidate_worktree.exists()

    # Active run record MUST remain active in PostgreSQL (not abandoned or unlocked)
    active_runs = uow.orchestration_runs.list_runs(project_id="proj-1", is_active=True)
    assert len(active_runs) == 1
    assert active_runs[0].current_stage == OrchestrationStage.EXPLORING


def test_request_rest_api_endpoints(in_memory_uow, tmp_path: Path):
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from minime.api.app import app, get_current_operator, get_uow
    from minime.domain.models import AuthorizedOperator, Project

    repo_root = tmp_path / "repo-test"
    repo_root.mkdir()
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    setup_managed_repository_fixture(
        in_memory_uow,
        "proj-test",
        repo_root,
        wt_root,
        canonical_repository_identity="github.com/org/repo-test",
    )
    in_memory_uow.projects.save(
        Project(
            project_id="proj-test",
            display_name="Test",
            repository="org/repo-test",
        )
    )

    mock_operator = AuthorizedOperator(
        email="operator@example.com",
        name="Operator",
        roles=["admin"],
    )

    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_current_operator] = lambda: mock_operator

    try:
        client = TestClient(app)

        # 1. GET eligible requests list
        with patch("minime.services.remote_request_intake.RemoteRequestIntakeService.get_eligible_requests", return_value=[{"number": 101, "title": "Feat"}]):
            res = client.get("/api/v1/projects/proj-test/requests")
            assert res.status_code == 200
            data = res.json()
            assert data["project_id"] == "proj-test"
            assert len(data["eligible_requests"]) == 1

        # 2. POST request run
        with patch("minime.services.agent_runner.CliAgentRunner.for_project_profiles", return_value=MagicMock()), \
             patch("minime.services.orchestration_coordinator.NativeOrchestrationCoordinator.execute_project_request") as mock_exec:
            mock_res = MagicMock(
                status="COMPLETED",
                run_id="run-1",
                current_stage=OrchestrationStage.COMPLETED,
                message="Done",
                pr1_url="https://github.com/org/repo-test/pull/1",
                pr2_url="https://github.com/org/repo-test/pull/2",
                human_payload=None,
            )
            mock_exec.return_value = mock_res
            res = client.post("/api/v1/projects/proj-test/requests/run", json={"operator_ack": False})
            assert res.status_code == 200
            assert "operator_response" not in mock_exec.call_args.kwargs
            data = res.json()
            assert data["status"] == "COMPLETED"
            assert data["pr1_url"] == "https://github.com/org/repo-test/pull/1"

        # 3. POST request ack
        with patch("minime.services.agent_runner.CliAgentRunner.for_project_profiles", return_value=MagicMock()), \
             patch("minime.services.orchestration_coordinator.NativeOrchestrationCoordinator.execute_project_request") as mock_exec:
            mock_exec.return_value = mock_res
            res = client.post("/api/v1/projects/proj-test/requests/ack")
            assert res.status_code == 200
            mock_exec.assert_called_once_with("proj-test", operator_ack=True)

        # 4. Recovery authority is recorded through the authenticated API and
        # produces the same durable OperatorActionRecord consumed by CLI runs.
        recovery_run = OrchestrationRun(
            run_id="run-recovery-api",
            project_id="proj-test",
            change_name="req-101-feat",
            base_sha="main",
            current_stage=OrchestrationStage.EXPLORING,
            resumable_stage=OrchestrationStage.EXPLORING,
            stop_details={
                "explore_attempt": {
                    "attempt_id": "attempt-recovery-api",
                    "status": "IN_PROGRESS",
                    "issue_number": 101,
                    "provider": "antigravity",
                    "context_sha256": "a" * 64,
                    "workflow_sha256": "b" * 64,
                }
            },
        )
        in_memory_uow.orchestration_runs.save(recovery_run)
        res = client.post(
            "/api/v1/projects/proj-test/runs/run-recovery-api/explore-recovery-authorizations",
            json={"prior_attempt_id": "attempt-recovery-api", "action_request_id": "api-recovery-1"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "ACCEPTED"
        record = in_memory_uow.operator_actions.get_by_request_id("api-recovery-1")
        assert record is not None
        assert record.actor_identity == "operator@example.com"
    finally:
        app.dependency_overrides.clear()

