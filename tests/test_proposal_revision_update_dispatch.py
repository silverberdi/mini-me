"""Unit tests for proposal revision update dispatch and invocation governance."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from minime.domain.enums import OrchestrationStage
from minime.domain.models import OrchestrationRun, RecoveryClaimContext
from minime.services.orchestration_coordinator import (
    NativeOrchestrationCoordinator,
    StageInvocation,
)


class FakeWorkflow:
    def __init__(self, operation: str):
        self.operation = operation
        self.dispatch_command = f"/opsx-{operation}"


class FakeAgentRunner:
    def __init__(self):
        self.resolved_operations: list[str] = []
        self.prompts: list[str] = []

    def resolve_workflow(self, *, worktree_path: Path, provider: str, operation: str, change_name: str):
        self.resolved_operations.append(operation)
        return FakeWorkflow(operation)

    async def run(self, **kwargs):
        self.prompts.append(kwargs.get("prompt_context", ""))
        return MagicMock(workflow_handoff=None, workflow_handoff_required=False)


@pytest.mark.asyncio
async def test_run_propose_dispatches_update_when_pending_revision(tmp_path: Path):
    runner = FakeAgentRunner()
    coord = NativeOrchestrationCoordinator(
        uow_factory=lambda: MagicMock(),
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=runner,
    )

    result = await coord._run_propose(
        worktree_path=tmp_path,
        provider="codex",
        change_name="test-change",
        issue_number=3,
        issue_title="Test Issue",
        issue_body="Description",
        pending_revision=True,
        operator_clarification="Fix static tests and scope",
    )

    assert "update" in runner.resolved_operations
    assert "continue" not in runner.resolved_operations
    assert "propose" not in runner.resolved_operations
    assert len(runner.prompts) == 1
    prompt = runner.prompts[0]
    assert "Execute official OpenSpec Update for change 'test-change'" in prompt
    assert "Fix static tests and scope" in prompt


@pytest.mark.asyncio
async def test_run_propose_dispatches_continue_when_continue_existing_without_revision(tmp_path: Path):
    runner = FakeAgentRunner()
    coord = NativeOrchestrationCoordinator(
        uow_factory=lambda: MagicMock(),
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=runner,
    )

    result = await coord._run_propose(
        worktree_path=tmp_path,
        provider="codex",
        change_name="test-change",
        issue_number=3,
        issue_title="Test Issue",
        issue_body="Description",
        continue_existing=True,
        pending_revision=False,
    )

    assert "continue" in runner.resolved_operations
    assert "update" not in runner.resolved_operations
    assert "Execute official OpenSpec Continue" in runner.prompts[0]


@pytest.mark.asyncio
async def test_begin_stage_invocation_permits_human_resume_after_failed_or_complete(tmp_path: Path):
    coord = NativeOrchestrationCoordinator(
        uow_factory=lambda: MagicMock(),
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
    )

    candidate = {
        "run_id": "test-run",
        "stage": "PROPOSE",
        "fingerprint": "fp123",
        "candidate": "same-candidate",
    }
    coord._stage_candidate_identity = AsyncMock(return_value=candidate)

    # Simulate prior finished attempts in stage events: one FAILED
    class FakeEvent:
        def __init__(self, event_type: str, evidence: dict):
            self.event_type = event_type
            self.evidence_references = evidence

    events = [
        FakeEvent("STAGE_INVOCATION_STARTED", {"attempt_id": "att-1", "candidate": candidate, "claim_key": "stage-invocation:test-run:PROPOSE:fp123"}),
        FakeEvent("STAGE_INVOCATION_FAILED", {"attempt_id": "att-1", "status": "FAILED", "claim_key": "stage-invocation:test-run:PROPOSE:fp123"}),
    ]

    claims_repo = MagicMock()
    claims_repo.get_by_key.return_value = None
    claims_repo.acquire_or_reacquire.return_value = MagicMock(
        claim_key="stage-invocation:test-run:PROPOSE:fp123",
        owner_instance_id="stage:PROPOSE:123",
        fence_token=1,
        lease_expires_at=datetime.now(timezone.utc),
    )

    uow = MagicMock()
    uow.claims = claims_repo
    uow.orchestration_stage_events.list_by_run.return_value = events

    run = OrchestrationRun(
        project_id="test",
        run_id="test-run",
        change_name="test-change",
        base_sha="base",
        current_stage=OrchestrationStage.PROPOSING,
    )

    # Without allow_human_resume or authorized_retry, must fail closed (return None)
    inv_denied = await coord._begin_stage_invocation(
        uow, run, tmp_path, "PROPOSE",
        allow_human_resume=False,
        authorized_retry=False,
    )
    assert inv_denied is None

    # With allow_human_resume=True, must permit invocation
    inv_allowed = await coord._begin_stage_invocation(
        uow, run, tmp_path, "PROPOSE",
        allow_human_resume=True,
        authorized_retry=False,
    )
    assert inv_allowed is not None
    assert isinstance(inv_allowed, StageInvocation)


@pytest.mark.asyncio
async def test_run_native_dispatch_releases_claim_when_invocation_is_none(tmp_path: Path):
    coord = NativeOrchestrationCoordinator(
        uow_factory=lambda: MagicMock(),
        github_adapter=MagicMock(),
        worktree_manager=MagicMock(),
        agent_runner=MagicMock(),
    )
    coord._begin_stage_invocation = AsyncMock(return_value=None)
    coord._finish_native_dispatch = MagicMock()

    uow = MagicMock()
    run = OrchestrationRun(
        project_id="test",
        run_id="test-run",
        change_name="test-change",
        base_sha="base",
        current_stage=OrchestrationStage.PROPOSING,
    )
    claim_ctx = RecoveryClaimContext(
        claim_key="run:test-run",
        owner_instance_id="propose:123",
        fence_token=1,
        lease_expires_at=datetime.now(timezone.utc),
    )
    dispatch = ("att-id", "action-key", claim_ctx)

    with pytest.raises(RuntimeError, match="Propose stage invocation is already active or ambiguous"):
        await coord._run_native_dispatch(
            uow, run, "propose", dispatch,
            work=AsyncMock(),
            complete=lambda r: True,
            worktree_path=tmp_path,
        )

    # Verify that _finish_native_dispatch was called to release the claim!
    coord._finish_native_dispatch.assert_called_once_with(
        uow, run, "propose", "att-id", "action-key", claim_ctx, "AMBIGUOUS",
        "Propose stage invocation is already active or ambiguous",
    )
