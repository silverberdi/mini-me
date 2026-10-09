"""Deterministic models for the minimal local worker bootstrap.

These models describe a constrained LOW-risk local (Ollama/Qwen) task envelope, its
structured output, preflight/eligibility/validation results, escalation, and the minimal
flat execution evidence record. They contain no operational mutable state such as quota or
process ids; they are pure, serializable domain records.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from minime.domain.enums import (
    ClassificationCompleteness,
    ClassificationStage,
    TaskComplexity,
    TaskSurfaceKind,
)
from minime.local_worker.model_identity import OLLAMA_PROVIDER

DEFAULT_CONTEXT_BUDGET_CHARS: int = 12000


class LocalTaskClass(str, Enum):
    """Canonical LOW-risk task classes for the local worker."""

    SMALL_CODE_FIX = "SMALL_CODE_FIX"
    TEST_AUTHORING = "TEST_AUTHORING"
    LOG_ANALYSIS = "LOG_ANALYSIS"
    SMALL_REFACTOR = "SMALL_REFACTOR"
    API_SMALL_CHANGE = "API_SMALL_CHANGE"
    UI_SMALL_POLISH = "UI_SMALL_POLISH"


class PreflightStatus(str, Enum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    UNREACHABLE = "UNREACHABLE"
    MODEL_MISSING = "MODEL_MISSING"
    NOT_QUALIFIED = "NOT_QUALIFIED"


class EligibilityVerdict(str, Enum):
    ADMIT = "ADMIT"
    REFUSE = "REFUSE"


class EscalationTarget(str, Enum):
    NONE = "NONE"
    EXISTING_PROVIDER_POLICY = "EXISTING_PROVIDER_POLICY"


class LocalResultKind(str, Enum):
    CHANGES_PROPOSED = "CHANGES_PROPOSED"
    NO_CHANGE_JUSTIFIED = "NO_CHANGE_JUSTIFIED"
    UNCERTAIN = "UNCERTAIN"


class LocalValidationVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class LocalRoutingVerdict(str, Enum):
    LOCAL_ELIGIBLE = "LOCAL_ELIGIBLE"
    ESCALATE_PROVIDER_POLICY = "ESCALATE_PROVIDER_POLICY"


class LocalMechanicalOperation(str, Enum):
    TEXT_REPLACEMENT = "TEXT_REPLACEMENT"
    LITERAL_UPDATE = "LITERAL_UPDATE"
    FIXTURE_UPDATE = "FIXTURE_UPDATE"
    LOG_DIAGNOSTIC = "LOG_DIAGNOSTIC"


class LocalMutationMode(str, Enum):
    MUTATING = "MUTATING"
    READ_ONLY = "READ_ONLY"


class LocalRoutingEvidenceProvenance(str, Enum):
    OPERATOR_EXPLICIT_MECHANICAL_COMMAND = "OPERATOR_EXPLICIT_MECHANICAL_COMMAND"
    STRUCTURED_OPENSPEC_TASK_METADATA = "STRUCTURED_OPENSPEC_TASK_METADATA"
    DETERMINISTIC_INTAKE_METADATA = "DETERMINISTIC_INTAKE_METADATA"


class OperatorMechanicalCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation_type: LocalMechanicalOperation
    mutation_mode: LocalMutationMode
    target_file: str | None = None
    target_symbol: str | None = None
    authoritative_change: dict[str, Any] | str | None = None
    deterministic_acceptance: dict[str, Any] | str | None = None
    read_sources: list[str] = Field(default_factory=list)
    requires_discovery: bool = False
    unresolved_ambiguity: bool = False
    command_id: str | None = None


class LocalRoutingEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation_type: LocalMechanicalOperation
    mutation_mode: LocalMutationMode
    target_file: str | None = None
    target_symbol: str | None = None
    authoritative_change_supplied: bool = False
    deterministic_acceptance_supplied: bool = False
    requires_discovery: bool = False
    unresolved_ambiguity: bool = False
    read_sources: list[str] = Field(default_factory=list)
    provenance: LocalRoutingEvidenceProvenance


class LocalRoutingReasonCode(str, Enum):
    LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY = "LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY"
    COMPLEXITY_NOT_LOW = "COMPLEXITY_NOT_LOW"
    CLASSIFICATION_UNKNOWN = "CLASSIFICATION_UNKNOWN"
    CLASSIFICATION_INCOMPLETE = "CLASSIFICATION_INCOMPLETE"
    HIGH_RISK_SURFACE = "HIGH_RISK_SURFACE"
    FORBIDDEN_SURFACE = "FORBIDDEN_SURFACE"
    SCOPE_TOO_BROAD = "SCOPE_TOO_BROAD"
    MULTI_MODULE_SCOPE = "MULTI_MODULE_SCOPE"
    TASK_NOT_MECHANICALLY_EXPLICIT = "TASK_NOT_MECHANICALLY_EXPLICIT"
    TASK_CLASS_NOT_LOCAL = "TASK_CLASS_NOT_LOCAL"
    LOCAL_MODEL_NOT_CAPABLE_FOR_TASK = "LOCAL_MODEL_NOT_CAPABLE_FOR_TASK"
    MISSING_ALLOWED_FILE_BOUNDARY = "MISSING_ALLOWED_FILE_BOUNDARY"
    MISSING_ROUTING_SOURCE = "MISSING_ROUTING_SOURCE"
    UNSUPPORTED_EVIDENCE_SOURCE = "UNSUPPORTED_EVIDENCE_SOURCE"
    AUTHORITY_CONSTRUCTION_FAILED = "AUTHORITY_CONSTRUCTION_FAILED"
    READ_SOURCE_LOADING_UNAVAILABLE = "READ_SOURCE_LOADING_UNAVAILABLE"


class LocalEvidenceAuthorityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool
    evidence: LocalRoutingEvidence | None = None
    reason: str = ""
    reason_code: LocalRoutingReasonCode = LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED


class LocalRoutingDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: LocalRoutingVerdict
    reason_code: LocalRoutingReasonCode
    reason_summary: str
    classification_snapshot_id: str | None = None
    task_class: str
    complexity: TaskComplexity | str | None = None
    classification_stage: ClassificationStage | str | None = None
    classification_completeness: ClassificationCompleteness | str | None = None
    surface_kind: TaskSurfaceKind | str | None = None
    risk_evidence: dict[str, str] = Field(default_factory=dict)
    allowed_files_evidence: list[str] = Field(default_factory=list)
    routing_evidence: LocalRoutingEvidence | None = None
    selected_local_model: str | None = None
    escalation_target: EscalationTarget = EscalationTarget.EXISTING_PROVIDER_POLICY
    policy_version: str = "1.0.0"



class LocalTaskEnvelope(BaseModel):
    """Explicit role + allowed/forbidden surfaces + smallest-patch instruction context."""

    role: str = Field(description="Explicit worker role (LOCAL_WORKER).")
    task_class: LocalTaskClass
    allowed_files: list[str] = Field(
        default_factory=list, description="Explicit allowlist of files/globs the work may touch."
    )
    forbidden_files: list[str] = Field(
        default_factory=list, description="Files/surfaces the work must never touch."
    )
    instruction: str = Field(
        min_length=1, description="Smallest-patch instruction; no architecture redesign."
    )
    context: str = Field(
        default="", description="Bounded context only; no unrelated repository surface."
    )
    no_architecture: bool = True
    no_unrelated_dependencies: bool = True
    max_output_tokens: int = 2048
    timeout_seconds: float = 60.0


class LocalWorkerResult(BaseModel):
    """Constrained structured output of the local model.

    ``NO_CHANGE_JUSTIFIED`` is a valid result the model may choose. Qwen never decides that
    its own work is successful; deterministic validation decides that from real side-effects.
    """

    kind: LocalResultKind = LocalResultKind.CHANGES_PROPOSED
    summary: str = ""
    files_changed: list[str] = Field(default_factory=list)
    patch: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    escalation_required: bool = False
    escalation_reason: str = Field(default="", description="Required when escalation_required.")
    next_action: str = Field(
        default="",
        description="e.g. 'apply_patch', 'no_change', or free-form next step.",
    )

    @property
    def is_no_change_justified(self) -> bool:
        return self.kind is LocalResultKind.NO_CHANGE_JUSTIFIED


class PreflightResult(BaseModel):
    provider: str
    model: str
    status: PreflightStatus
    reason: str = ""
    reachable: bool = False
    model_present: bool = False


class EligibilityDecision(BaseModel):
    verdict: EligibilityVerdict
    task_class: str
    model: str
    reason: str = ""
    forbidden_surface: str | None = None
    escalation_target: EscalationTarget = EscalationTarget.NONE

    @property
    def admitted(self) -> bool:
        return self.verdict is EligibilityVerdict.ADMIT


class ValidationResult(BaseModel):
    verdict: LocalValidationVerdict
    authority: str = "deterministic"
    reason: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict is LocalValidationVerdict.PASS


class EscalationDecision(BaseModel):
    required: bool = False
    target: EscalationTarget = EscalationTarget.NONE
    reason: str = ""


LOCAL_WORKER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["CHANGES_PROPOSED", "NO_CHANGE_JUSTIFIED"],
        },
        "summary": {"type": "string"},
        "files_changed": {
            "type": "array",
            "items": {"type": "string"},
        },
        "patch": {
            "type": ["string", "null"],
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "escalation_required": {"type": "boolean"},
        "escalation_reason": {"type": "string"},
        "next_action": {"type": "string"},
    },
    "required": [
        "kind",
        "summary",
        "files_changed",
        "patch",
        "confidence",
        "escalation_required",
        "escalation_reason",
        "next_action",
    ],
    "additionalProperties": False,
}


class LocalExecutionEvidence(BaseModel):
    """Minimal structured evidence: provider, model, task class, attempt, result,
    validation result, escalation."""

    provider: str = OLLAMA_PROVIDER
    model: str
    task_class: str
    attempt: int = 1  # starts at initial attempt; corrective attempt uses 2
    result: LocalResultKind
    result_class: str
    validation_result: LocalValidationVerdict
    escalation: EscalationDecision = Field(default_factory=EscalationDecision)
    summary: str = ""
    corrections_used: int = 0
    patch_proposed: bool = False
    patch_applied: bool = False
    authoritative_changed_files: list[str] = Field(default_factory=list)
    worktree_path: str | None = None
    raw_output_excerpt: str | None = None
    model_output_failure_reason: str | None = None
    raw_output_length: int | None = None

    @property
    def fully_validated(self) -> bool:
        return self.validation_result is LocalValidationVerdict.PASS
