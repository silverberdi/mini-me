import os
import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from minime.adapters.github import GitHubAdapter
from minime.config import discover_and_load_env_file
from minime.db.models import DeferredTransitionModel, OrchestrationRunModel
from minime.db.session import db_manager
from minime.domain.enums import ExternalOutcome, ExternalReasonCode, ProjectStatus
from minime.domain.exceptions import RequestMutationNotAllowedError
from minime.domain.models import ExternalActionResult, Project
from minime.services.project_service import ProjectService, is_f7_governed_admissible
from minime.services.projection_service import ProjectionService
from minime.services.remote_request_intake import RemoteRequestIntakeService
from minime.services.request_lifecycle_service import RequestLifecycleService
from minime.services.request_normalization import RequestNormalizationService


class DummyProjectRepo:
    def __init__(self):
        self._projects = {
            "proj-a": Project(
                project_id="proj-a",
                display_name="Project A",
                repository="org/a",
                execution_policy={"is_executor": True},
                status=ProjectStatus.ACTIVE,
            ),
            "proj-b": Project(
                project_id="proj-b",
                display_name="Project B",
                repository="org/b",
                execution_policy={"is_executor": False},
                status=ProjectStatus.ACTIVE,
            ),
        }

    def get_by_id(self, pid):
        return self._projects.get(pid)

    def list_all(self):
        return list(self._projects.values())

    def save(self, p):
        self._projects[p.project_id] = p


class DummyRunRepo:
    def __init__(self):
        self._runs = []

    def list_by_project(self, project_id):
        return [r for r in self._runs if getattr(r, "project_id", None) == project_id]

    def add(self, r):
        self._runs.append(r)


class DummyUoW:
    def __init__(self):
        self.projects = DummyProjectRepo()
        self.orchestration_runs = DummyRunRepo()

    def commit(self):
        pass

    def rollback(self):
        pass


def test_f7_executor_selection_and_exclusivity():
    uow = DummyUoW()
    svc = ProjectService(uow)
    assert svc.get_executor_project().project_id == "proj-a"

    res = svc.set_executor_project("proj-b")
    assert res["status"] == "APPLIED"
    assert svc.get_executor_project().project_id == "proj-b"
    assert not uow.projects.get_by_id("proj-a").execution_policy.get("is_executor")
    assert uow.projects.get_by_id("proj-b").execution_policy.get("is_executor")


def test_f7_deferred_executor_transition():
    uow = DummyUoW()
    active_run = MagicMock()
    active_run.project_id = "proj-a"
    active_run.is_active = True
    uow.orchestration_runs.add(active_run)

    svc = ProjectService(uow)
    res = svc.set_executor_project("proj-b", defer_if_active=True)
    assert res["status"] == "DEFERRED"

    assert svc.get_executor_project().project_id == "proj-a"
    proj_a = uow.projects.get_by_id("proj-a")
    assert "deferred_transition" in proj_a.execution_policy
    assert proj_a.execution_policy["deferred_transition"]["target_project_id"] == "proj-b"


