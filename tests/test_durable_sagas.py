"""Targeted adversarial unit and integration tests for Stage D Durable Intake and Closure Sagas."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from minime.domain.enums import (
    ChangeStatus,
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    QueuePriority,
    ReadinessState,
    SagaStatus,
    SagaType,
    WorkItemStatus,
)
from minime.domain.models import (
    BacklogItem,
    Change,
    DurableSaga,
    OrchestrationExternalAction,
)
from minime.services.post_merge_service import PostMergeReconciliationService
from minime.services.reconciliation_authority import ReconciliationAuthority
from minime.services.restart_recovery_service import RestartRecoveryService
from minime.services.saga_engine import SagaEngine


class InMemoryDurableSagaRepository:
    def __init__(self):
        self._sagas: dict[str, DurableSaga] = {}

    def save(self, saga: DurableSaga) -> None:
        self._sagas[saga.id] = saga

    def get_by_id(self, saga_id: str) -> DurableSaga | None:
        return self._sagas.get(saga_id)

    def get_active_saga(self, project_id: str, work_item_key: str, saga_type: SagaType | str) -> DurableSaga | None:
        st_val = saga_type.value if isinstance(saga_type, SagaType) else saga_type
        for s in self._sagas.values():
            if s.project_id == project_id and s.work_item_key == work_item_key and s.saga_type.value == st_val:
                if s.status in {SagaStatus.IN_PROGRESS, SagaStatus.BLOCKED}:
                    return s
        return None

    def list_by_project(self, project_id: str, saga_type: SagaType | str | None = None, status: SagaStatus | str | None = None) -> list[DurableSaga]:
        res = [s for s in self._sagas.values() if s.project_id == project_id]
        if saga_type:
            st_val = saga_type.value if isinstance(saga_type, SagaType) else saga_type
            res = [s for s in res if s.saga_type.value == st_val]
        if status:
            stat_val = status.value if isinstance(status, SagaStatus) else status
            res = [s for s in res if s.status.value == stat_val]
        return res

    def list_active(self, saga_type: SagaType | str | None = None) -> list[DurableSaga]:
        res = [s for s in self._sagas.values() if s.status in {SagaStatus.IN_PROGRESS, SagaStatus.BLOCKED}]
        if saga_type:
            st_val = saga_type.value if isinstance(saga_type, SagaType) else saga_type
            res = [s for s in res if s.saga_type.value == st_val]
        return res

    def update_phase(self, saga_id: str, current_phase: str, evidence_references: dict | None = None, last_observed_outcome: Any | None = None) -> DurableSaga:
        saga = self._sagas[saga_id]
        refs = dict(saga.evidence_references)
        if evidence_references:
            refs.update(evidence_references)
        updated = saga.model_copy(update={"current_phase": current_phase, "evidence_references": refs, "last_observed_outcome": last_observed_outcome})
        self._sagas[saga_id] = updated
        return updated

    def update_status(self, saga_id: str, status: SagaStatus | str, blocking_reason: str | None = None, last_observed_outcome: Any | None = None) -> DurableSaga:
        saga = self._sagas[saga_id]
        st_enum = SagaStatus(status) if isinstance(status, str) else status
        updated = saga.model_copy(update={"status": st_enum, "blocking_reason": blocking_reason, "last_observed_outcome": last_observed_outcome})
        self._sagas[saga_id] = updated
        return updated


class InMemoryExternalActionRepository:
    def __init__(self):
        self._actions: dict[str, OrchestrationExternalAction] = {}

    def reserve(self, action: OrchestrationExternalAction) -> None:
        self._actions[action.action_key] = action

    def get_by_action_key(self, action_key: str) -> OrchestrationExternalAction | None:
        return self._actions.get(action_key)

    def list_by_run(self, run_id: str) -> list[OrchestrationExternalAction]:
        return [a for a in self._actions.values() if a.run_id == run_id]

    def list_by_saga(self, saga_id: str) -> list[OrchestrationExternalAction]:
        return [a for a in self._actions.values() if a.saga_id == saga_id]

    def update_status(self, action_key: str, status: ExternalActionStatus, remote_identifier: str | None = None, result_payload: dict | None = None, error_message: str | None = None) -> OrchestrationExternalAction:
        act = self._actions[action_key]
        updated = act.model_copy(update={"status": status, "remote_identifier": remote_identifier, "result_payload": result_payload or {}, "error_message": error_message})
        self._actions[action_key] = updated
        return updated

    def reconcile_observe_before_repeat(self, action_key: str, observed_result: Any, original_mutation_retry_authorized: bool = False) -> OrchestrationExternalAction:
        act = self._actions.get(action_key)
        if not act:
            raise ValueError(f"Action '{action_key}' not found.")
        if observed_result.outcome == ExternalOutcome.SUCCESS:
            updated = act.model_copy(update={"status": ExternalActionStatus.COMPLETED, "remote_identifier": observed_result.remote_identifier or act.remote_identifier})
            self._actions[action_key] = updated
            return updated
        return act


class DummyUOW:
    def __init__(self):
        self.durable_sagas = InMemoryDurableSagaRepository()
        self.orchestration_external_actions = InMemoryExternalActionRepository()
        self.events = MagicMock()
        self.backlog_items = MagicMock()
        self.changes = MagicMock()
        self.projects = MagicMock()
        self.bindings = MagicMock()
        self.work_queue = MagicMock()
        self.orchestration_runs = MagicMock()
        self.jobs = MagicMock()
        self.git_operations = MagicMock()
        self.git_operations.list_by_job.return_value = []
        self.git_operations.list_by_worktree.return_value = []
        self.job_handoffs = MagicMock()
        self.job_handoffs.list_by_job.return_value = []
        self.check_results = MagicMock()
        self.check_results.list_by_job.return_value = []

    def commit(self):
        pass


# 1. Ownership Invariant Verification
def test_action_ownership_invariant():
    """Verify OrchestrationExternalAction raises ValueError when neither run_id nor saga_id is set."""
    with pytest.raises(ValueError, match="must have at least run_id or saga_id set"):
        OrchestrationExternalAction(
            run_id=None,
            saga_id=None,
            action_key="test_key",
            action_type=ExternalActionType.ISSUE_CREATE,
            target_identity="target",
            request_fingerprint="fp",
        )

    # Valid run_id
    act_run = OrchestrationExternalAction(
        run_id="run_123",
        saga_id=None,
        action_key="test_run_key",
        action_type=ExternalActionType.ISSUE_CREATE,
        target_identity="target",
        request_fingerprint="fp",
    )
    assert act_run.run_id == "run_123"

    # Valid saga_id
    act_saga = OrchestrationExternalAction(
        run_id=None,
        saga_id="saga_456",
        action_key="test_saga_key",
        action_type=ExternalActionType.ISSUE_CREATE,
        target_identity="target",
        request_fingerprint="fp",
    )
    assert act_saga.saga_id == "saga_456"


# 2. Single External Action Authority Verification
def test_single_external_action_authority():
    """Verify both run-bound and saga-bound actions are stored in OrchestrationExternalAction repository."""
    uow = DummyUOW()
    engine = SagaEngine(uow)

    # Saga action
    saga_act = engine.reserve_action(
        action_key="issue_create:proj:feat",
        action_type=ExternalActionType.ISSUE_CREATE,
        target_identity="feat",
        request_fingerprint="fp",
        saga_id="saga_001",
    )
    assert saga_act.saga_id == "saga_001"
    assert saga_act.status == ExternalActionStatus.RESERVED

    # Run action
    run_act = engine.reserve_action(
        action_key="issue_close:proj:feat",
        action_type=ExternalActionType.ISSUE_CLOSE,
        target_identity="feat",
        request_fingerprint="fp",
        run_id="run_001",
    )
    assert run_act.run_id == "run_001"
    assert run_act.status == ExternalActionStatus.RESERVED

    all_saga_actions = uow.orchestration_external_actions.list_by_saga("saga_001")
    assert len(all_saga_actions) == 1
    assert all_saga_actions[0].action_key == "issue_create:proj:feat"


# 3. Canonical Persisted Status Verification
def test_forbidden_persisted_statuses():
    """Verify attempting to record non-canonical status (e.g. SUCCESS or RECONCILED) raises ValueError."""
    uow = DummyUOW()
    engine = SagaEngine(uow)
    engine.reserve_action(
        action_key="test_act",
        action_type=ExternalActionType.ISSUE_CLOSE,
        target_identity="t",
        request_fingerprint="f",
        saga_id="s1",
    )

    with pytest.raises(ValueError, match="not a valid ExternalActionStatus|Invalid external action status"):
        engine.record_action_result("test_act", status="SUCCESS")

    with pytest.raises(ValueError, match="not a valid ExternalActionStatus|Invalid external action status"):
        engine.record_action_result("test_act", status="RECONCILED")

    # Valid status
    rec = engine.record_action_result("test_act", status=ExternalActionStatus.COMPLETED)
    assert rec.status == ExternalActionStatus.COMPLETED


# 4. Stage B Comment Marker Issue Matching
def test_stage_b_issue_comment_marker_matching():
    """Verify Issue reconciliation matches exact comment marker and forbids title-only matching."""
    uow = DummyUOW()
    uow.orchestration_external_actions.reserve(
        OrchestrationExternalAction(
            saga_id="s1",
            action_key="issue_create:p:c",
            action_type=ExternalActionType.ISSUE_CREATE,
            target_identity="c",
            request_fingerprint="fp",
            status=ExternalActionStatus.RESERVED,
        )
    )
    rec_auth = ReconciliationAuthority(uow)
    gh_mock = MagicMock()

    # Issue with matching marker comment
    gh_mock.search_issues_by_marker.return_value = [
        {"number": 42, "html_url": "http://gh/issue/42", "body": "<!-- minime-opkey: issue_create:p:c -->\nIssue body"}
    ]

    res = rec_auth.reconcile_issue_creation(
        github_adapter=gh_mock,
        repository="owner/repo",
        operation_key="issue_create:p:c",
        title="[c] Feature",
    )
    assert res.outcome == ExternalOutcome.SUCCESS
    assert res.data["number"] == 42
    # Verify exact marker search was called, NOT title search
    gh_mock.search_issues_by_marker.assert_called_once_with("owner/repo", "issue_create:p:c")


# 5. Stage B Project Item URL Lookup Matching
def test_stage_b_project_item_url_lookup():
    """Verify Project Item reconciliation uses exact issue URL lookup and forbids title search."""
    uow = DummyUOW()
    uow.orchestration_external_actions.reserve(
        OrchestrationExternalAction(
            saga_id="s1",
            action_key="project_item_add:p:c",
            action_type=ExternalActionType.PROJECT_ITEM_ADD,
            target_identity="c",
            request_fingerprint="fp",
            status=ExternalActionStatus.RESERVED,
        )
    )
    rec_auth = ReconciliationAuthority(uow)
    gh_mock = MagicMock()
    gh_mock.lookup_project_item_id_by_issue_url.return_value = "pvti_123"

    res = rec_auth.reconcile_project_item_add(
        github_adapter=gh_mock,
        project_number=1,
        owner="owner",
        issue_url="http://gh/issue/42",
        operation_key="project_item_add:p:c",
    )
    assert res.outcome == ExternalOutcome.SUCCESS
    assert res.data == "pvti_123"
    gh_mock.lookup_project_item_id_by_issue_url.assert_called_once_with(1, "owner", "http://gh/issue/42")


# 6. Squash Merge Delivery Verification
def test_squash_merge_delivery_verification(tmp_path, monkeypatch):
    """Verify candidate delivery verification supports squash merges where PR head SHA matches candidate SHA."""
    uow = DummyUOW()
    svc = PostMergeReconciliationService(uow, project_root=tmp_path)

    gh_mock = MagicMock()
    gh_mock.get_pull_request_merge_details.return_value = {
        "is_merged": True,
        "merged_by": "octocat",
        "head_sha": "cand_sha_123",
        "base_branch": "main",
        "merge_commit_sha": "squash_commit_sha_456",
    }
    svc.github_adapter = gh_mock
    svc._authorize_managed_repo_mutation = MagicMock()
    svc.verify_candidate_ancestry = MagicMock(return_value=False)

    import subprocess
    mock_run = MagicMock()
    mock_run.returncode = 0
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_run)

    verif = svc.verify_candidate_delivery(
        candidate_sha="cand_sha_123",
        base_branch="main",
        project_id="p1",
        pr_details=gh_mock.get_pull_request_merge_details.return_value,
    )
    assert verif is True


# 7. Intake Saga Restart at Every Phase
def test_intake_saga_restart_at_every_phase(tmp_path):
    """Verify intake saga can safely restart from any of its 7 phases."""
    phases = [
        "INTAKE_CREATED",
        "CONTEXT_CHECKED",
        "OPENSPEC_AUTHORED",
        "ISSUE_BOUND",
        "PROJECT_ITEM_BOUND",
        "READINESS_EVALUATED",
        "READY",
    ]
    for phase in phases:
        uow = DummyUOW()
        engine = SagaEngine(uow)
        saga = engine.start_saga(
            saga_type=SagaType.INTAKE,
            project_id="proj",
            work_item_key="item_key",
            change_name="item_key",
            initial_phase=phase,
        )
        assert saga.current_phase == phase

        # Resume saga
        resumed = engine.resume_saga(saga.id)
        assert resumed.id == saga.id


# 8. Closure Saga Restart at Every Phase
def test_closure_saga_restart_at_every_phase():
    """Verify closure saga can safely restart from any of its 13 phases."""
    phases = [
        "CLOSURE_CREATED",
        "MERGE_OBSERVED",
        "MERGED_DELIVERY_VERIFIED",
        "RUN_JOB_RECONCILED",
        "ISSUE_CLOSED",
        "PROJECT_ITEM_DONE",
        "SPEC_SYNCED",
        "SYNC_VERIFIED",
        "SPEC_ARCHIVED",
        "ARCHIVE_VERIFIED",
        "WORKTREE_CLEANED",
        "BRANCH_CLEANED",
        "FINAL_CLOSED",
    ]
    for phase in phases:
        uow = DummyUOW()
        engine = SagaEngine(uow)
        saga = engine.start_saga(
            saga_type=SagaType.CLOSURE,
            project_id="proj",
            work_item_key="item_key",
            change_name="item_key",
            initial_phase=phase,
        )
        assert saga.current_phase == phase

        resumed = engine.resume_saga(saga.id)
        assert resumed.id == saga.id


# 9. Terminal Domain Reconciliation Mode Verification
def test_terminal_domain_reconciliation_mode():
    """Verify terminal domain states with incomplete saga evidence enter reconciliation mode without resurrecting work."""
    uow = DummyUOW()
    engine = SagaEngine(uow)

    # Set change as DONE but closure saga is incomplete
    uow.changes.get_by_name.return_value = Change(
        project_id="p1",
        name="c1",
        status=ChangeStatus.DONE,
        proposal_path="p",
        tasks_path="t",
        design_path="d",
    )
    uow.backlog_items.get_by_project_and_key.return_value = BacklogItem(
        project_id="p1",
        item_key="c1",
        title="Title",
        description="Desc",
        priority=QueuePriority.HIGH,
        status=WorkItemStatus.COMPLETED,
        readiness_state=ReadinessState.READY,
        openspec_change_name="c1",
    )
    uow.jobs.list_active_jobs.return_value = []
    uow.orchestration_runs.list_runs.return_value = []

    _saga = engine.start_saga(
        saga_type=SagaType.CLOSURE,
        project_id="p1",
        work_item_key="c1",
        change_name="c1",
        initial_phase="ISSUE_CLOSED",
    )

    recovery = RestartRecoveryService(uow, project_root=".")
    reconciled = recovery.reconcile_durable_sagas()
    assert len(reconciled) == 1


# 10. Terminal Identity Protection during Intake
def test_terminal_identity_protection_intake():
    """Verify intake saga for terminal backlog item completes without re-opening work."""
    uow = DummyUOW()
    engine = SagaEngine(uow)

    uow.backlog_items.get_by_project_and_key.return_value = BacklogItem(
        project_id="p1",
        item_key="k1",
        title="Title",
        description="Desc",
        priority=QueuePriority.NORMAL,
        status=WorkItemStatus.COMPLETED,
        readiness_state=ReadinessState.READY,
        openspec_change_name="k1",
    )

    _saga = engine.start_saga(
        saga_type=SagaType.INTAKE,
        project_id="p1",
        work_item_key="k1",
        change_name="k1",
        initial_phase="INTAKE_CREATED",
    )

    recovery = RestartRecoveryService(uow, project_root=".")
    reconciled = recovery.reconcile_durable_sagas()
    assert len(reconciled) == 1
    assert reconciled[0].status == SagaStatus.COMPLETED


# 11. Repeated Resume Idempotency
def test_repeated_resume_idempotency():
    """Verify calling resume_saga multiple times is idempotent."""
    uow = DummyUOW()
    engine = SagaEngine(uow)
    saga = engine.start_saga(
        saga_type=SagaType.INTAKE,
        project_id="p1",
        work_item_key="k1",
        change_name="k1",
    )

    res1 = engine.resume_saga(saga.id)
    res2 = engine.resume_saga(saga.id)
    res3 = engine.resume_saga(saga.id)

    assert res1.id == res2.id == res3.id == saga.id
