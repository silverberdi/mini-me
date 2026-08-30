from minime.domain.enums import (
    ContinuationDecision,
    ExecutionOutcome,
    OrchestrationStopOutcome,
    ProviderResultClass,
)
from minime.domain.models import NormalizedProviderResult, OrchestrationRun
from minime.services.continuation_engine import ContinuationContext, ContinuationEngine
from minime.services.outcome_governance import (
    CompletionVerificationResult,
    OutcomeGovernanceService,
)


def test_transient_provider_error_maps_to_environment_unavailable():
    outcome = OutcomeGovernanceService().classify_outcome(
        CompletionVerificationResult(is_complete=False),
        NormalizedProviderResult(
            result_class=ProviderResultClass.TRANSIENT_ERROR, provider="codex", role="implementer"
        ),
    )
    assert outcome == ExecutionOutcome.ENVIRONMENT_UNAVAILABLE


def test_environment_unavailable_waits_without_consuming_budgets():
    context = ContinuationContext(
        job_id="job",
        attempt_number=4,
        current_executor_role="codex",
        current_model_identity="codex-model",
        outcome=ExecutionOutcome.ENVIRONMENT_UNAVAILABLE,
        corrective_retries_for_current_executor=2,
        reassignment_count=2,
    )
    decision = ContinuationEngine().decide(context)
    assert decision.decision == ContinuationDecision.WAIT_EXTERNAL
    assert context.corrective_retries_for_current_executor == 2
    assert context.reassignment_count == 2


def test_wait_external_is_the_orchestration_stop_outcome():
    assert OrchestrationStopOutcome.WAITING_EXTERNAL.value == "WAITING_EXTERNAL"
    run = OrchestrationRun(run_id="run", project_id="p", change_name="c", base_sha="base")
    assert run.current_generation == 1
