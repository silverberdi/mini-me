from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import setup_managed_repository_fixture

from minime.api.app import app, get_current_operator, get_uow
from minime.domain.enums import OrchestrationStage
from minime.domain.models import AuthorizedOperator, OrchestrationRun, Project


def test_code_review_recovery_authorization_is_run_bound(in_memory_uow, tmp_path: Path):
    repo_root = tmp_path / "repo"
    worktrees = tmp_path / "worktrees"
    repo_root.mkdir()
    worktrees.mkdir()
    setup_managed_repository_fixture(
        in_memory_uow,
        "proj-review",
        repo_root,
        worktrees,
        canonical_repository_identity="github.com/org/proj-review",
    )
    in_memory_uow.projects.save(
        Project(
            project_id="proj-review",
            display_name="Review",
            repository="org/proj-review",
            agent_profiles={"independent_review": {"agent_id": "opencode", "model_id": "deepseek-chat"}},
        )
    )
    in_memory_uow.orchestration_runs.save(
        OrchestrationRun(
            run_id="run-review",
            project_id="proj-review",
            change_name="req-review",
            base_sha="base",
            candidate_sha="candidate",
            current_stage=OrchestrationStage.CODE_REVIEW,
            resumable_stage=OrchestrationStage.CODE_REVIEW,
            stop_details={
                "issue_number": 208,
                "code_review": {
                    "attempt_id": "attempt-review",
                    "status": "invalid_response",
                    "candidate_sha": "candidate",
                },
            },
        )
    )
    operator = AuthorizedOperator(email="operator@example.com", name="Operator", roles=["admin"])
    app.dependency_overrides[get_uow] = lambda: in_memory_uow
    app.dependency_overrides[get_current_operator] = lambda: operator
    try:
        client = TestClient(app)
        accepted = client.post(
            "/api/v1/projects/proj-review/runs/run-review/code-review-recovery-authorizations",
            json={"prior_attempt_id": "attempt-review", "action_request_id": "recovery-review-1"},
        )
        assert accepted.status_code == 200
        assert accepted.json() == {
            "action_request_id": "recovery-review-1",
            "run_id": "run-review",
            "status": "ACCEPTED",
        }

        duplicate = client.post(
            "/api/v1/projects/proj-review/runs/run-review/code-review-recovery-authorizations",
            json={"prior_attempt_id": "attempt-review", "action_request_id": "recovery-review-1"},
        )
        assert duplicate.status_code == 409
    finally:
        app.dependency_overrides.clear()
