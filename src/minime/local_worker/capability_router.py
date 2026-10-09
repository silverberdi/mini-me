"""Deterministic capability routing engine for the local worker.

Evaluates structural classification snapshots, zero-tolerance risk profiles, surface bounds,
file allowlist boundaries, and trusted routing evidence to decide whether a work unit is eligible
for local Qwen 7B execution or must emit an escalation signal to existing cloud provider policies.
"""

from __future__ import annotations

import logging
from typing import Any

from minime.domain.enums import (
    ClassificationCompleteness,
    ClassificationStage,
    TaskComplexity,
    TaskSurfaceKind,
)
from minime.domain.models import TaskClassificationSnapshot
from minime.local_worker.model_identity import local_qwen_model_identity
from minime.local_worker.models import (
    EscalationTarget,
    LocalMutationMode,
    LocalRoutingDecision,
    LocalRoutingEvidence,
    LocalRoutingEvidenceProvenance,
    LocalRoutingReasonCode,
    LocalRoutingVerdict,
    LocalTaskEnvelope,
)
from minime.local_worker.task_classes import ALLOWED_LOCAL_TASK_CLASSES

logger = logging.getLogger(__name__)

_ALLOWED_SURFACE_KINDS = frozenset(
    {
        TaskSurfaceKind.DOCS_ONLY,
        TaskSurfaceKind.TESTS_ONLY,
        TaskSurfaceKind.BACKEND_SERVICE,
        TaskSurfaceKind.UI_FRONTEND,
    }
)