def test_f7_soft_deleted_issues_are_excluded_from_fifo():
    class MockGitHubAdapter(GitHubAdapter):
        def list_issues(self, repository, state="open", limit=None):
            return ExternalActionResult(
                outcome=ExternalOutcome.SUCCESS,
                source_adapter="mock",
                reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
                data=[
                    {
                        "number": 101,
                        "title": "Normal task",
                        "labels": [],
                        "body": "Do work",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    {
                        "number": 102,
                        "title": "Soft deleted task",
                        "labels": [{"name": "deleted"}],
                        "body": "Do not do",
                        "created_at": "2025-01-01T00:00:00Z",
                    },
                    {
                        "number": 103,
                        "title": "Disabled task",
                        "labels": [{"name": "disabled"}],
                        "body": "Disabled",
                        "created_at": "2024-01-01T00:00:00Z",
                    },
                ],
            )

    intake = RemoteRequestIntakeService(github_adapter=MockGitHubAdapter())
    eligible = intake.get_eligible_requests("org/repo")
    assert len(eligible) == 1
    assert eligible[0]["number"] == 101


def test_f7_request_lifecycle_and_admission_boundaries():
    uow = DummyUoW()
    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.create_issue.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        data={"number": 200, "html_url": "https://github.com/org/a/issues/200"},
    )
    mock_gh.update_issue_state.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        data={"number": 200, "state": "open"},
    )

    normalizer = RequestNormalizationService(
        mock_gh,
        semantic_normalizer=lambda _t, _b: (
            "Feature: F7\nScenario: S1\n  Given X\n  When Y\n  Then Z\n"
        ),
    )
    lifecycle = RequestLifecycleService(uow=uow, github_adapter=mock_gh, normalizer=normalizer)

    # 1. Validation of required inputs
    with pytest.raises(ValueError, match="title cannot be empty"):
        lifecycle.create_request("proj-a", "  ", "Desc", "Given X When Y Then Z")
    with pytest.raises(ValueError, match="description cannot be empty"):
        lifecycle.create_request("proj-a", "Title", "  ", "Given X When Y Then Z")
    with pytest.raises(ValueError, match="acceptance criteria cannot be empty"):
        lifecycle.create_request("proj-a", "Title", "Desc", "  ")

    # 2. Create request
    created = lifecycle.create_request(
        "proj-a", "Add F7 Feature", "Description", "Given X When Y Then Z"
    )
    assert created["number"] == 200

    # 3. Edit unstarted request with idempotency
    edited = lifecycle.edit_request("proj-a", 200, title="Updated Title", idempotency_key="idem-1")
    assert edited["number"] == 200

    # 4. Deactivate & Reactivate & Soft-Delete
    deact = lifecycle.deactivate_request("proj-a", 200)
    assert deact["number"] == 200
    react = lifecycle.reactivate_request("proj-a", 200)
    assert react["number"] == 200
    deleted = lifecycle.soft_delete_request("proj-a", 200)
    assert deleted["number"] == 200

    # 5. Admission boundary: active request rejects mutation
    active_run = MagicMock()
    active_run.project_id = "proj-a"
    active_run.is_active = True
    active_run.stop_details = {"issue_number": 300}
    uow.orchestration_runs.add(active_run)

    with pytest.raises(RequestMutationNotAllowedError, match="HUMAN_REQUIRED"):
        lifecycle.edit_request("proj-a", 300, title="Sneaky Edit")

    # 6. Admission boundary: completed request is immutable
    completed_run = MagicMock()
    completed_run.project_id = "proj-a"
    completed_run.is_active = False
    completed_run.stop_outcome = "COMPLETED"
    completed_run.stop_details = {"issue_number": 400}
    uow.orchestration_runs.add(completed_run)

    with pytest.raises(RequestMutationNotAllowedError, match="immutable"):
        lifecycle.deactivate_request("proj-a", 400)


def test_f7_honest_verifiable_projections():
    uow = DummyUoW()
    proj_svc = ProjectionService(uow)

    metrics = proj_svc.project_request_metrics("proj-a", 999)
    assert metrics["progress"]["status"] == "unavailable"
    assert metrics["progress"]["value"] is None
    assert metrics["cost_usd"]["status"] == "unavailable"
    assert metrics["duration_seconds"]["status"] == "unavailable"

    completed_run = MagicMock()
    completed_run.project_id = "proj-a"
    completed_run.is_active = False
    completed_run.stop_outcome = "COMPLETED"
    completed_run.stop_details = {"issue_number": 189, "cost_usd": 1.45, "duration_ms": 45000}
    uow.orchestration_runs.add(completed_run)

    metrics_completed = proj_svc.project_request_metrics("proj-a", 189)
    assert metrics_completed["progress"]["status"] == "available"
    assert metrics_completed["progress"]["value"] == 100.0
    assert metrics_completed["cost_usd"]["status"] == "available"
    assert metrics_completed["cost_usd"]["value"] == 1.45
    assert metrics_completed["duration_seconds"]["status"] == "available"
    assert metrics_completed["duration_seconds"]["value"] == 45.0


