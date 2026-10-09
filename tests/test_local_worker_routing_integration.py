"""Integration tests for LocalWorkerService.run with capability routing.

Verifies end-to-end integration, refusal statuses (PreflightStatus.NOT_QUALIFIED),
zero Ollama HTTP dispatch, single-file patch policy enforcement, and safety boundaries.
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
        authoritative_change={"replacement": "..." },
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
    assert adapter.preflight.call_count == 0
    assert adapter.generate.call_count == 0


@pytest.mark.asyncio
async def test_scenario_8_prose_alone_cannot_create_trusted_evidence():
    """Scenario 8: Instruction text containing mechanical description without routing_source fails closed."""
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
        instruction="Replace text_a with text_b in src/minime/utils.py mechanically",
    )
    validator = AsyncMock(return_value=ValidationResult(verdict=LocalValidationVerdict.PASS))

    outcome = await service.run(
        task,
        validator=validator,
        routing_source=None,  # No structured command
        classification_snapshot=snapshot,
    )

    assert outcome.preflight.status == PreflightStatus.NOT_QUALIFIED
    assert outcome.evidence.result_class == "REFUSED"
    assert adapter.preflight.call_count == 0
    assert adapter.generate.call_count == 0


@pytest.mark.asyncio
async def test_scenario_19_20_refusal_emits_existing_provider_policy():
    """Scenarios 19 & 20: Refusal uses PreflightStatus.NOT_QUALIFIED and emits EXISTING_PROVIDER_POLICY escalation."""
    cmd, _ = _valid_fixtures()
    # Snapshot missing to trigger refusal
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
        routing_source=cmd,
        classification_snapshot=None,  # Missing snapshot
    )

    assert outcome.preflight.status == PreflightStatus.NOT_QUALIFIED
    assert outcome.evidence.escalation.required is True
    assert outcome.evidence.escalation.target == EscalationTarget.EXISTING_PROVIDER_POLICY
    assert adapter.preflight.call_count == 0
    assert adapter.generate.call_count == 0
