"""Unit tests for LocalRoutingEvidenceAuthority and LocalWorkerCapabilityRouter.

Tests all scenarios in the acceptance test matrix for local-worker-capability-routing-policy.
"""

from typing import Any

import pytest
from pydantic import ValidationError

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


_SENTINEL = object()


def _make_mutating_cmd(
    target_file: str = "src/minime/utils.py",
    authoritative_change: Any = _SENTINEL,
    deterministic_acceptance: Any = _SENTINEL,
    requires_discovery: bool = False,
    unresolved_ambiguity: bool = False,
) -> OperatorMechanicalCommand:
    auth = {"replacement": "def foo(): pass"} if authoritative_change is _SENTINEL else authoritative_change
    det = {"test_target": "tests/test_utils.py"} if deterministic_acceptance is _SENTINEL else deterministic_acceptance
    return OperatorMechanicalCommand(
        operation_type=LocalMechanicalOperation.TEXT_REPLACEMENT,
        mutation_mode=LocalMutationMode.MUTATING,
        target_file=target_file,
        authoritative_change=auth,
        deterministic_acceptance=det,
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
        cmd = _make_mutating_cmd(authoritative_change=None)
        res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        assert res.success is False
        assert res.reason_code == LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED

    def test_scenario_7_missing_deterministic_acceptance_fails_closed(self):
        cmd = _make_mutating_cmd(deterministic_acceptance=None)
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

    def test_authority_explicit_requires_discovery_and_ambiguity_refusal(self):
        cmd_disc = _make_mutating_cmd(requires_discovery=True)
        res_disc = LocalRoutingEvidenceAuthority.construct_evidence(cmd_disc)
        assert res_disc.success is False
        assert res_disc.reason_code == LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED

        cmd_ambig = _make_mutating_cmd(unresolved_ambiguity=True)
        res_ambig = LocalRoutingEvidenceAuthority.construct_evidence(cmd_ambig)
        assert res_ambig.success is False
        assert res_ambig.reason_code == LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED

    def test_mutating_target_boundary_hardening_in_authority(self):
        # Absolute paths
        cmd_abs = _make_mutating_cmd(target_file="/etc/passwd")
        res_abs = LocalRoutingEvidenceAuthority.construct_evidence(cmd_abs)
        assert res_abs.success is False
        assert res_abs.reason_code == LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED

        # Traversal
        cmd_trav = _make_mutating_cmd(target_file="../src/minime/utils.py")
        res_trav = LocalRoutingEvidenceAuthority.construct_evidence(cmd_trav)
        assert res_trav.success is False
        assert res_trav.reason_code == LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED

        # Directory target
        cmd_dir = _make_mutating_cmd(target_file="src/minime/")
        res_dir = LocalRoutingEvidenceAuthority.construct_evidence(cmd_dir)
        assert res_dir.success is False
        assert res_dir.reason_code == LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED


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

    def test_classification_stage_gates(self):
        cmd = _make_mutating_cmd()
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        task = _make_task()
        router = LocalWorkerCapabilityRouter()

        # Missing snapshot
        d_none = router.evaluate_capability_routing(task=task, snapshot=None, evidence=auth_res.evidence)
        assert d_none.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert d_none.reason_code == LocalRoutingReasonCode.CLASSIFICATION_UNKNOWN

        # POST_MATERIALIZATION stage
        snap_post = _make_snapshot(stage=ClassificationStage.POST_MATERIALIZATION)
        d_post = router.evaluate_capability_routing(task=task, snapshot=snap_post, evidence=auth_res.evidence)
        assert d_post.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert d_post.reason_code == LocalRoutingReasonCode.CLASSIFICATION_UNKNOWN

    def test_classification_completeness_and_missing_signals(self):
        cmd = _make_mutating_cmd()
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        task = _make_task()
        router = LocalWorkerCapabilityRouter()

        # MINIMAL completeness -> refusal
        snap_min = _make_snapshot(completeness=ClassificationCompleteness.MINIMAL)
        d_min = router.evaluate_capability_routing(task=task, snapshot=snap_min, evidence=auth_res.evidence)
        assert d_min.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert d_min.reason_code == LocalRoutingReasonCode.CLASSIFICATION_INCOMPLETE

        # PARTIAL + missing_signals -> refusal
        snap_missing = _make_snapshot(completeness=ClassificationCompleteness.PARTIAL, missing_signals=["no proposal"])
        d_missing = router.evaluate_capability_routing(task=task, snapshot=snap_missing, evidence=auth_res.evidence)
        assert d_missing.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert d_missing.reason_code == LocalRoutingReasonCode.CLASSIFICATION_INCOMPLETE

    def test_complexity_gates(self):
        cmd = _make_mutating_cmd()
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        task = _make_task()
        router = LocalWorkerCapabilityRouter()

        for comp in [TaskComplexity.MEDIUM, TaskComplexity.HIGH, TaskComplexity.UNKNOWN]:
            snap = _make_snapshot(complexity=comp)
            d = router.evaluate_capability_routing(task=task, snapshot=snap, evidence=auth_res.evidence)
            assert d.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
            assert d.reason_code == LocalRoutingReasonCode.COMPLEXITY_NOT_LOW

    def test_risk_dimension_gates(self):
        router = LocalWorkerCapabilityRouter()

        # Sensitive risk dimensions set to LOW -> refusal
        sensitive_dimensions = [
            ("architectural_impact", "LOW"),
            ("persistence_impact", "LOW"),
            ("security_auth_impact", "LOW"),
            ("production_runtime", "LOW"),
            ("provider_orchestration", "LOW"),
            ("destructive_operations", "PRESENT"),
            ("deployment_config", "LOW"),
        ]
        for dimension, val in sensitive_dimensions:
            cmd = _make_mutating_cmd()
            auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
            snap = _make_snapshot(risk_overrides={dimension: val})
            task = _make_task()

            d = router.evaluate_capability_routing(task=task, snapshot=snap, evidence=auth_res.evidence)
            assert d.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
            assert d.reason_code == LocalRoutingReasonCode.HIGH_RISK_SURFACE

        # code_change_breadth LOW alone remains eligible
        cmd_low = _make_mutating_cmd()
        auth_low = LocalRoutingEvidenceAuthority.construct_evidence(cmd_low)
        snap_low = _make_snapshot(risk_overrides={"code_change_breadth": "LOW"})
        task_low = _make_task()

        d_low = router.evaluate_capability_routing(task=task_low, snapshot=snap_low, evidence=auth_low.evidence)
        assert d_low.verdict == LocalRoutingVerdict.LOCAL_ELIGIBLE

    def test_surface_kind_gates(self):
        router = LocalWorkerCapabilityRouter()
        forbidden_surfaces = [
            TaskSurfaceKind.MIGRATION_SCHEMA,
            TaskSurfaceKind.CONFIG_ONLY,
            TaskSurfaceKind.INFRASTRUCTURE_DEPLOYMENT,
            TaskSurfaceKind.ORCHESTRATION_LIFECYCLE,
            TaskSurfaceKind.SECURITY_AUTH,
            TaskSurfaceKind.MIXED,
            TaskSurfaceKind.UNKNOWN,
        ]
        for surface in forbidden_surfaces:
            cmd = _make_mutating_cmd()
            auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
            snap = _make_snapshot(surface=surface)
            task = _make_task()

            d = router.evaluate_capability_routing(task=task, snapshot=snap, evidence=auth_res.evidence)
            assert d.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
            assert d.reason_code == LocalRoutingReasonCode.FORBIDDEN_SURFACE

    def test_mutation_boundary_gates(self):
        router = LocalWorkerCapabilityRouter()
        cmd = _make_mutating_cmd(target_file="src/minime/utils.py")
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        snap = _make_snapshot()

        # No allowed file
        task_no_files = _make_task(allowed_files=[])
        d_no_files = router.evaluate_capability_routing(task=task_no_files, snapshot=snap, evidence=auth_res.evidence)
        assert d_no_files.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert d_no_files.reason_code == LocalRoutingReasonCode.MISSING_ALLOWED_FILE_BOUNDARY

        # Two allowed files
        task_two_files = _make_task(allowed_files=["src/minime/utils.py", "src/minime/service.py"])
        d_two_files = router.evaluate_capability_routing(task=task_two_files, snapshot=snap, evidence=auth_res.evidence)
        assert d_two_files.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert d_two_files.reason_code == LocalRoutingReasonCode.SCOPE_TOO_BROAD

        # Wildcard allowed file
        task_wildcard = _make_task(allowed_files=["src/minime/*.py"])
        d_wildcard = router.evaluate_capability_routing(task=task_wildcard, snapshot=snap, evidence=auth_res.evidence)
        assert d_wildcard.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert d_wildcard.reason_code == LocalRoutingReasonCode.MISSING_ALLOWED_FILE_BOUNDARY

        # Target file != allowed file
        task_mismatch = _make_task(allowed_files=["src/minime/other.py"])
        d_mismatch = router.evaluate_capability_routing(task=task_mismatch, snapshot=snap, evidence=auth_res.evidence)
        assert d_mismatch.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert d_mismatch.reason_code == LocalRoutingReasonCode.MISSING_ALLOWED_FILE_BOUNDARY

    def test_model_capability_gate(self):
        cmd = _make_mutating_cmd()
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        snap = _make_snapshot()
        task = _make_task()
        router = LocalWorkerCapabilityRouter()

        # Canonical 7B -> passes model gate
        d_7b = router.evaluate_capability_routing(
            task=task,
            snapshot=snap,
            evidence=auth_res.evidence,
            effective_model_identity="qwen2.5-coder:7b-instruct-q4_K_M",
        )
        assert d_7b.verdict == LocalRoutingVerdict.LOCAL_ELIGIBLE
        assert d_7b.selected_local_model == "qwen2.5-coder:7b-instruct-q4_K_M"

        # Qwen 14B -> refused by model gate
        d_14b = router.evaluate_capability_routing(
            task=task,
            snapshot=snap,
            evidence=auth_res.evidence,
            effective_model_identity="qwen2.5-coder:14b-instruct-q4_K_M",
        )
        assert d_14b.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert d_14b.reason_code == LocalRoutingReasonCode.LOCAL_MODEL_NOT_CAPABLE_FOR_TASK
        assert d_14b.selected_local_model is None

        # Unknown model -> refused by model gate
        d_unknown = router.evaluate_capability_routing(
            task=task,
            snapshot=snap,
            evidence=auth_res.evidence,
            effective_model_identity="llama3:8b",
        )
        assert d_unknown.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert d_unknown.reason_code == LocalRoutingReasonCode.LOCAL_MODEL_NOT_CAPABLE_FOR_TASK

    def test_read_only_tasks_refused_due_to_loading_unavailability(self):
        cmd = OperatorMechanicalCommand(
            operation_type=LocalMechanicalOperation.LOG_DIAGNOSTIC,
            mutation_mode=LocalMutationMode.READ_ONLY,
            read_sources=["/var/log/minime/api.log"],
        )
        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        snap = _make_snapshot()
        task = _make_task(allowed_files=[])

        router = LocalWorkerCapabilityRouter()
        decision = router.evaluate_capability_routing(
            task=task, snapshot=snap, evidence=auth_res.evidence
        )

        assert decision.verdict == LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY
        assert decision.reason_code == LocalRoutingReasonCode.READ_SOURCE_LOADING_UNAVAILABLE

    def test_value_object_immutability(self):
        cmd = _make_mutating_cmd()
        with pytest.raises((ValidationError, TypeError)):
            cmd.target_file = "src/other.py"  # type: ignore[misc]

        auth_res = LocalRoutingEvidenceAuthority.construct_evidence(cmd)
        with pytest.raises((ValidationError, TypeError)):
            auth_res.success = False  # type: ignore[misc]

        evidence = auth_res.evidence
        assert evidence is not None
        with pytest.raises((ValidationError, TypeError)):
            evidence.authoritative_change_supplied = False  # type: ignore[misc]

        snapshot = _make_snapshot()
        task = _make_task()
        router = LocalWorkerCapabilityRouter()
        decision = router.evaluate_capability_routing(task=task, snapshot=snapshot, evidence=evidence)
        with pytest.raises((ValidationError, TypeError)):
            decision.verdict = LocalRoutingVerdict.LOCAL_ELIGIBLE  # type: ignore[misc]
