# Leaf F: preflight / CLI configuration incompatibility must not consume
# corrective-retry budget or degrade provider health, for BOTH implementer and
# reviewer roles.

import pytest
from tests.test_execution_pipeline import FakeWorktreeManager, seed_ready_change

from minime.domain.enums import (
    ContinuationDecision,
    EventType,
    ExecutionOutcome,
    JobStatus,
    ProviderHealthStatus,
)
from minime.services.continuation_engine import ContinuationContext, ContinuationEngine
from minime.services.execution_pipeline import ExecutionPipelineService
from minime.services.implementer_runner import ImplementerResult, MockImplementerRunner
from minime.services.reviewer_runner import ReviewerResult


def test_preflight_failure_escalates_without_consuming_retry_budget():
    ctx = ContinuationContext(
        job_id="job",
        attempt_number=1,
        current_executor_role="codex",
        current_model_identity="codex",
        outcome=ExecutionOutcome.PROVIDER_PREFLIGHT_FAILURE,
        corrective_retries_for_current_executor=0,
        reassignment_count=0,
    )
    decision = ContinuationEngine().decide(ctx)
    assert decision.decision == ContinuationDecision.NEEDS_HUMAN
    assert ctx.corrective_retries_for_current_executor == 0
    assert ctx.reassignment_count == 0


class _PreflightFailImplementerRunner:
    async def run(self, worktree_path, prompt_context, timeout_seconds):
        del worktree_path, prompt_context, timeout_seconds
        return ImplementerResult(
            exit_code=0,
            timed_out=False,
            stdout=[],
            stderr=[],
            duration_ms=1,
            preflight_error="UNSUPPORTED_FLAG",
        )


class _PreflightFailReviewerRunner:
    async def run(self, worktree_path, prompt_context, timeout_seconds):
        del worktree_path, prompt_context, timeout_seconds
        return ReviewerResult(
            exit_code=-2,
            timed_out=False,
            stdout=[],
            stderr=[],
            duration_ms=1,
            preflight_error="UNSUPPORTED_FLAG",
        )


@pytest.mark.asyncio
async def test_implementer_preflight_failure_no_retry_and_no_health_degradation(
    in_memory_uow, tmp_path
):
    seed_ready_change(in_memory_uow, tmp_path, "# Tasks\n- [x] 1.1 Done\n")
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=_PreflightFailImplementerRunner(),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("mini-me", "synthetic-pipeline-change")

    assert job.status == JobStatus.NEEDS_HUMAN
    health = in_memory_uow.provider_health.get_by_provider("codex")
    assert health.status == ProviderHealthStatus.AVAILABLE
    events = in_memory_uow.events.list_events(
        project_id="mini-me", change_id="synthetic-pipeline-change"
    )
    assert not any(
        e.event_type == EventType.CORRECTIVE_RETRY_ISSUED for e in events
    )


@pytest.mark.asyncio
async def test_reviewer_preflight_failure_no_retry_and_no_health_degradation(
    in_memory_uow, tmp_path
):
    seed_ready_change(in_memory_uow, tmp_path, "# Tasks\n- [x] 1.1 Done\n")
    service = ExecutionPipelineService(
        in_memory_uow,
        project_root=tmp_path,
        implementer_runner=MockImplementerRunner(),
        reviewer_runner=_PreflightFailReviewerRunner(),
        worktree_manager=FakeWorktreeManager(tmp_path),
    )

    job = await service.run_job("mini-me", "synthetic-pipeline-change")

    assert job.status == JobStatus.NEEDS_HUMAN
    health = in_memory_uow.provider_health.get_by_provider("antigravity")
    assert health.status == ProviderHealthStatus.AVAILABLE
    events = in_memory_uow.events.list_events(
        project_id="mini-me", change_id="synthetic-pipeline-change"
    )
    assert not any(
        e.event_type == EventType.CORRECTIVE_RETRY_ISSUED for e in events
    )
