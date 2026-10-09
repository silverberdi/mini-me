"""Unit tests for LocalRoutingEvidenceAuthority and LocalWorkerCapabilityRouter.

Tests all 24 scenarios defined in the approved OpenSpec contract local-worker-capability-routing-policy.
"""


from minime.domain.enums import (
    ClassificationCompleteness,
    ClassificationStage,
    TaskComplexity,
    TaskSurfaceKind,
)
from minime.domain.models import TaskClassificationSnapshot, TaskRiskProfile
from minime.local_worker.capability_router import LocalWorkerCapabilityRouter
from minime.local_worker.evidence_authority import LocalRoutingEvidenceAuthority
from minime.local_worker.model_identity import local_qwen_model_identity
from minime.local_worker.models import (
    EscalationTarget,
    LocalMechanicalOperation,
    LocalMutationMode,
    LocalRoutingEvidenceProvenance,
    LocalRoutingReasonCode,
    LocalRoutingVerdict,
    LocalTaskClass,
    LocalTaskEnvelope,
    OperatorMechanicalCommand,
)


def _make_snapshot(
    stage: ClassificationStage = ClassificationStage.PRE_EXECUTION,
    completeness: ClassificationCompleteness = ClassificationCompleteness.PARTIAL,
    missing_signals: list[str] | None = None,
    complexity: TaskComplexity = TaskComplexity.LOW,
    surface: TaskSurfaceKind = TaskSurfaceKind.BACKEND_SERVICE,
    risk_overrides: dict[str, str] | None = None,
) -> TaskClassificationSnapshot:
    risk_dict = {
        "architectural_impact": "NONE",
        "persistence_impact": "NONE",
        "security_auth_impact": "NONE",
        "production_runtime": "NONE",
        "provider_orchestration": "NONE",
        "destructive_operations": "NONE",
        "deployment_config": "NONE",
        "code_change_breadth": "LOW",
    }
    if risk_overrides:
        risk_dict.update(risk_overrides)

    return TaskClassificationSnapshot(
        id="snap-test-router-001",
        stage=stage,
        classifier_version="1.0.0",
        evidence_source="test_harness",
        classification_completeness=completeness,
        missing_signals=missing_signals if missing_signals is not None else [],
        complexity=complexity,
        surface_kind=surface,
        risk_profile=TaskRiskProfile(**risk_dict),
    )


def _make_task(
    allowed_files: list[str] | None = None,
    task_class: LocalTaskClass = LocalTaskClass.SMALL_CODE_FIX,
    instruction: str = "Fix bug in helper",
) -> LocalTaskEnvelope:
    return LocalTaskEnvelope(
        role="LOCAL_WORKER",
        task_class=task_class,
        allowed_files=allowed_files if allowed_files is not None else ["src/minime/utils.py"],
        instruction=instruction,
    )


def _make_mutating_cmd(
    target_file: str = "src/minime/utils.py",
    authoritative_change: dict | str | None = None,
    deterministic_acceptance: dict | str | None = None,
    requires_discovery: bool = False,
    unresolved_ambiguity: bool = False,
) -> OperatorMechanicalCommand:
    return OperatorMechanicalCommand(
        operation_type=LocalMechanicalOperation.TEXT_REPLACEMENT,
        mutation_mode=LocalMutationMode.MUTATING,
        target_file=target_file,
        authoritative_change=authoritative_change or {"replacement": "def foo(): pass"},
        deterministic_acceptance=deterministic_acceptance or {"test_target": "tests/test_utils.py"},
        requires_discovery=requires_discovery,
        unresolved_ambiguity=unresolved_ambiguity,
    )


class TestLocalRoutingEvidenceAuthority:
    def test_scenario_2_provenance_assigned_and_payloads_derived(self):
        cmd = _make_mutating_cmd()
        res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        assert res.success is True
        assert res.evidence is not None
        assert res.evidence.provenance == LocalRoutingEvidenceProvenance.OPERATOR_EXPLICIT_MECHANICAL_COMMAND
        assert res.evidence.authoritative_change_supplied is True
        assert res.evidence.deterministic_acceptance_supplied is True

    def test_scenario_3_unsupported_source_fails_closed(self):
        res = LocalRoutingEvidenceAuthority.construct_evidence({"unsupported": "dict"})
        assert res.success is False
        assert res.reason_code == LocalRoutingReasonCode.UNSUPPORTED_EVIDENCE_SOURCE

    def test_scenario_4_missing_source_fails_closed(self):
        res = LocalRoutingEvidenceAuthority.construct_evidence(None)
        assert res.success is False
        assert res.reason_code == LocalRoutingReasonCode.MISSING_ROUTING_SOURCE

    def test_scenario_6_missing_authoritative_change_fails_closed(self):
        cmd = _make_mutating_cmd()
        cmd.authoritative_change = None
        res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        assert res.success is False
        assert res.reason_code == LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED

    def test_scenario_7_missing_deterministic_acceptance_fails_closed(self):
        cmd = _make_mutating_cmd()
        cmd.deterministic_acceptance = None
        res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        assert res.success is False
        assert res.reason_code == LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED

    def test_scenario_9_generic_string_not_accepted(self):
        res = LocalRoutingEvidenceAuthority.construct_evidence("Fix helper function")
        assert res.success is False
        assert res.reason_code == LocalRoutingReasonCode.UNSUPPORTED_EVIDENCE_SOURCE

    def test_scenario_10_read_only_log_analysis_with_bounded_read_sources(self):
        cmd = OperatorMechanicalCommand(
            operation_type=LocalMechanicalOperation.LOG_DIAGNOSTIC,
            mutation_mode=LocalMutationMode.READ_ONLY,
            read_sources=["/var/log/minime/api.log"],
        )
        res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        assert res.success is True
        assert res.evidence is not None
        assert res.evidence.mutation_mode == LocalMutationMode.READ_ONLY
        assert res.evidence.read_sources == ["/var/log/minime/api.log"]

    def test_scenario_11_sensitive_path_in_read_sources_escalates(self):
        for path in ["config/secrets.env", "/etc/minime/pki/key.pem", "auth.json"]:
            cmd = OperatorMechanicalCommand(
                operation_type=LocalMechanicalOperation.LOG_DIAGNOSTIC,
                mutation_mode=LocalMutationMode.READ_ONLY,
                read_sources=[path],
            )
            res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
            assert res.success is False
            assert res.reason_code == LocalRoutingReasonCode.FORBIDDEN_SURFACE

    def test_scenario_12_unbounded_read_sources_escalates(self):
        for bad_sources in [[], ["*"], [".."]]:
            cmd = OperatorMechanicalCommand(
                operation_type=LocalMechanicalOperation.LOG_DIAGNOSTIC,
                mutation_mode=LocalMutationMode.READ_ONLY,
                read_sources=bad_sources,
            )
            res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
            assert res.success is False
            assert res.reason_code == LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED


