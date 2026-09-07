"""Deterministic models for the minimal local worker bootstrap.

These models describe a constrained LOW-risk local (Ollama/Qwen) task envelope, its
structured output, preflight/eligibility/validation results, escalation, and the minimal
flat execution evidence record. They contain no operational mutable state such as quota or
process ids; they are pure, serializable domain records.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from minime.local_worker.model_identity import OLLAMA_PROVIDER


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

    @property
    def fully_validated(self) -> bool:
        return self.validation_result is LocalValidationVerdict.PASS
