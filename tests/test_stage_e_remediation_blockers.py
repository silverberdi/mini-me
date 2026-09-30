"""Adversarial test suite verifying resolution of Stage E independent review blockers.

Blocker 1: Pure readiness invokes pure workspace classification without writing MetricFact.
Blocker 2: CANCELLED Change is projected as terminal CANCELLED and never resurrected.
Blocker 3: Provider capacity observation exception fails closed to NOT_READY with zero writes.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from minime.api.app import app, get_uow
from minime.domain.enums import (
    ChangeStatus,
    OrchestrationStage,
    ProjectStatus,
    ProviderHealthStatus,
    ReadinessState,
    WorkItemStatus,
    WorkspaceOperation,
)
from minime.domain.models import (
    BacklogItem,
    Change,
    OrchestrationRun,
    Project,
    ProjectManagedRepositoryBinding,
    ProviderHealth,
    WorkspaceMutationRequest,
    utc_now,
)
from minime.services.dashboard_service import OperationsDashboardService
from minime.services.intake_service import IntakeService
from minime.services.provider_health_service import ProviderHealthService
from minime.services.readiness_service import ReadinessService
from minime.services.workspace_guard import ManagedWorkspaceGuard

# -----------------------------------------------------------------------------
# BLOCKER 1 TESTS: Pure Readiness & Workspace Guard Purity
# -----------------------------------------------------------------------------


def test_pure_readiness_with_allowed_workspace_classification(in_memory_uow, tmp_path):
    """Verify pure readiness with valid managed binding executes zero writes."""
    uow = in_memory_uow

    proj = Project(
        project_id="p-b1-allowed",
        display_name="Allowed Workspace Test",
        repository="owner/repo",
        base_branch="main",
        status=ProjectStatus.ACTIVE,
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(proj)

    managed_root = tmp_path / "managed_repo"
    wt_parent = tmp_path / "worktrees"
    managed_root.mkdir(parents=True, exist_ok=True)
    wt_parent.mkdir(parents=True, exist_ok=True)

    binding = ProjectManagedRepositoryBinding(
        project_id="p-b1-allowed",
        canonical_repository_identity="github.com/owner/repo",
        managed_repository_root=str(managed_root),
        worktree_parent_dir=str(wt_parent),
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.commit()
    uow.committed = False

    facts_before = len(uow.metrics.list_facts())

    service = ReadinessService(uow)
    result = service.evaluate_change_readiness_pure(
        project_id="p-b1-allowed",
        change_name="change-b1-allowed",
        project_root=str(tmp_path),
    )

    assert result.change_id == "change-b1-allowed"
    assert uow.committed is False
    assert len(uow.metrics.list_facts()) == facts_before


def test_pure_readiness_with_denied_workspace_classification(in_memory_uow, tmp_path, monkeypatch):
    """Verify pure readiness with denied workspace classification returns NOT_READY with zero MetricFact writes."""
    uow = in_memory_uow

    proj = Project(
        project_id="p-b1-denied",
        display_name="Denied Workspace Test",
        repository="owner/repo",
        base_branch="main",
        status=ProjectStatus.ACTIVE,
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(proj)

    # Set up managed root outside trusted managed root to trigger POLICY_DENIED classification
    trusted_root = tmp_path / "trusted"
    untrusted_root = tmp_path / "untrusted" / "managed_repo"
    wt_parent = trusted_root / "worktrees"
    trusted_root.mkdir(parents=True, exist_ok=True)
    untrusted_root.mkdir(parents=True, exist_ok=True)
    wt_parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("MINIME_MANAGED_ROOT", str(trusted_root))

    binding = ProjectManagedRepositoryBinding(
        project_id="p-b1-denied",
        canonical_repository_identity="github.com/owner/repo",
        managed_repository_root=str(untrusted_root),
        worktree_parent_dir=str(wt_parent),
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.commit()
    uow.committed = False

    facts_before = len(uow.metrics.list_facts())
    events_before = len(uow.events.list_events(limit=100))

    service = ReadinessService(uow)
    result = service.evaluate_change_readiness_pure(
        project_id="p-b1-denied",
        change_name="change-b1-denied",
        project_root=str(tmp_path),
    )

    assert result.status == ReadinessState.NOT_READY
    assert any("Stage C Admission Fence" in r for r in result.unmet_reasons)
    assert any("escapes trusted managed root" in r for r in result.unmet_reasons)

    # Assert ZERO MetricFact writes, ZERO events, ZERO commits
    assert len(uow.metrics.list_facts()) == facts_before
    assert len(uow.events.list_events(limit=100)) == events_before
    assert uow.committed is False


def test_http_get_readiness_route_denied_workspace_classification_remains_pure(
    in_memory_uow, tmp_path, monkeypatch
):
    """Verify HTTP GET /readiness route with denied workspace classification remains 100% pure."""
    uow = in_memory_uow

    proj = Project(
        project_id="p-b1-http-denied",
        display_name="HTTP Denied Workspace Test",
        repository="owner/repo",
        base_branch="main",
        status=ProjectStatus.ACTIVE,
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(proj)

    trusted_root = tmp_path / "trusted_http"
    untrusted_root = tmp_path / "untrusted_http" / "managed_repo"
    wt_parent = trusted_root / "worktrees"
    trusted_root.mkdir(parents=True, exist_ok=True)
    untrusted_root.mkdir(parents=True, exist_ok=True)
    wt_parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("MINIME_MANAGED_ROOT", str(trusted_root))

    binding = ProjectManagedRepositoryBinding(
        project_id="p-b1-http-denied",
        canonical_repository_identity="github.com/owner/repo",
        managed_repository_root=str(untrusted_root),
        worktree_parent_dir=str(wt_parent),
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)
    uow.commit()
    uow.committed = False

    def _get_uow_override():
        return uow

    app.dependency_overrides[get_uow] = _get_uow_override
    client = TestClient(app)

    facts_before = len(uow.metrics.list_facts())

    response = client.get(
        f"/projects/p-b1-http-denied/changes/change-http-denied/readiness?project_root={tmp_path}"
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NOT_READY"

    # Zero MetricFact writes and zero commits
    assert len(uow.metrics.list_facts()) == facts_before
    assert uow.committed is False


def test_command_mutation_enforcement_records_denial_telemetry_regression(
    in_memory_uow, tmp_path, monkeypatch
):
    """Regression test proving command-side evaluate_mutation still records workspace_mutation_denied_total metric."""
    uow = in_memory_uow

    proj = Project(
        project_id="p-b1-cmd-denied",
        display_name="Command Denied Test",
        repository="owner/repo",
    )
    uow.projects.save(proj)

    trusted_root = tmp_path / "trusted_cmd"
    untrusted_root = tmp_path / "untrusted_cmd" / "managed_repo"
    wt_parent = trusted_root / "worktrees"
    trusted_root.mkdir(parents=True, exist_ok=True)
    untrusted_root.mkdir(parents=True, exist_ok=True)
    wt_parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("MINIME_MANAGED_ROOT", str(trusted_root))

    binding = ProjectManagedRepositoryBinding(
        project_id="p-b1-cmd-denied",
        canonical_repository_identity="github.com/owner/repo",
        managed_repository_root=str(untrusted_root),
        worktree_parent_dir=str(wt_parent),
        is_valid=True,
    )
    uow.project_managed_repository_bindings.save(binding)

    guard = ManagedWorkspaceGuard(uow, trusted_managed_root=str(trusted_root))
    cmd_req = WorkspaceMutationRequest(
        project_id="p-b1-cmd-denied",
        target_path=str(untrusted_root / "file.py"),
        requested_operation=WorkspaceOperation.EDIT,
    )
    decision = guard.evaluate_mutation(cmd_req)

    assert decision.allowed is False
    # Command evaluation MUST record metric fact
    facts = uow.metrics.list_facts()
    denied_facts = [f for f in facts if f.metric_name == "workspace_mutation_denied_total"]
    assert len(denied_facts) == 1
    assert denied_facts[0].project_id == "p-b1-cmd-denied"


# -----------------------------------------------------------------------------
# BLOCKER 2 TESTS: Cancelled Change Dashboard Projection Precedence
# -----------------------------------------------------------------------------


def test_cancelled_change_no_run_projection(in_memory_uow):
    """Verify Change=CANCELLED with no run projects as CANCELLED and leaves canonical DB intact."""
    uow = in_memory_uow

    proj = Project(
        project_id="p-b2-cancelled",
        display_name="Cancelled Test",
        repository="owner/repo",
    )
    uow.projects.save(proj)

    change = Change(
        project_id="p-b2-cancelled",
        name="change-cancelled-no-run",
        status=ChangeStatus.CANCELLED,
        last_readiness_status=ReadinessState.READY,
    )
    uow.changes.save(change)
    uow.commit()
    uow.committed = False

    dash_svc = OperationsDashboardService(uow)
    overview = dash_svc.get_overview()

    c_summary = next(
        (c for c in overview.changes if c.change_name == "change-cancelled-no-run"), None
    )
    assert c_summary is not None
    assert c_summary.status == "CANCELLED"

    detail = dash_svc.get_change_detail("p-b2-cancelled", "change-cancelled-no-run")
    assert detail is not None
    assert detail.status == "CANCELLED"

    db_change = uow.changes.get_by_name("p-b2-cancelled", "change-cancelled-no-run")
    assert db_change.status == ChangeStatus.CANCELLED
    assert uow.committed is False


def test_cancelled_change_stale_active_run_projection(in_memory_uow):
    """Verify Change=CANCELLED with a stale active run remains CANCELLED and is not resurrected."""
    uow = in_memory_uow
    now = utc_now()

    proj = Project(
        project_id="p-b2-stale-run",
        display_name="Stale Run Test",
        repository="owner/repo",
    )
    uow.projects.save(proj)

    change = Change(
        project_id="p-b2-stale-run",
        name="change-cancelled-stale-run",
        status=ChangeStatus.CANCELLED,
        last_readiness_status=ReadinessState.READY,
    )
    uow.changes.save(change)

    stale_run = OrchestrationRun(
        run_id="run-stale-active",
        project_id="p-b2-stale-run",
        change_name="change-cancelled-stale-run",
        base_sha="main",
        current_stage=OrchestrationStage.IMPLEMENTING,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    uow.orchestration_runs.save(stale_run)
    uow.commit()
    uow.committed = False

    dash_svc = OperationsDashboardService(uow)
    overview = dash_svc.get_overview()

    c_summary = next(
        (c for c in overview.changes if c.change_name == "change-cancelled-stale-run"), None
    )
    assert c_summary is not None
    assert c_summary.status == "CANCELLED"

    # Active executions list MUST NOT contain the run for the cancelled change
    active_run_ids = [a.run_id for a in overview.active_executions]
    assert "run-stale-active" not in active_run_ids

    detail = dash_svc.get_change_detail("p-b2-stale-run", "change-cancelled-stale-run")
    assert detail is not None
    assert detail.status == "CANCELLED"

    db_change = uow.changes.get_by_name("p-b2-stale-run", "change-cancelled-stale-run")
    assert db_change.status == ChangeStatus.CANCELLED
    assert uow.committed is False


def test_cancelled_change_repeated_reads_preserves_terminal_state(in_memory_uow):
    """Verify repeated overview and detail queries preserve terminal CANCELLED state and commit zero times."""
    uow = in_memory_uow

    proj = Project(
        project_id="p-b2-repeat",
        display_name="Repeated Read Test",
        repository="owner/repo",
    )
    uow.projects.save(proj)

    change = Change(
        project_id="p-b2-repeat",
        name="change-repeat-cancelled",
        status=ChangeStatus.CANCELLED,
    )
    uow.changes.save(change)
    uow.commit()
    uow.committed = False

    dash_svc = OperationsDashboardService(uow)

    for _ in range(5):
        overview = dash_svc.get_overview()
        c_summary = next(
            (c for c in overview.changes if c.change_name == "change-repeat-cancelled"), None
        )
        assert c_summary.status == "CANCELLED"

        detail = dash_svc.get_change_detail("p-b2-repeat", "change-repeat-cancelled")
        assert detail.status == "CANCELLED"

    db_change = uow.changes.get_by_name("p-b2-repeat", "change-repeat-cancelled")
    assert db_change.status == ChangeStatus.CANCELLED
    assert uow.committed is False


def test_cancelled_backlog_item_projection(in_memory_uow):
    """Verify BacklogItem with CANCELLED status or parent CANCELLED change remains CANCELLED."""
    uow = in_memory_uow

    proj = Project(
        project_id="p-b2-backlog",
        display_name="Backlog Projection Test",
        repository="owner/repo",
    )
    uow.projects.save(proj)

    item1 = BacklogItem(
        project_id="p-b2-backlog",
        item_key="item-cancelled-direct",
        title="Directly Cancelled Item",
        status=WorkItemStatus.CANCELLED,
    )
    uow.backlog_items.save(item1)

    item2 = BacklogItem(
        project_id="p-b2-backlog",
        item_key="item-cancelled-parent",
        title="Item With Cancelled Parent",
        status=WorkItemStatus.BACKLOG,
    )
    uow.backlog_items.save(item2)

    parent_change = Change(
        project_id="p-b2-backlog",
        name="item-cancelled-parent",
        status=ChangeStatus.CANCELLED,
    )
    uow.changes.save(parent_change)
    uow.commit()
    uow.committed = False

    intake_svc = IntakeService(uow)
    projected = intake_svc.reconcile_backlog_projections("p-b2-backlog")

    projected_dict = {p.item_key: p.status for p in projected}
    assert projected_dict["item-cancelled-direct"] == WorkItemStatus.CANCELLED
    assert projected_dict["item-cancelled-parent"] == WorkItemStatus.CANCELLED
    assert uow.committed is False


# -----------------------------------------------------------------------------
# BLOCKER 3 TESTS: Capacity Observation Exception Fails Closed
# -----------------------------------------------------------------------------


def test_capacity_observation_exception_fails_closed(in_memory_uow, tmp_path, monkeypatch):
    """Verify capacity observation exception returns NOT_READY with explicit failed check and zero writes."""
    uow = in_memory_uow

    proj = Project(
        project_id="p-b3-exc",
        display_name="Capacity Exception Test",
        repository="owner/repo",
        base_branch="main",
        status=ProjectStatus.ACTIVE,
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(proj)
    uow.commit()
    uow.committed = False

    def mock_is_pair_available(implementer, reviewer):
        raise RuntimeError("Provider API timeout connecting to host secret_host_98765")

    monkeypatch.setattr(ProviderHealthService, "is_pair_available", mock_is_pair_available)

    facts_before = len(uow.metrics.list_facts())
    events_before = len(uow.events.list_events(limit=100))

    service = ReadinessService(uow)
    result = service.evaluate_change_readiness_pure(
        project_id="p-b3-exc",
        change_name="change-capacity-exc",
        project_root=str(tmp_path),
    )

    assert result.status == ReadinessState.NOT_READY

    # Assert primary_capacity check exists and failed
    cap_check = next((c for c in result.checks if c.name == "primary_capacity"), None)
    assert cap_check is not None
    assert cap_check.passed is False
    assert "Primary pair capacity unavailable/unobservable" in cap_check.reason
    assert "secret_host_98765" not in cap_check.reason  # Verify secret redaction

    # Assert reason in unmet_reasons
    assert any("Primary pair capacity unavailable/unobservable" in r for r in result.unmet_reasons)

    # Assert ZERO provider health writes, ZERO MetricFact writes, ZERO Event writes, ZERO commits
    assert len(uow.metrics.list_facts()) == facts_before
    assert len(uow.events.list_events(limit=100)) == events_before
    assert uow.committed is False


def test_capacity_observation_persisted_available_pair_passes(in_memory_uow, tmp_path):
    """Verify persisted AVAILABLE provider pair passes primary capacity check."""
    uow = in_memory_uow
    now = utc_now()

    proj = Project(
        project_id="p-b3-avail",
        display_name="Capacity Available Test",
        repository="owner/repo",
        base_branch="main",
        status=ProjectStatus.ACTIVE,
        implementer="codex",
        reviewer="antigravity",
    )
    uow.projects.save(proj)

    for prov in ["codex", "antigravity"]:
        uow.provider_health.save(
            ProviderHealth(
                health_id=f"ph-b3-{prov}",
                provider=prov,
                status=ProviderHealthStatus.AVAILABLE,
                updated_at=now,
            )
        )
    uow.commit()
    uow.committed = False

    service = ReadinessService(uow)
    result = service.evaluate_change_readiness_pure(
        project_id="p-b3-avail",
        change_name="change-capacity-avail",
        project_root=str(tmp_path),
    )

    cap_check = next((c for c in result.checks if c.name == "primary_capacity"), None)
    assert cap_check is not None
    assert cap_check.passed is True
    assert uow.committed is False
