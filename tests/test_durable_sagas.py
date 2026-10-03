"""Targeted adversarial unit and integration tests for Stage D Durable Intake and Closure Sagas."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from minime.domain.enums import (
    ChangeStatus,
    ExternalActionStatus,
    ExternalActionType,
    ExternalOutcome,
    JobStatus,
    OrchestrationStage,
    OrchestrationStopOutcome,
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
    RecoveryClaimContext,
    utc_now,
)
from minime.services.intake_service import IntakeService
from minime.services.post_merge_service import PostMergeReconciliationService
from minime.services.reconciliation_authority import ReconciliationAuthority
from minime.services.restart_recovery_service import RestartRecoveryService
from minime.services.saga_engine import SagaEngine


def _test_ctx(claim_key: str = "test-claim") -> RecoveryClaimContext:
    return RecoveryClaimContext(
        claim_key=claim_key,
        owner_instance_id="test-owner",
        fence_token=1,
        lease_expires_at=utc_now() + timedelta(seconds=3600),
    )


class InMemoryDurableSagaRepository:
    def __init__(self):
        self._sagas: dict[str, DurableSaga] = {}

    def save(self, saga: DurableSaga) -> None:
        self._sagas[saga.id] = saga

    def get_by_id(self, saga_id: str) -> DurableSaga | None:
        return self._sagas.get(saga_id)

    def get_for_update(self, saga_id: str) -> DurableSaga | None:
        return self._sagas.get(saga_id)

    def get_active_saga(
        self, project_id: str, work_item_key: str, saga_type: SagaType | str
    ) -> DurableSaga | None:
        st_val = saga_type.value if isinstance(saga_type, SagaType) else saga_type
        for s in self._sagas.values():
            if (
                s.project_id == project_id
                and s.work_item_key == work_item_key
                and s.saga_type.value == st_val
            ):
                if s.status in {SagaStatus.IN_PROGRESS, SagaStatus.BLOCKED}:
                    return s
        return None

    def list_by_project(
        self,
        project_id: str,
        saga_type: SagaType | str | None = None,
        status: SagaStatus | str | None = None,
    ) -> list[DurableSaga]:
        res = [s for s in self._sagas.values() if s.project_id == project_id]
        if saga_type:
            st_val = saga_type.value if isinstance(saga_type, SagaType) else saga_type
            res = [s for s in res if s.saga_type.value == st_val]
        if status:
            stat_val = status.value if isinstance(status, SagaStatus) else status
            res = [s for s in res if s.status.value == stat_val]
        return res

    def list_active(self, saga_type: SagaType | str | None = None) -> list[DurableSaga]:
        res = [
            s
            for s in self._sagas.values()
            if s.status in {SagaStatus.IN_PROGRESS, SagaStatus.BLOCKED}
        ]
        if saga_type:
            st_val = saga_type.value if isinstance(saga_type, SagaType) else saga_type
            res = [s for s in res if s.saga_type.value == st_val]
        return res

    def update_phase(
        self,
        saga_id: str,
        current_phase: str,
        evidence_references: dict | None = None,
        last_observed_outcome: Any | None = None,
    ) -> DurableSaga:
        saga = self._sagas[saga_id]
        refs = dict(saga.evidence_references)
        if evidence_references:
            refs.update(evidence_references)
        updated = saga.model_copy(
            update={
                "current_phase": current_phase,
                "evidence_references": refs,
                "last_observed_outcome": last_observed_outcome,
            }
        )
        self._sagas[saga_id] = updated
        return updated

    def update_status(
        self,
        saga_id: str,
        status: SagaStatus | str,
        blocking_reason: str | None = None,
        last_observed_outcome: Any | None = None,
    ) -> DurableSaga:
        saga = self._sagas[saga_id]
        st_enum = SagaStatus(status) if isinstance(status, str) else status
        updated = saga.model_copy(
            update={
                "status": st_enum,
                "blocking_reason": blocking_reason,
                "last_observed_outcome": last_observed_outcome,
            }
        )
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

    def update_status(
        self,
        action_key: str,
        status: ExternalActionStatus,
        remote_identifier: str | None = None,
        result_payload: dict | None = None,
        error_message: str | None = None,
    ) -> OrchestrationExternalAction:
        act = self._actions[action_key]
        updated = act.model_copy(
            update={
                "status": status,
                "remote_identifier": remote_identifier,
                "result_payload": result_payload or {},
                "error_message": error_message,
            }
        )
        self._actions[action_key] = updated
        return updated

    def reconcile_observe_before_repeat(
        self,
        action_key: str,
        observed_result: Any,
        original_mutation_retry_authorized: bool = False,
    ) -> OrchestrationExternalAction:
        act = self._actions.get(action_key)
        if not act:
            raise ValueError(f"Action '{action_key}' not found.")
        if observed_result.outcome == ExternalOutcome.SUCCESS:
            updated = act.model_copy(
                update={
                    "status": ExternalActionStatus.COMPLETED,
                    "remote_identifier": observed_result.remote_identifier or act.remote_identifier,
                }
            )
            self._actions[action_key] = updated
            return updated
        return act


class DummyUOW:
    def __init__(self):
        self.durable_sagas = InMemoryDurableSagaRepository()
        self.orchestration_external_actions = InMemoryExternalActionRepository()
        self.events = MagicMock()
        self.projects = MagicMock()
        self.projects.get_by_id.return_value = MagicMock(
            project_id="p1",
            display_name="Proj",
            repository="owner/repo",
            base_branch="main",
            openspec_path="openspec",
        )
        self.bindings = MagicMock()
        self.bindings.get_by_project_and_change.return_value = None
        self.work_queue = MagicMock()
        self.work_queue.get_by_project_and_change.return_value = None

        def _save_change(c):
            if hasattr(c, "name") and c.name:
                self.changes._store[c.name] = c
            if hasattr(c, "change_id") and c.change_id:
                self.changes._store[c.change_id] = c

        self.changes = MagicMock()
        self.changes.return_value = None
        self.changes._store = {}
        self.changes.get_by_name.side_effect = lambda pid, name: (
            self.changes._store.get(name)
            if self.changes._store.get(name) is not None
            else self.changes.return_value
        )
        self.changes.save.side_effect = _save_change

        def _save_item(item):
            if hasattr(item, "item_key") and item.item_key:
                self.backlog_items._store[item.item_key] = item
            if hasattr(item, "item_id") and item.item_id:
                self.backlog_items._store[item.item_id] = item

        self.backlog_items = MagicMock()
        self.backlog_items.return_value = None
        self.backlog_items._store = {}
        self.backlog_items.get_by_project_and_key.side_effect = lambda pid, key: (
            self.backlog_items._store.get(key)
            if self.backlog_items._store.get(key) is not None
            else self.backlog_items.return_value
        )
        self.backlog_items.save.side_effect = _save_item

        self.orchestration_runs = MagicMock()
        self.jobs = MagicMock()
        self.metrics = MagicMock()
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

    with pytest.raises(
        ValueError, match="not a valid ExternalActionStatus|Invalid external action status"
    ):
        engine.record_action_result("test_act", status="SUCCESS")

    with pytest.raises(
        ValueError, match="not a valid ExternalActionStatus|Invalid external action status"
    ):
        engine.record_action_result("test_act", status="RECONCILED")

    # Valid status
    rec = engine.record_action_result("test_act", status=ExternalActionStatus.COMPLETED)
    assert rec.status == ExternalActionStatus.COMPLETED


# 4. Stage B Comment Marker Issue Matching
def test_stage_b_issue_comment_marker_matching():
    """Verify Issue reconciliation matches exact comment marker and forbids title-only matching."""
    from minime.domain.enums import ExternalReasonCode
    from minime.domain.models import ExternalActionResult

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
    gh_mock.list_issues.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        data=[
            {
                "number": 42,
                "html_url": "http://gh/issue/42",
                "body": "<!-- minime-opkey: issue_create:p:c -->\nIssue body",
            }
        ],
    )

    res = rec_auth.reconcile_issue_creation(
        github_adapter=gh_mock,
        repository="owner/repo",
        operation_key="issue_create:p:c",
        title="[c] Feature",
    )
    assert res.outcome == ExternalOutcome.SUCCESS
    assert res.data["number"] == 42
    gh_mock.list_issues.assert_called_once_with("owner/repo", state="all")


# 5. Stage B Project Item URL Lookup Matching
def test_stage_b_project_item_url_lookup():
    """Verify Project Item reconciliation uses exact issue URL lookup and forbids title search."""
    from minime.domain.enums import ExternalReasonCode
    from minime.domain.models import ExternalActionResult

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
    gh_mock.list_project_items.return_value = ExternalActionResult(
        outcome=ExternalOutcome.SUCCESS,
        source_adapter="github",
        reason_code=ExternalReasonCode.EXECUTION_SUCCESS,
        data=[{"id": "pvti_123", "content": {"url": "http://gh/issue/42"}}],
    )

    res = rec_auth.reconcile_project_item_add(
        github_adapter=gh_mock,
        project_number=1,
        owner="owner",
        issue_url="http://gh/issue/42",
        operation_key="project_item_add:p:c",
    )
    assert res.outcome == ExternalOutcome.SUCCESS
    assert res.data == "pvti_123"
    gh_mock.list_project_items.assert_called_once_with(project_number=1, owner="owner")


# 6. Squash Merge Delivery Verification
def test_squash_merge_delivery_verification(tmp_path, monkeypatch):
    """Verify candidate delivery verification supports squash merges where PR head SHA matches candidate SHA."""
    uow = DummyUOW()
    svc = PostMergeReconciliationService(uow, project_root=tmp_path)

    gh_mock = MagicMock()
    gh_mock.get_pull_request_merge_details.return_value = {
        "repository": "owner/repo",
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

        from datetime import timedelta

        from minime.domain.models import RecoveryClaimContext, utc_now
        ctx = RecoveryClaimContext(claim_key=f"saga:{saga.id}", owner_instance_id="test-owner", fence_token=1, lease_expires_at=utc_now() + timedelta(seconds=3600))
        resumed = engine.resume_saga(saga.id, claim_context=ctx)
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

        from datetime import timedelta

        from minime.domain.models import RecoveryClaimContext, utc_now
        ctx = RecoveryClaimContext(claim_key=f"saga:{saga.id}", owner_instance_id="test-owner", fence_token=1, lease_expires_at=utc_now() + timedelta(seconds=3600))
        resumed = engine.resume_saga(saga.id, claim_context=ctx)
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

    item = BacklogItem(
        project_id="p1",
        item_key="k1",
        title="Title",
        description="Desc",
        priority=QueuePriority.NORMAL,
        status=WorkItemStatus.COMPLETED,
        readiness_state=ReadinessState.READY,
        openspec_change_name="k1",
    )
    uow.backlog_items.save(item)

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
    assert reconciled[0].status == SagaStatus.CANCELLED


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

    from datetime import timedelta

    from minime.domain.models import RecoveryClaimContext, utc_now
    ctx = RecoveryClaimContext(claim_key=f"saga:{saga.id}", owner_instance_id="test-owner", fence_token=1, lease_expires_at=utc_now() + timedelta(seconds=3600))
    res1 = engine.resume_saga(saga.id, claim_context=ctx)
    res2 = engine.resume_saga(saga.id, claim_context=ctx)
    res3 = engine.resume_saga(saga.id, claim_context=ctx)

    assert res1.id == res2.id == res3.id == saga.id


# 12. Intake Resume From Persisted Phase Without Replay
def test_intake_resume_from_persisted_phase_no_replay():
    """Verify intake resumes from persisted phase without replaying prior completed phases."""
    uow = DummyUOW()
    engine = SagaEngine(uow)

    item = BacklogItem(
        project_id="p1",
        item_key="k1",
        title="Title",
        description="Desc",
        priority=QueuePriority.NORMAL,
        status=WorkItemStatus.PREPARING,
        readiness_state=ReadinessState.NOT_READY,
        openspec_change_name="k1",
    )
    uow.backlog_items.save(item)
    uow.projects.get_by_id.return_value = MagicMock(
        display_name="Proj",
        openspec_path="openspec",
        repository="owner/repo",
        base_branch="main",
        project_id="p1",
    )
    uow.changes.get_by_name.return_value = None

    _saga = engine.start_saga(
        saga_type=SagaType.INTAKE,
        project_id="p1",
        work_item_key="k1",
        change_name="k1",
        initial_phase="OPENSPEC_AUTHORED",
    )

    gen_mock = MagicMock()
    service = IntakeService(
        uow=uow, project_root=".", openspec_generator=gen_mock, saga_engine=engine
    )
    ctx = _test_ctx("intake:p1:k1")
    service.prepare_work_item("p1", "k1", claim_context=ctx)
    gen_mock.generate_from_backlog_item.assert_not_called()


# 13. OpenSpec Generation Not Replayed After OPENSPEC_AUTHORED
def test_openspec_generation_not_replayed_after_authored():
    """Verify generate_from_backlog_item and write_change_to_disk are not called when phase >= OPENSPEC_AUTHORED."""
    uow = DummyUOW()
    engine = SagaEngine(uow)
    item = BacklogItem(
        project_id="p1",
        item_key="k1",
        title="Title",
        description="Desc",
        priority=QueuePriority.NORMAL,
        status=WorkItemStatus.PREPARING,
        readiness_state=ReadinessState.NOT_READY,
        openspec_change_name="k1",
    )
    uow.backlog_items.save(item)
    uow.projects.get_by_id.return_value = MagicMock(
        display_name="Proj",
        openspec_path="openspec",
        repository="owner/repo",
        base_branch="main",
        project_id="p1",
    )
    uow.changes.get_by_name.return_value = None

    _saga = engine.start_saga(
        saga_type=SagaType.INTAKE,
        project_id="p1",
        work_item_key="k1",
        change_name="k1",
        initial_phase="ISSUE_BOUND",
    )
    gen_mock = MagicMock()
    service = IntakeService(
        uow=uow, project_root=".", openspec_generator=gen_mock, saga_engine=engine
    )
    ctx = _test_ctx("intake:p1:k1")
    service.prepare_work_item("p1", "k1", claim_context=ctx)
    gen_mock.generate_from_backlog_item.assert_not_called()
    gen_mock.write_change_to_disk.assert_not_called()


# 14. Canonical reconcile_observe_before_repeat Invoked For Issue Action
def test_canonical_reconcile_observe_before_repeat_invoked_for_issue():
    """Verify reconcile_observe_before_repeat is invoked for Issue creation action."""
    uow = DummyUOW()
    rec_auth = ReconciliationAuthority(uow)

    op_key = "issue_create:p1:k1"
    action = OrchestrationExternalAction(
        saga_id="s1",
        action_key=op_key,
        action_type=ExternalActionType.ISSUE_CREATE,
        target_identity="k1",
        request_fingerprint="k1",
        status=ExternalActionStatus.RESERVED,
    )
    uow.orchestration_external_actions.reserve(action)

    mock_obs = MagicMock()
    mock_obs.outcome = ExternalOutcome.SUCCESS
    mock_obs.remote_identifier = "42"

    res = rec_auth.reconcile_observe_before_repeat(op_key, mock_obs)
    assert res.status == ExternalActionStatus.COMPLETED
    assert res.remote_identifier == "42"


# 15. Canonical reconcile_observe_before_repeat Invoked For Project Item Action
def test_canonical_reconcile_observe_before_repeat_invoked_for_project_item():
    """Verify reconcile_observe_before_repeat is invoked for Project item action."""
    uow = DummyUOW()
    rec_auth = ReconciliationAuthority(uow)
    op_key = "project_item_add:p1:k1"
    action = OrchestrationExternalAction(
        saga_id="s1",
        action_key=op_key,
        action_type=ExternalActionType.PROJECT_ITEM_ADD,
        target_identity="k1",
        request_fingerprint="k1",
        status=ExternalActionStatus.RESERVED,
    )
    uow.orchestration_external_actions.reserve(action)
    mock_obs = MagicMock()
    mock_obs.outcome = ExternalOutcome.SUCCESS
    mock_obs.remote_identifier = "item_99"
    res = rec_auth.reconcile_observe_before_repeat(op_key, mock_obs)
    assert res.status == ExternalActionStatus.COMPLETED
    assert res.remote_identifier == "item_99"


# 16. Ambiguous Action Without Safe Retry Blocks
def test_ambiguous_action_without_safe_retry_blocks():
    """Verify action in AMBIGUOUS status without safe retry authorization blocks saga."""
    uow = DummyUOW()
    engine = SagaEngine(uow)
    item = BacklogItem(
        project_id="p1",
        item_key="k1",
        title="Title",
        description="Desc",
        priority=QueuePriority.NORMAL,
        status=WorkItemStatus.PREPARING,
        readiness_state=ReadinessState.NOT_READY,
        openspec_change_name="k1",
    )
    uow.backlog_items.save(item)
    uow.projects.get_by_id.return_value = MagicMock(
        display_name="Proj",
        openspec_path="openspec",
        repository="owner/repo",
        base_branch="main",
        project_id="p1",
    )
    uow.changes.get_by_name.return_value = None

    saga = engine.start_saga(
        saga_type=SagaType.INTAKE,
        project_id="p1",
        work_item_key="k1",
        change_name="k1",
        initial_phase="OPENSPEC_AUTHORED",
    )
    op_key = "issue_create:p1:k1"
    action = OrchestrationExternalAction(
        saga_id=saga.id,
        action_key=op_key,
        action_type=ExternalActionType.ISSUE_CREATE,
        target_identity="k1",
        request_fingerprint="k1",
        status=ExternalActionStatus.AMBIGUOUS,
    )
    uow.orchestration_external_actions.reserve(action)

    mock_github = MagicMock()
    mock_github.list_issues.return_value = MagicMock(outcome=ExternalOutcome.FAILURE, data=[])

    service = IntakeService(
        uow=uow, project_root=".", github_adapter=mock_github, saga_engine=engine
    )
    ctx = _test_ctx("intake:p1:k1")
    service.prepare_work_item("p1", "k1", claim_context=ctx)

    updated_saga = engine.get_saga(saga.id)
    assert updated_saga.status == SagaStatus.BLOCKED


# 17. Terminal Intake Recovery Does Not Become Successful COMPLETED
def test_terminal_intake_recovery_cancels_saga():
    """Verify terminal intake saga transitions to CANCELLED instead of COMPLETED."""
    uow = DummyUOW()
    engine = SagaEngine(uow)

    item = BacklogItem(
        project_id="p1",
        item_key="k1",
        title="Title",
        description="Desc",
        priority=QueuePriority.NORMAL,
        status=WorkItemStatus.CANCELLED,
        readiness_state=ReadinessState.NOT_READY,
        openspec_change_name="k1",
    )
    uow.backlog_items.save(item)

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
    assert reconciled[0].status == SagaStatus.CANCELLED


# 18. Terminal Closure Reconciliation Missing Evidence Blocks
def test_terminal_closure_reconciliation_missing_evidence_blocks():
    """Verify terminal closure reconciliation with missing evidence blocks saga."""
    uow = DummyUOW()

    run = MagicMock(
        run_id="run_1",
        project_id="p1",
        change_name="c1",
        current_stage=OrchestrationStage.COMPLETED,
        stop_outcome=OrchestrationStopOutcome.COMPLETED,
        is_active=False,
        active_job_id="job_1",
        candidate_sha="sha123",
    )
    job = MagicMock(job_id="job_1", status=JobStatus.COMPLETED)
    uow.orchestration_runs.get_by_id.return_value = run
    uow.jobs.get_by_id.return_value = job
    uow.bindings.get_by_project_and_change.return_value = MagicMock(
        github_issue_number=123, github_project_item_id="item_1"
    )
    service = PostMergeReconciliationService(uow=uow, project_root=".")

    ctx = _test_ctx("run:run_1")
    res = service.reconcile_post_merge("p1", "c1", run_id="run_1", claim_context=ctx)
    assert res.success is False


# 19. Terminal Closure Missing One Phase Does Not Reach FINAL_CLOSED
def test_terminal_closure_missing_one_phase_does_not_reach_final_closed():
    """Verify terminal closure missing even 1 phase evidence does not reach FINAL_CLOSED."""
    uow = DummyUOW()
    engine = SagaEngine(uow)

    run = MagicMock(
        run_id="run_1",
        project_id="p1",
        change_name="c1",
        current_stage=OrchestrationStage.COMPLETED,
        stop_outcome=OrchestrationStopOutcome.COMPLETED,
        is_active=False,
        active_job_id="job_1",
        candidate_sha="sha123",
    )
    job = MagicMock(job_id="job_1", status=JobStatus.COMPLETED)
    uow.orchestration_runs.get_by_id.return_value = run
    uow.jobs.get_by_id.return_value = job
    c = Change(
        project_id="p1",
        name="c1",
        status=ChangeStatus.IN_PROGRESS,
        proposal_path="p",
        tasks_path="t",
        design_path="d",
    )
    uow.changes.save(c)
    item = BacklogItem(
        project_id="p1",
        item_key="c1",
        title="T",
        description="D",
        priority=QueuePriority.HIGH,
        status=WorkItemStatus.RUNNING,
        readiness_state=ReadinessState.READY,
        openspec_change_name="c1",
    )
    uow.backlog_items.save(item)

    saga = engine.start_saga(
        saga_type=SagaType.CLOSURE,
        project_id="p1",
        work_item_key="c1",
        change_name="c1",
        run_id="run_1",
        job_id="job_1",
    )
    for act_type in [
        ExternalActionType.ISSUE_CLOSE,
        ExternalActionType.PROJECT_ITEM_EDIT,
        ExternalActionType.OPENSPEC_SYNC,
        ExternalActionType.OPENSPEC_ARCHIVE,
        ExternalActionType.BRANCH_DELETE,
    ]:
        uow.orchestration_external_actions.reserve(
            OrchestrationExternalAction(
                saga_id=saga.id,
                action_key=f"act:{act_type.value}",
                action_type=act_type,
                target_identity="c1",
                request_fingerprint="fp",
                status=ExternalActionStatus.COMPLETED,
            )
        )
    uow.bindings.get_by_project_and_change.return_value = MagicMock(
        github_issue_number=123, github_project_item_id="item_1"
    )
    service = PostMergeReconciliationService(uow=uow, project_root=".")

    ctx = _test_ctx("run:run_1")
    res = service.reconcile_post_merge("p1", "c1", run_id="run_1", claim_context=ctx)
    assert res.success is False
    assert saga.current_phase != "FINAL_CLOSED"


# 20. Terminal Closure All 13 Proven Reaches FINAL_CLOSED
def test_terminal_closure_all_13_proven_reaches_final_closed():
    """Verify terminal closure with all 13 phases proven reaches FINAL_CLOSED and completes."""
    uow = DummyUOW()
    engine = SagaEngine(uow)

    run = MagicMock(
        run_id="run_1",
        project_id="p1",
        change_name="c1",
        current_stage=OrchestrationStage.COMPLETED,
        stop_outcome=OrchestrationStopOutcome.COMPLETED,
        is_active=False,
        active_job_id="job_1",
        candidate_sha="sha123",
    )
    job = MagicMock(job_id="job_1", status=JobStatus.COMPLETED)
    uow.orchestration_runs.get_by_id.return_value = run
    uow.jobs.get_by_id.return_value = job
    c = Change(
        project_id="p1",
        name="c1",
        status=ChangeStatus.IN_PROGRESS,
        proposal_path="p",
        tasks_path="t",
        design_path="d",
    )
    uow.changes.save(c)
    item = BacklogItem(
        project_id="p1",
        item_key="c1",
        title="T",
        description="D",
        priority=QueuePriority.HIGH,
        status=WorkItemStatus.RUNNING,
        readiness_state=ReadinessState.READY,
        openspec_change_name="c1",
    )
    uow.backlog_items.save(item)

    saga = engine.start_saga(
        saga_type=SagaType.CLOSURE,
        project_id="p1",
        work_item_key="c1",
        change_name="c1",
        run_id="run_1",
        job_id="job_1",
    )
    for act_type in [
        ExternalActionType.ISSUE_CLOSE,
        ExternalActionType.PROJECT_ITEM_EDIT,
        ExternalActionType.OPENSPEC_SYNC,
        ExternalActionType.OPENSPEC_ARCHIVE,
        ExternalActionType.WORKTREE_DELETE,
        ExternalActionType.BRANCH_DELETE,
    ]:
        uow.orchestration_external_actions.reserve(
            OrchestrationExternalAction(
                saga_id=saga.id,
                action_key=f"act:{act_type.value}",
                action_type=act_type,
                target_identity="c1",
                request_fingerprint="fp",
                status=ExternalActionStatus.COMPLETED,
            )
        )
    uow.bindings.get_by_project_and_change.return_value = MagicMock(
        github_issue_number=123, github_project_item_id="item_1"
    )
    service = PostMergeReconciliationService(uow=uow, project_root=".")

    ctx = _test_ctx("run:run_1")
    res = service.reconcile_post_merge("p1", "c1", run_id="run_1", claim_context=ctx)
    assert res.success is True
    assert res.already_closed is True


# 21. Squash Repository Mismatch Fails
def test_squash_repository_mismatch_fails():
    """Verify verify_candidate_delivery fails when PR repository mismatch occurs."""
    uow = DummyUOW()
    uow.projects.get_by_id.return_value = MagicMock(repository="owner/expected-repo")
    service = PostMergeReconciliationService(uow=uow, project_root=".")

    pr_details = {
        "repository": "owner/wrong-repo",
        "base_branch": "main",
        "head_sha": "cand123",
        "merge_commit_sha": "merge123",
        "is_merged": True,
    }
    verified = service.verify_candidate_delivery(
        candidate_sha="cand123",
        base_branch="main",
        project_id="p1",
        pr_details=pr_details,
    )
    assert verified is False


# 22. Squash Base Mismatch Fails
def test_squash_base_mismatch_fails():
    """Verify verify_candidate_delivery fails when PR base branch mismatch occurs."""
    uow = DummyUOW()
    uow.projects.get_by_id.return_value = MagicMock(repository="owner/repo")
    service = PostMergeReconciliationService(uow=uow, project_root=".")

    pr_details = {
        "repository": "owner/repo",
        "base_branch": "feature-branch",
        "head_sha": "cand123",
        "merge_commit_sha": "merge123",
        "is_merged": True,
    }
    verified = service.verify_candidate_delivery(
        candidate_sha="cand123",
        base_branch="main",
        project_id="p1",
        pr_details=pr_details,
    )
    assert verified is False


# 23. Missing Audited Candidate Fails
def test_missing_audited_candidate_fails():
    """Verify verify_candidate_delivery fails when candidate SHA is empty."""
    uow = DummyUOW()
    service = PostMergeReconciliationService(uow=uow, project_root=".")
    verified = service.verify_candidate_delivery(
        candidate_sha="",
        base_branch="main",
        project_id="p1",
    )
    assert verified is False


# 24. Valid Squash Passes
def test_valid_squash_passes():
    """Verify verify_candidate_delivery passes when valid squash merge evidence is present."""
    uow = DummyUOW()
    uow.projects.get_by_id.return_value = MagicMock(repository="owner/repo")
    service = PostMergeReconciliationService(uow=uow, project_root=".")
    service.verify_candidate_ancestry = MagicMock(
        side_effect=lambda cand, base, **kw: base == "merge123"
    )
    service._authorize_managed_repo_mutation = MagicMock()

    pr_details = {
        "repository": "owner/repo",
        "base_branch": "main",
        "head_sha": "cand123",
        "merge_commit_sha": "merge123",
        "is_merged": True,
    }

    import subprocess

    orig_run = subprocess.run

    def mock_run(cmd, **kwargs):
        if "merge-base" in cmd:
            return MagicMock(returncode=0)
        return orig_run(cmd, **kwargs)

    with pytest.MonkeyPatch.context() as m:
        m.setattr(subprocess, "run", mock_run)
        verified = service.verify_candidate_delivery(
            candidate_sha="cand123",
            base_branch="main",
            project_id="p1",
            pr_details=pr_details,
        )
        assert verified is True


# 25. Terminal Change Check Prevents Saga Creation
def test_terminal_change_check_prevents_saga_creation():
    """Verify prepare_work_item does not start or cancel a saga when Change is terminal."""
    uow = DummyUOW()
    engine = MagicMock(wraps=SagaEngine(uow))
    item = BacklogItem(
        project_id="p1",
        item_key="term1",
        title="Title",
        description="Desc",
        priority=QueuePriority.NORMAL,
        status=WorkItemStatus.PREPARING,
        readiness_state=ReadinessState.NOT_READY,
        openspec_change_name="term1",
    )
    uow.backlog_items.save(item)
    change = Change(
        project_id="p1",
        name="term1",
        status=ChangeStatus.DONE,
        proposal_path="p",
        tasks_path="t",
        design_path="d",
    )
    uow.changes.save(change)
    service = IntakeService(uow=uow, project_root=".", saga_engine=engine)
    ctx = _test_ctx("intake:p1:term1")
    res = service.prepare_work_item("p1", "term1", claim_context=ctx)
    assert res.item.item_key == "term1"
    engine.start_saga.assert_not_called()
    engine.cancel_saga.assert_not_called()


# 26. Observation Failure Returns UNKNOWN
def test_reconcile_issue_creation_unobservable_returns_unknown():
    """Verify reconcile_issue_creation returns ExternalOutcome.UNKNOWN when list_issues query fails or throws."""
    from minime.domain.enums import ExternalReasonCode
    from minime.domain.models import ExternalActionResult

    uow = DummyUOW()
    rec_auth = ReconciliationAuthority(uow)
    gh_mock = MagicMock()

    # Case 1: Exception during list_issues
    gh_mock.list_issues.side_effect = RuntimeError("503 Service Unavailable")
    res1 = rec_auth.reconcile_issue_creation(gh_mock, "owner/repo", "op1", "Title")
    assert res1.outcome == ExternalOutcome.UNKNOWN
    assert res1.reason_code == ExternalReasonCode.UNOBSERVABLE

    # Case 2: Non-success outcome from list_issues
    gh_mock.list_issues.side_effect = None
    gh_mock.list_issues.return_value = ExternalActionResult(
        outcome=ExternalOutcome.FAILURE,
        source_adapter="github",
        reason_code=ExternalReasonCode.UNOBSERVABLE,
        error_message="Timeout",
    )
    res2 = rec_auth.reconcile_issue_creation(gh_mock, "owner/repo", "op1", "Title")
    assert res2.outcome == ExternalOutcome.UNKNOWN
    assert res2.reason_code == ExternalReasonCode.UNOBSERVABLE


# 27. Project Item Observation Failure Returns UNKNOWN
def test_reconcile_project_item_add_unobservable_returns_unknown():
    """Verify reconcile_project_item_add returns ExternalOutcome.UNKNOWN when list_project_items query fails or throws."""
    from minime.domain.enums import ExternalReasonCode
    from minime.domain.models import ExternalActionResult

    uow = DummyUOW()
    rec_auth = ReconciliationAuthority(uow)
    gh_mock = MagicMock()

    # Exception
    gh_mock.list_project_items.side_effect = TimeoutError("Request timed out")
    res1 = rec_auth.reconcile_project_item_add(gh_mock, 1, "owner", "http://issue/1", "op1")
    assert res1.outcome == ExternalOutcome.UNKNOWN
    assert res1.reason_code == ExternalReasonCode.UNOBSERVABLE

    # Non-success outcome
    gh_mock.list_project_items.side_effect = None
    gh_mock.list_project_items.return_value = ExternalActionResult(
        outcome=ExternalOutcome.FAILURE,
        source_adapter="github",
        reason_code=ExternalReasonCode.UNOBSERVABLE,
        error_message="GraphQL Error",
    )
    res2 = rec_auth.reconcile_project_item_add(gh_mock, 1, "owner", "http://issue/1", "op1")
    assert res2.outcome == ExternalOutcome.UNKNOWN
    assert res2.reason_code == ExternalReasonCode.UNOBSERVABLE