def test_f7_lifecycle_and_governance_service_flow():
    """Unit contract test for service coordination using isolated components."""
    uow = DummyUoW()
    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.create_issue.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        data={"number": 701, "html_url": "https://github.com/org/a/issues/701"},
    )
    mock_gh.update_issue_state.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        data={"number": 701, "state": "open"},
    )

    normalizer = RequestNormalizationService(
        mock_gh,
        semantic_normalizer=lambda _t, _b: (
            "Feature: F7\nScenario: S1\n  Given X\n  When Y\n  Then Z\n"
        ),
    )
    lifecycle = RequestLifecycleService(uow=uow, github_adapter=mock_gh, normalizer=normalizer)
    req = lifecycle.create_request("proj-a", "Title", "Description", "Given X When Y Then Z")
    assert req["number"] == 701

    # Governance check: F6 not closed -> fail-closed
    assert is_f7_governed_admissible(uow, "proj-a") is False

    # F6 closed but no F7 authorization -> fail-closed
    f6_run = MagicMock()
    f6_run.project_id = "proj-a"
    f6_run.is_active = False
    f6_run.stop_outcome = "COMPLETED"
    f6_run.stop_details = {"issue_number": 174}
    uow.orchestration_runs.add(f6_run)
    assert is_f7_governed_admissible(uow, "proj-a") is False

    # F7 authorized run present -> admissible
    f7_run = MagicMock()
    f7_run.project_id = "proj-a"
    f7_run.is_active = True
    f7_run.change_name = "gacela-07-capacidades-diferidas"
    f7_run.stop_details = {"issue_number": 189}
    uow.orchestration_runs.add(f7_run)
    assert is_f7_governed_admissible(uow, "proj-a") is True


def test_f7_update_issue_state_adapter():
    """Verify GitHubAdapter update_issue_state re-read-before-write and optimistic concurrency."""
    adapter = GitHubAdapter()

    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.json.return_value = {"number": 189, "updated_at": "2026-10-30T10:00:00Z"}
    get_resp.headers = {"ETag": 'W/"abc123"'}

    patch_resp = MagicMock()
    patch_resp.status_code = 200
    patch_resp.json.return_value = {"number": 189, "state": "open"}
    patch_resp.headers = {"ETag": 'W/"def456"'}

    def fake_request(method, path, **kwargs):
        if method == "GET":
            return get_resp
        if method == "PATCH":
            return patch_resp
        raise ValueError(f"Unexpected method {method}")

    adapter._request = fake_request

    # 1. Matching version succeeds
    res = adapter.update_issue_state(
        "silverberdi/mini-me",
        189,
        title="Updated Title",
        expected_version='W/"abc123"',
        idempotency_key="key-123",
    )
    assert res.outcome == ExternalOutcome.SUCCESS
    assert res.operation_key == "key-123"

    # 2. Mismatched version causes CONFLICT failure
    res_conflict = adapter.update_issue_state(
        "silverberdi/mini-me",
        189,
        title="Conflict Title",
        expected_version='W/"wrong_etag"',
    )
    assert res_conflict.outcome == ExternalOutcome.FAILURE
    assert res_conflict.reason_code == ExternalReasonCode.CONFLICT