class LocalWorkerCapabilityRouter:
    """Deterministic pre-inference capability router for local Qwen 7B execution."""

    def evaluate_capability_routing(
        self,
        *,
        task: LocalTaskEnvelope,
        snapshot: TaskClassificationSnapshot | None,
        evidence: LocalRoutingEvidence | None,
        effective_model_identity: str | None = None,
        worktree_path: Any | None = None,
    ) -> LocalRoutingDecision:
        """Evaluate task, snapshot, and evidence for local Qwen 7B admittance."""
        task_class_val = task.task_class.value if hasattr(task.task_class, "value") else str(task.task_class)
        target_model = effective_model_identity or local_qwen_model_identity()

        # 0. Model capability gate
        if target_model != local_qwen_model_identity():
            return self._refuse(
                reason_code=LocalRoutingReasonCode.LOCAL_MODEL_NOT_CAPABLE_FOR_TASK,
                summary=f"Effective local model '{target_model}' does not match canonical identity '{local_qwen_model_identity()}'",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        # 1. Snapshot presence
        if snapshot is None:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.CLASSIFICATION_UNKNOWN,
                summary="Missing pre-execution classification snapshot",
                task_class=task_class_val,
                snapshot=None,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        # 2. Stage gate: PRE_EXECUTION only
        stage_val = snapshot.stage.value if hasattr(snapshot.stage, "value") else str(snapshot.stage)
        if stage_val != ClassificationStage.PRE_EXECUTION.value:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.CLASSIFICATION_UNKNOWN,
                summary=f"Classification stage '{stage_val}' is not PRE_EXECUTION",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        # 3. Completeness & direct missing_signals check
        completeness_val = (
            snapshot.classification_completeness.value
            if hasattr(snapshot.classification_completeness, "value")
            else str(snapshot.classification_completeness)
        )
        if completeness_val != ClassificationCompleteness.PARTIAL.value:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.CLASSIFICATION_INCOMPLETE,
                summary=f"Classification completeness '{completeness_val}' is not PARTIAL",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        # Direct snapshot.missing_signals check
        if snapshot.missing_signals != []:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.CLASSIFICATION_INCOMPLETE,
                summary=f"Pre-execution snapshot contains missing signals: {snapshot.missing_signals}",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        # 4. Complexity gate: LOW only
        complexity_val = (
            snapshot.complexity.value
            if hasattr(snapshot.complexity, "value")
            else str(snapshot.complexity)
        )
        if complexity_val != TaskComplexity.LOW.value:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.COMPLEXITY_NOT_LOW,
                summary=f"Task complexity '{complexity_val}' is not LOW",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        # 5. Zero-tolerance sensitive risk gate
        risk = snapshot.risk_profile
        sensitive_risk_failures: list[str] = []
        if risk.architectural_impact != "NONE":
            sensitive_risk_failures.append(f"architectural_impact={risk.architectural_impact}")
        if risk.persistence_impact != "NONE":
            sensitive_risk_failures.append(f"persistence_impact={risk.persistence_impact}")
        if risk.security_auth_impact != "NONE":
            sensitive_risk_failures.append(f"security_auth_impact={risk.security_auth_impact}")
        if risk.production_runtime != "NONE":
            sensitive_risk_failures.append(f"production_runtime={risk.production_runtime}")
        if risk.provider_orchestration != "NONE":
            sensitive_risk_failures.append(f"provider_orchestration={risk.provider_orchestration}")
        if risk.destructive_operations != "NONE":
            sensitive_risk_failures.append(f"destructive_operations={risk.destructive_operations}")
        if risk.deployment_config != "NONE":
            sensitive_risk_failures.append(f"deployment_config={risk.deployment_config}")

        if sensitive_risk_failures:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.HIGH_RISK_SURFACE,
                summary=f"Sensitive risk dimensions exceed zero-tolerance: {', '.join(sensitive_risk_failures)}",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        if risk.code_change_breadth not in ("NONE", "LOW"):
            return self._refuse(
                reason_code=LocalRoutingReasonCode.HIGH_RISK_SURFACE,
                summary=f"code_change_breadth '{risk.code_change_breadth}' exceeds LOW",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        # 6. Surface gate
        surface_val = (
            snapshot.surface_kind.value
            if hasattr(snapshot.surface_kind, "value")
            else str(snapshot.surface_kind)
        )
        if snapshot.surface_kind not in _ALLOWED_SURFACE_KINDS and surface_val not in [
            s.value for s in _ALLOWED_SURFACE_KINDS
        ]:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.FORBIDDEN_SURFACE,
                summary=f"Surface kind '{surface_val}' is not locally allowed",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        # 7. Task class gate
        if task_class_val not in ALLOWED_LOCAL_TASK_CLASSES:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.TASK_CLASS_NOT_LOCAL,
                summary=f"Task class '{task_class_val}' is not in ALLOWED_LOCAL_TASK_CLASSES",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        # 8. Trusted routing evidence gate
        if evidence is None:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.MISSING_ROUTING_SOURCE,
                summary="Missing trusted LocalRoutingEvidence",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=None,
                allowed_files=task.allowed_files or [],
            )

        if evidence.provenance != LocalRoutingEvidenceProvenance.OPERATOR_EXPLICIT_MECHANICAL_COMMAND:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.UNSUPPORTED_EVIDENCE_SOURCE,
                summary=f"Evidence provenance '{evidence.provenance.value}' is unsupported in V1",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        if evidence.requires_discovery or evidence.unresolved_ambiguity:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.TASK_NOT_MECHANICALLY_EXPLICIT,
                summary="Task evidence requires discovery or contains unresolved ambiguity",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        # 9. Mutating vs Read-Only Boundary Gate
        if evidence.mutation_mode == LocalMutationMode.MUTATING:
            if not evidence.authoritative_change_supplied or not evidence.deterministic_acceptance_supplied:
                return self._refuse(
                    reason_code=LocalRoutingReasonCode.TASK_NOT_MECHANICALLY_EXPLICIT,
                    summary="Mutating task missing authoritative change or deterministic acceptance payload",
                    task_class=task_class_val,
                    snapshot=snapshot,
                    evidence=evidence,
                    allowed_files=task.allowed_files or [],
                )
            if not task.allowed_files or len(task.allowed_files) != 1:
                return self._refuse(
                    reason_code=LocalRoutingReasonCode.MISSING_ALLOWED_FILE_BOUNDARY
                    if not task.allowed_files
                    else LocalRoutingReasonCode.SCOPE_TOO_BROAD,
                    summary=f"Mutating task requires exactly 1 explicit allowed file, got {len(task.allowed_files or [])}",
                    task_class=task_class_val,
                    snapshot=snapshot,
                    evidence=evidence,
                    allowed_files=task.allowed_files or [],
                )
            target_f = task.allowed_files[0]
            if not target_f or not isinstance(target_f, str) or not target_f.strip():
                return self._refuse(
                    reason_code=LocalRoutingReasonCode.MISSING_ALLOWED_FILE_BOUNDARY,
                    summary="Allowed file boundary is empty or invalid",
                    task_class=task_class_val,
                    snapshot=snapshot,
                    evidence=evidence,
                    allowed_files=task.allowed_files or [],
                )
            clean_target = target_f.strip()
            if clean_target.startswith("/") or clean_target.startswith("\\"):
                return self._refuse(
                    reason_code=LocalRoutingReasonCode.MISSING_ALLOWED_FILE_BOUNDARY,
                    summary=f"Allowed file boundary '{clean_target}' is an absolute path",
                    task_class=task_class_val,
                    snapshot=snapshot,
                    evidence=evidence,
                    allowed_files=task.allowed_files or [],
                )
            if ".." in clean_target.split("/") or ".." in clean_target.split("\\"):
                return self._refuse(
                    reason_code=LocalRoutingReasonCode.MISSING_ALLOWED_FILE_BOUNDARY,
                    summary=f"Allowed file boundary '{clean_target}' contains directory traversal",
                    task_class=task_class_val,
                    snapshot=snapshot,
                    evidence=evidence,
                    allowed_files=task.allowed_files or [],
                )
            if "*" in clean_target or "?" in clean_target:
                return self._refuse(
                    reason_code=LocalRoutingReasonCode.MISSING_ALLOWED_FILE_BOUNDARY,
                    summary=f"Allowed file boundary '{clean_target}' contains wildcards",
                    task_class=task_class_val,
                    snapshot=snapshot,
                    evidence=evidence,
                    allowed_files=task.allowed_files or [],
                )
            if clean_target.endswith("/") or clean_target.endswith("\\"):
                return self._refuse(
                    reason_code=LocalRoutingReasonCode.MISSING_ALLOWED_FILE_BOUNDARY,
                    summary=f"Allowed file boundary '{clean_target}' appears to be a directory",
                    task_class=task_class_val,
                    snapshot=snapshot,
                    evidence=evidence,
                    allowed_files=task.allowed_files or [],
                )
            if evidence.target_file and clean_target != evidence.target_file:
                return self._refuse(
                    reason_code=LocalRoutingReasonCode.MISSING_ALLOWED_FILE_BOUNDARY,
                    summary=f"Allowed file '{clean_target}' does not match evidence target file '{evidence.target_file}'",
                    task_class=task_class_val,
                    snapshot=snapshot,
                    evidence=evidence,
                    allowed_files=task.allowed_files or [],
                )
        elif evidence.mutation_mode == LocalMutationMode.READ_ONLY:
            return self._refuse(
                reason_code=LocalRoutingReasonCode.READ_SOURCE_LOADING_UNAVAILABLE,
                summary="Source content binding unavailable for read-only tasks",
                task_class=task_class_val,
                snapshot=snapshot,
                evidence=evidence,
                allowed_files=task.allowed_files or [],
            )

        # 10. Model identity check
        return LocalRoutingDecision(
            verdict=LocalRoutingVerdict.LOCAL_ELIGIBLE,
            reason_code=LocalRoutingReasonCode.LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY,
            reason_summary=f"Task '{task_class_val}' admitted for local Qwen 7B execution",
            classification_snapshot_id=snapshot.id,
            task_class=task_class_val,
            complexity=snapshot.complexity,
            classification_stage=snapshot.stage,
            classification_completeness=snapshot.classification_completeness,
            surface_kind=snapshot.surface_kind,
            risk_evidence={
                "code_change_breadth": risk.code_change_breadth,
                "architectural_impact": risk.architectural_impact,
                "persistence_impact": risk.persistence_impact,
                "security_auth_impact": risk.security_auth_impact,
            },
            allowed_files_evidence=list(task.allowed_files or []),
            routing_evidence=evidence,
            selected_local_model=target_model,
            escalation_target=EscalationTarget.NONE,
            policy_version="1.0.0",
        )

    def _refuse(
        self,
        *,
        reason_code: LocalRoutingReasonCode,
        summary: str,
        task_class: str,
        snapshot: TaskClassificationSnapshot | None,
        evidence: LocalRoutingEvidence | None,
        allowed_files: list[str],
    ) -> LocalRoutingDecision:
        return LocalRoutingDecision(
            verdict=LocalRoutingVerdict.ESCALATE_PROVIDER_POLICY,
            reason_code=reason_code,
            reason_summary=summary,
            classification_snapshot_id=snapshot.id if snapshot else None,
            task_class=task_class,
            complexity=snapshot.complexity if snapshot else None,
            classification_stage=snapshot.stage if snapshot else None,
            classification_completeness=snapshot.classification_completeness if snapshot else None,
            surface_kind=snapshot.surface_kind if snapshot else None,
            allowed_files_evidence=list(allowed_files),
            routing_evidence=evidence,
            selected_local_model=None,
            escalation_target=EscalationTarget.EXISTING_PROVIDER_POLICY,
            policy_version="1.0.0",
        )