class TestLocalWorkerCapabilityRouter:
    def test_scenario_5_valid_low_risk_task_admitted(self):
        cmd = _make_mutating_cmd()
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        snapshot = _make_snapshot()
        task = _make_task()

        router = LocalWorkerCapabilityRouter()
        decision = router.evaluate_capability_routing(
            task=task, snapshot=snapshot, evidence=auth_res.evidence
        )

        assert decision.verdict == LocalRoutingVerdict.LOCAL_ELIGIBLE
        assert decision.reason_code == LocalRoutingReasonCode.LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY
        assert decision.selected_local_model == local_qwen_model_identity()
        assert decision.escalation_target == EscalationTarget.NONE

    def test_scenario_14_deterministic_routing(self):
        cmd = _make_mutating_cmd()
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        snapshot = _make_snapshot()
        task = _make_task()

        router = LocalWorkerCapabilityRouter()
        d1 = router.evaluate_capability_routing(task=task, snapshot=snapshot, evidence=auth_res.evidence)
        d2 = router.evaluate_capability_routing(task=task, snapshot=snapshot, evidence=auth_res.evidence)
        assert d1.model_dump() == d2.model_dump()

    def test_scenario_15_partial_completeness_empty_missing_signals_admitted(self):
        cmd = _make_mutating_cmd()
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        snapshot = _make_snapshot(
            completeness=ClassificationCompleteness.PARTIAL, missing_signals=[]
        )
        task = _make_task()

        router = LocalWorkerCapabilityRouter()
        decision = router.evaluate_capability_routing(
            task=task, snapshot=snapshot, evidence=auth_res.evidence
        )

        assert decision.verdict == LocalRoutingVerdict.LOCAL_ELIGIBLE

    def test_scenario_16_partial_completeness_nonempty_missing_signals_escalates(self):
        cmd = _make_mutating_cmd()
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        snapshot = _make_snapshot(
            completeness=ClassificationCompleteness.PARTIAL, missing_signals=["no proposal text"]
        )
        task = _make_task()

        router = LocalWorkerCapabilityRouter()
        decision = router.evaluate_capability_routing(
            task=task, snapshot=snapshot, evidence=auth_res.evidence
        )

        assert decision.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert decision.reason_code == LocalRoutingReasonCode.CLASSIFICATION_INCOMPLETE

    def test_scenario_17_minimal_completeness_escalates(self):
        cmd = _make_mutating_cmd()
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        snapshot = _make_snapshot(completeness=ClassificationCompleteness.MINIMAL)
        task = _make_task()

        router = LocalWorkerCapabilityRouter()
        decision = router.evaluate_capability_routing(
            task=task, snapshot=snapshot, evidence=auth_res.evidence
        )

        assert decision.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert decision.reason_code == LocalRoutingReasonCode.CLASSIFICATION_INCOMPLETE

    def test_scenario_18_sensitive_risk_dimension_equals_low_escalates(self):
        for dimension in [
            "security_auth_impact",
            "persistence_impact",
            "provider_orchestration",
            "deployment_config",
            "architectural_impact",
        ]:
            cmd = _make_mutating_cmd()
            auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
            snapshot = _make_snapshot(risk_overrides={dimension: "LOW"})
            task = _make_task()

            router = LocalWorkerCapabilityRouter()
            decision = router.evaluate_capability_routing(
                task=task, snapshot=snapshot, evidence=auth_res.evidence
            )

            assert decision.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
            assert decision.reason_code == LocalRoutingReasonCode.HIGH_RISK_SURFACE

    def test_scenario_24_qwen_14b_not_selectable(self):
        cmd = _make_mutating_cmd()
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        snapshot = _make_snapshot()
        task = _make_task()

        router = LocalWorkerCapabilityRouter()
        decision = router.evaluate_capability_routing(
            task=task, snapshot=snapshot, evidence=auth_res.evidence
        )

        assert decision.selected_local_model != "qwen2.5-coder:14b-instruct-q4_K_M"
        assert decision.selected_local_model == "qwen2.5-coder:7b-instruct-q4_K_M"