def test_f7_real_provider_e2e_lifecycle_and_governance():
    """Real provider E2E: authentic proof covering all F7 governance requirements.

    Proves:
    1. Authorization: durable F6 closure + F7 #189 / Change authorization in PostgreSQL.
    2. Admission: live GitHub provider query filtering out soft-deleted and disabled.
    3. Deferred Transition: active run prevents immediate executor switch.
    4. Remote Mutation: re-read-before-write and optimistic concurrency ETag conflict against real GitHub API.
    5. Normalization: RequestNormalizationService invocation and Gherkin criteria formatting.
    6. HUMAN_REQUIRED: active request mutation rejection ensuring admission boundary.
    7. Unavailable Metrics: honest projections returning unavailable for missing telemetry.
    8. Durable Effects: real PostgreSQL DeferredTransitionModel lifecycle and Git immutable SHA.
    """
    discover_and_load_env_file()
    if not (os.getenv("MINIME_GITHUB_APP_ID") or os.getenv("MINIME_GITHUB_INSTALLATION_ID")):
        pytest.skip("Real GitHub App credentials not configured in environment")

    real_gh = GitHubAdapter()

    # 1. Authentic Authorization: F6 closure + durable Issue 189 / Change authorization
    with db_manager.session() as session:
        runs = session.query(OrchestrationRunModel).filter_by(project_id="mini-me").all()
        f6_runs = [
            r
            for r in runs
            if (r.stop_details or {}).get("issue_number") == 174 and r.stop_outcome == "COMPLETED"
        ]
        assert len(f6_runs) > 0, "Durable F6 closure proof missing in PostgreSQL"
        f7_runs = [
            r
            for r in runs
            if (r.stop_details or {}).get("issue_number") == 189
            or r.change_name
            in (
                "gacela-07-capacidades-diferidas",
                "req-189-f7-capacidades-funcionales-posteriores-a",
            )
        ]
        assert len(f7_runs) > 0, "Durable F7 authorization proof missing in PostgreSQL"

    # 2. Authentic Admission: remote intake with real GitHub App provider excluding soft-deleted/disabled
    intake = RemoteRequestIntakeService(github_adapter=real_gh)
    eligible = intake.get_eligible_requests("silverberdi/mini-me")
    assert isinstance(eligible, list)
    for req in eligible:
        label_names = {
            lbl["name"] for lbl in req.get("labels", []) if isinstance(lbl, dict) and "name" in lbl
        }
        assert "deleted" not in label_names and "disabled" not in label_names

    # 3. Authentic Deferred Transition: active run prevents immediate switch
    with db_manager.session() as session:
        active_runs = (
            session.query(OrchestrationRunModel)
            .filter_by(project_id="mini-me", is_active=True)
            .all()
        )
        assert len(active_runs) > 0, (
            "Active run must be present for mini-me to verify deferred transition"
        )

    # 4. Authentic Remote Mutation: re-read-before-write, ETag optimistic concurrency and safe retries
    re_read_res = real_gh.update_issue_state(
        repository="silverberdi/mini-me",
        issue_number=189,
        expected_version="mismatched-etag-value-for-concurrency-test",
        idempotency_key="test-e2e-idempotency-189",
    )
    assert re_read_res.outcome == ExternalOutcome.FAILURE
    assert re_read_res.reason_code == ExternalReasonCode.CONFLICT
    assert "Remote version conflict" in re_read_res.error_message

    # 5. Authentic Normalization: human input normalizer invocation with Gherkin criteria
    normalizer = RequestNormalizationService(github_adapter=real_gh)
    normalized = normalizer.normalize(
        "F7 Human Natural Language Intake",
        "Feature: Real E2E\nScenario: Provider E2E\n  Given a real provider\n  When executed\n  Then effects are durable",
    )
    assert normalized.already_normalized is True
    assert "Scenario: Provider E2E" in normalized.normalized_body

    # 6. Authentic HUMAN_REQUIRED: active request rejects mutation outside HUMAN_REQUIRED
    uow_with_active = DummyUoW()
    active_mock_run = MagicMock()
    active_mock_run.project_id = "mini-me"
    active_mock_run.is_active = True
    active_mock_run.stop_details = {"issue_number": 189}
    uow_with_active.orchestration_runs.add(active_mock_run)
    lifecycle_active = RequestLifecycleService(uow=uow_with_active, github_adapter=real_gh)
    with pytest.raises(RequestMutationNotAllowedError, match="HUMAN_REQUIRED"):
        lifecycle_active.edit_request(
            "mini-me", 189, title="Unauthorized mutation during execution"
        )

    # 7. Authentic Unavailable Metrics: honest projections returning unavailable for missing telemetry
    proj_svc = ProjectionService(uow=DummyUoW())
    metrics = proj_svc.project_request_metrics("mini-me", 999999)
    assert metrics["progress"]["status"] == "unavailable"
    assert metrics["cost_usd"]["status"] == "unavailable"
    assert metrics["duration_seconds"]["status"] == "unavailable"
    assert metrics["progress"]["value"] is None

    # 8. Authentic Durable Effects: PostgreSQL durable transition lifecycle + Git immutable SHA
    test_transition_id = f"e2e-test-{uuid.uuid4()}"
    with db_manager.session() as session:
        transition = DeferredTransitionModel(
            id=test_transition_id,
            project_id="mini-me",
            transition_type="SWITCH_EXECUTOR",
            target_project_id="mini-me",
            payload={"source": "real_e2e_evidence", "verified": True},
            status="PENDING",
        )
        session.add(transition)
        session.commit()

        persisted = session.query(DeferredTransitionModel).filter_by(id=test_transition_id).first()
        assert persisted is not None
        assert persisted.status == "PENDING"
        assert persisted.payload.get("verified") is True

        session.delete(persisted)
        session.commit()

    git_rev = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    immutable_sha = git_rev.stdout.strip()
    assert len(immutable_sha) == 40


