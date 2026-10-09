"""Integration tests for LocalWorkerService.run with capability routing.

Verifies end-to-end integration, refusal statuses (PreflightStatus.NOT_QUALIFIED),
zero Ollama HTTP dispatch, single-file patch policy enforcement, structured decision
preservation on ServiceOutcome, and the reserved benchmark test case.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from minime.domain.enums import (
    ClassificationCompleteness,
    ClassificationStage,
    TaskComplexity,
    TaskSurfaceKind,
)
from minime.domain.models import TaskClassificationSnapshot, TaskRiskProfile
from minime.local_worker.models import (
    EscalationTarget,
    LocalMechanicalOperation,
    LocalMutationMode,
    LocalRoutingEvidence,
    LocalRoutingEvidenceProvenance,
    LocalRoutingReasonCode,
    LocalRoutingVerdict,
    LocalTaskClass,
    LocalTaskEnvelope,
    LocalValidationVerdict,
    OperatorMechanicalCommand,
    PreflightStatus,
    ValidationResult,
)
from minime.local_worker.service import LocalWorkerService


def _valid_fixtures(target_file: str = "src/minime/utils.py"):
    cmd = OperatorMechanicalCommand(
        operation_type=LocalMechanicalOperation.TEXT_REPLACEMENT,
        mutation_mode=LocalMutationMode.MUTATING,
        target_file=target_file,
        authoritative_change={"replacement": "def foo(): pass"},
        deterministic_acceptance={"test_target": "tests/test_utils.py"},
    )
    snapshot = TaskClassificationSnapshot(
        id="snap-test-integration-001",
        stage=ClassificationStage.PRE_EXECUTION,
        classifier_version="1.0.0",
        evidence_source="test_fixture",
        classification_completeness=ClassificationCompleteness.PARTIAL,
        missing_signals=[],
        complexity=TaskComplexity.LOW,
        surface_kind=TaskSurfaceKind.BACKEND_SERVICE,
        risk_profile=TaskRiskProfile(
            architectural_impact="NONE",
            persistence_impact="NONE",
            security_auth_impact="NONE",
            production_runtime="NONE",
            provider_orchestration="NONE",
            destructive_operations="NONE",
            deployment_config="NONE",
            code_change_breadth="LOW",
        ),
    )
    return cmd, snapshot


@pytest.mark.asyncio
async def test_scenario_1_direct_instantiation_of_evidence_fails_closed_zero_ollama():
    """Scenario 1: Direct instantiation of LocalRoutingEvidence without authority fails before preflight/Ollama."""
    evidence = LocalRoutingEvidence(
        operation_type=LocalMechanicalOperation.TEXT_REPLACEMENT,
        mutation_mode=LocalMutationMode.MUTATING,
        target_file="src/minime/utils.py",
        authoritative_change_supplied=True,
        deterministic_acceptance_supplied=True,
        provenance=LocalRoutingEvidenceProvenance.OPERATOR_EXPLICIT_MECHANICAL_COMMAND,
    )
    _, snapshot = _valid_fixtures()

    adapter = MagicMock()
    adapter.model = "qwen2.5-coder:7b-instruct-q4_K_M"
    adapter.preflight = AsyncMock()
    adapter.generate = AsyncMock()

    service = LocalWorkerService(adapter=adapter)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["src/minime/utils.py"],
        instruction="Fix helper",
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(
        task,
        validator=validator,
        routing_source=evidence,  # Passing LocalRoutingEvidence directly, not OperatorMechanicalCommand
        classification_snapshot=snapshot,
    )

    assert outcome.preflight.status == PreflightStatus.NOT_QUALIFIED
    assert outcome.evidence.result_class == "REFUSED"
    assert outcome.evidence.escalation.required is True
    assert outcome.evidence.escalation.target == EscalationTarget.EXISTING_PROVIDER_POLICY
    assert outcome.routing_decision is not None
    assert outcome.routing_decision.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
    assert outcome.routing_decision.reason_code == LocalRoutingReasonCode.UNSUPPORTED_EVIDENCE_SOURCE
    assert adapter.preflight.call_count == 0
    assert adapter.generate.call_count == 0


@pytest.mark.asyncio
async def test_scenario_4_missing_source_fails_closed_zero_ollama():
    """Scenario 4: Missing routing_source fails before preflight/Ollama."""
    _, snapshot = _valid_fixtures()

    adapter = MagicMock()
    adapter.model = "qwen2.5-coder:7b-instruct-q4_K_M"
    adapter.preflight = AsyncMock()
    adapter.generate = AsyncMock()

    service = LocalWorkerService(adapter=adapter)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["src/minime/utils.py"],
        instruction="Fix helper",
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(
        task,
        validator=validator,
        routing_source=None,
        classification_snapshot=snapshot,
    )

    assert outcome.preflight.status == PreflightStatus.NOT_QUALIFIED
    assert outcome.evidence.result_class == "REFUSED"
    assert outcome.evidence.escalation.required is True
    assert outcome.evidence.escalation.target == EscalationTarget.EXISTING_PROVIDER_POLICY
    assert outcome.routing_decision is not None
    assert outcome.routing_decision.reason_code == LocalRoutingReasonCode.MISSING_ROUTING_SOURCE
    assert adapter.preflight.call_count == 0
    assert adapter.generate.call_count == 0


@pytest.mark.asyncio
async def test_read_only_with_arbitrary_context_never_reaches_ollama():
    """Finding 1: Safe-looking read_sources list plus arbitrary task context NEVER reaches Ollama."""
    cmd = OperatorMechanicalCommand(
        operation_type=LocalMechanicalOperation.LOG_DIAGNOSTIC,
        mutation_mode=LocalMutationMode.READ_ONLY,
        read_sources=["/var/log/minime/api.log"],
    )
    _, snapshot = _valid_fixtures()

    adapter = MagicMock()
    adapter.model = "qwen2.5-coder:7b-instruct-q4_K_M"
    adapter.preflight = AsyncMock()
    adapter.generate = AsyncMock()

    service = LocalWorkerService(adapter=adapter)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.LOG_ANALYSIS,
        allowed_files=[],
        instruction="Analyze api log errors",
        context="ARBITRARY_UNBOUNDED_CALLER_CONTEXT_CONTENT",
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(
        task,
        validator=validator,
        routing_source=cmd,
        classification_snapshot=snapshot,
    )

    assert outcome.preflight.status == PreflightStatus.NOT_QUALIFIED
    assert outcome.evidence.result_class == "REFUSED"
    assert outcome.routing_decision is not None
    assert outcome.routing_decision.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
    assert outcome.routing_decision.reason_code == LocalRoutingReasonCode.READ_SOURCE_LOADING_UNAVAILABLE
    assert adapter.preflight.call_count == 0
    assert adapter.generate.call_count == 0


@pytest.mark.asyncio
async def test_reserved_benchmark_case_escalates_zero_ollama():
    """Reserved Benchmark: Exact instruction without trusted OperatorMechanicalCommand yields ESCALATE_PROVIDER_POLICY and 0 Ollama calls."""
    _, snapshot = _valid_fixtures()

    adapter = MagicMock()
    adapter.model = "qwen2.5-coder:7b-instruct-q4_K_M"
    adapter.preflight = AsyncMock()
    adapter.generate = AsyncMock()

    service = LocalWorkerService(adapter=adapter)
    benchmark_instruction = (
        "Repair the stale test fixture in tests/test_autonomous_intake_admission.py so "
        "test_auto_admit_single_concurrency_deterministic_selection matches the current "
        "discovery/readiness contract. Modify only this test file. Preserve runtime behavior; "
        "source files forbidden."
    )
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.TEST_AUTHORING,
        allowed_files=["tests/test_autonomous_intake_admission.py"],
        instruction=benchmark_instruction,
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(
        task,
        validator=validator,
        routing_source=None,  # No trusted OperatorMechanicalCommand provided
        classification_snapshot=snapshot,
    )

    assert outcome.preflight.status == PreflightStatus.NOT_QUALIFIED
    assert outcome.evidence.result_class == "REFUSED"
    assert outcome.evidence.escalation.required is True
    assert outcome.evidence.escalation.target == EscalationTarget.EXISTING_PROVIDER_POLICY
    assert outcome.routing_decision is not None
    assert outcome.routing_decision.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
    assert outcome.routing_decision.reason_code == LocalRoutingReasonCode.MISSING_ROUTING_SOURCE
    assert adapter.preflight.call_count == 0
    assert adapter.generate.call_count == 0


@pytest.mark.asyncio
async def test_service_outcome_preserves_routing_decision_for_eligible_execution():
    """Finding 3: ServiceOutcome exposes routing_decision for LOCAL_ELIGIBLE execution."""
    cmd, snapshot = _valid_fixtures("src/minime/utils.py")

    adapter = MagicMock()
    adapter.model = "qwen2.5-coder:7b-instruct-q4_K_M"
    adapter.preflight = AsyncMock(
        return_value=MagicMock(status=PreflightStatus.READY, reachable=True, model_present=True)
    )
    adapter.generate = AsyncMock(
        return_value=MagicMock(
            result_class=MagicMock(name="SUCCESS"),
            text='{"kind":"NO_CHANGE_JUSTIFIED","summary":"ok","files_changed":[],"patch":null,"confidence":1.0,"escalation_required":false,"escalation_reason":"","next_action":"none"}',
        )
    )

    service = LocalWorkerService(adapter=adapter)
    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["src/minime/utils.py"],
        instruction="Fix helper",
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(
        task,
        validator=validator,
        routing_source=cmd,
        classification_snapshot=snapshot,
    )

    assert outcome.routing_decision is not None
    assert outcome.routing_decision.verdict == LocalRoutingVerdict.LOCAL_ELIGIBLE
    assert outcome.routing_decision.reason_code == LocalRoutingReasonCode.LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY


def test_effective_execution_model_binding_constructor():
    """Proves constructor enforcement of effective execution model identity (Required Tests 1-4)."""
    from minime.local_worker.ollama_adapter import LocalOllamaAdapter

    # 1. Canonical service model + canonical adapter model: accepted
    adapter_7b = LocalOllamaAdapter(model="qwen2.5-coder:7b-instruct-q4_K_M")
    service_ok = LocalWorkerService(adapter=adapter_7b)
    assert service_ok.model == "qwen2.5-coder:7b-instruct-q4_K_M"
    assert service_ok.adapter.model == "qwen2.5-coder:7b-instruct-q4_K_M"

    # 2. Canonical self.model + injected 14B adapter: FAILS CLOSED in __init__
    adapter_14b = LocalOllamaAdapter(model="qwen2.5-coder:14b-instruct-q4_K_M")
    with pytest.raises(ValueError, match="model mismatch"):
        LocalWorkerService(adapter=adapter_14b)

    # 3. Canonical self.model + injected unknown-model adapter: FAILS CLOSED in __init__
    adapter_unknown = LocalOllamaAdapter(model="unknown-model")
    with pytest.raises(ValueError, match="model mismatch"):
        LocalWorkerService(adapter=adapter_unknown)

    # 4. Explicit 14B service model: rejected by assert_local_qwen_model
    with pytest.raises(ValueError, match="canonical local Qwen model"):
        LocalWorkerService(model="qwen2.5-coder:14b-instruct-q4_K_M")


@pytest.mark.asyncio
async def test_mismatched_or_missing_model_adapter_zero_preflight_and_generate():
    """Proves adapter with missing/None model identity fails closed with 0 preflight and 0 generate calls (Required Tests 5, 8)."""
    cmd, snapshot = _valid_fixtures("src/minime/utils.py")

    class AdapterWithoutModel:
        model = None
        preflight = AsyncMock()
        generate = AsyncMock()

    adapter_no_model = AdapterWithoutModel()
    service = LocalWorkerService(adapter=adapter_no_model)

    task = LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=LocalTaskClass.SMALL_CODE_FIX,
        allowed_files=["src/minime/utils.py"],
        instruction="Fix helper",
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(
        task,
        validator=validator,
        routing_source=cmd,
        classification_snapshot=snapshot,
    )

    assert outcome.preflight.status == PreflightStatus.NOT_QUALIFIED
    assert outcome.routing_decision is not None
    assert outcome.routing_decision.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
    assert outcome.routing_decision.reason_code == LocalRoutingReasonCode.LOCAL_MODEL_NOT_CAPABLE_FOR_TASK
    assert adapter_no_model.preflight.call_count == 0
    assert adapter_no_model.generate.call_count == 0