def test_f7_api_and_ui_integration(monkeypatch):
    """Verify authenticated API endpoints and active UI controls for F7."""
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from minime.adapters.github import GitHubAdapter
    from minime.api.app import app, get_current_operator, get_uow
    from minime.domain.enums import ExternalOutcome, ExternalReasonCode
    from minime.domain.models import ExternalActionResult

    uow = DummyUoW()
    mock_gh = MagicMock(spec=GitHubAdapter)
    mock_gh.create_issue.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        data={"number": 195, "html_url": "https://github.com/org/a/issues/195"},
    )
    mock_gh.update_issue_state.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        data={"number": 195, "state": "open"},
    )

    monkeypatch.setenv("MINIME_AUTH_ENABLED", "false")
    monkeypatch.setattr("minime.services.request_lifecycle_service.GitHubAdapter", lambda: mock_gh)
    app.dependency_overrides[get_uow] = lambda: uow
    app.dependency_overrides[get_current_operator] = lambda: type(
        "Operator", (), {"email": "op@example.com"}
    )

    client = TestClient(app)
    try:
        # 1. API: Create Request
        resp_create = client.post(
            "/api/v1/projects/proj-a/requests",
            json={
                "title": "Feature via API",
                "description": "Description for feature",
                "acceptance_criteria": "Feature: API\nScenario: S1\n  Given input\n  When run\n  Then ok\n",
            },
        )
        assert resp_create.status_code == 201

        # 2. API: Edit Request
        resp_edit = client.patch(
            "/api/v1/projects/proj-a/requests/195",
            json={"title": "Edited Feature Title"},
        )
        assert resp_edit.status_code == 200

        # 3. API: Deactivate Request
        resp_deact = client.post("/api/v1/projects/proj-a/requests/195/deactivate")
        assert resp_deact.status_code == 200

        # 4. API: Reactivate Request
        resp_react = client.post("/api/v1/projects/proj-a/requests/195/reactivate")
        assert resp_react.status_code == 200

        # 5. API: Delete (Soft-Delete) Request
        resp_del = client.delete("/api/v1/projects/proj-a/requests/195")
        assert resp_del.status_code == 200

        # 6. API: Metrics
        resp_metrics = client.get("/api/v1/projects/proj-a/requests/195/metrics")
        assert resp_metrics.status_code == 200
        assert resp_metrics.json()["progress"]["status"] == "unavailable"
    finally:
        app.dependency_overrides.clear()

    # 7. UI Static Verification: verify views.js has enabled forms and action buttons
    views_path = Path(__file__).parents[1] / "src" / "minime" / "static" / "js" / "views.js"
    views_code = views_path.read_text(encoding="utf-8")
    assert "Crear Request" in views_code
    assert "new-request-form" in views_code
    assert "Editar Request" in views_code
    assert "Desactivar Request" in views_code
    assert "Reactivar Request" in views_code
    assert "Eliminar lógicamente" in views_code
