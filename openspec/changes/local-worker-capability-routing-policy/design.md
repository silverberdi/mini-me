# Design: Local Worker Capability Routing Policy

## Architecture Decisions

### 1. Subsystem Separation & Authority
Preserve strict architectural separation across three distinct components:
- **`TaskComplexityRiskClassifier`:** Responsible ONLY for producing observable, provider-agnostic classification snapshots (`TaskClassificationSnapshot`) containing complexity (`TaskComplexity.LOW`, `MEDIUM`, `HIGH`, `UNKNOWN`), multi-dimensional risk profiles, structural surface kinds (`TaskSurfaceKind`), and completeness metrics (`ClassificationCompleteness.COMPLETE`, `PARTIAL`, `MINIMAL`). It NEVER selects models or routes work.
- **`LocalWorkerCapabilityRouter`:** Responsible for taking the classification snapshot, task envelope, and structured `LocalRoutingEvidence` to answer: *"Is this work safe, mechanically explicit, and sufficiently simple to attempt with canonical local Qwen 7B?"*
- **`ProviderPolicy`:** Responsible for selecting between primary cloud providers (Codex / Antigravity) and OpenRouter drain fallback whenever a task emits an escalation signal (`EscalationTarget.EXISTING_PROVIDER_POLICY`).

### 2. Typed Routing Input & Decision Models

#### Typed Explicitness Evidence Model (`LocalRoutingEvidence`):
```python
class LocalMechanicalOperation(str, Enum):
    TEXT_REPLACEMENT = "TEXT_REPLACEMENT"
    LITERAL_UPDATE = "LITERAL_UPDATE"
    FIXTURE_UPDATE = "FIXTURE_UPDATE"
    LOG_DIAGNOSTIC = "LOG_DIAGNOSTIC"

class LocalMutationMode(str, Enum):
    MUTATING = "MUTATING"
    READ_ONLY = "READ_ONLY"

@dataclass(frozen=True)
class LocalRoutingEvidence:
    operation_type: LocalMechanicalOperation
    mutation_mode: LocalMutationMode
    target_file: str | None
    target_symbol: str | None
    authoritative_change_supplied: bool
    deterministic_acceptance_supplied: bool
    requires_discovery: bool
    unresolved_ambiguity: bool
    evidence_source: str = "UPSTREAM_CONTEXT"
```
*Rule: Eligibility MUST NOT be inferred by parsing `task.instruction` or `task.context` natural language text. The router MUST NOT use prompt heuristics. An upstream deterministic authority constructs `LocalRoutingEvidence`.*

#### Decision Model (`LocalRoutingDecision`):
```python
@dataclass(frozen=True)
class LocalRoutingDecision:
    verdict: LocalRoutingVerdict  # LOCAL_ELIGIBLE, ESCALATE_PROVIDER_POLICY, INSUFFICIENT_EVIDENCE
    reason_code: LocalRoutingReasonCode
    reason_summary: str
    classification_snapshot_id: str | None
    task_class: str
    complexity: TaskComplexity
    classification_stage: ClassificationStage
    classification_completeness: ClassificationCompleteness
    surface_kind: TaskSurfaceKind
    risk_evidence: dict[str, str]
    allowed_files_evidence: list[str]
    routing_evidence: LocalRoutingEvidence | None
    selected_local_model: str | None  # qwen2.5-coder:7b-instruct-q4_K_M or None
    escalation_target: EscalationTarget  # EXISTING_PROVIDER_POLICY or NONE
    policy_version: str = "1.0.0"
```
If `verdict` evaluates to `INSUFFICIENT_EVIDENCE` or policy evaluation encounters an error, the router fails closed: `verdict = ESCALATE_PROVIDER_POLICY` and `escalation_target = EscalationTarget.EXISTING_PROVIDER_POLICY`.

### 3. Deterministic Policy Rules & Gate Precedence

To achieve `LOCAL_ELIGIBLE` status, a task envelope MUST pass ALL of the following gates sequentially:

1. **Snapshot Gate:** A `PRE_EXECUTION` `TaskClassificationSnapshot` MUST exist. Missing snapshot -> `CLASSIFICATION_UNKNOWN` -> `ESCALATE_PROVIDER_POLICY`.
2. **Completeness & Stage Gate:** For `PRE_EXECUTION` stage snapshots:
   - Canonical `classify_pre_execution()` initializes `classification_completeness` to `ClassificationCompleteness.PARTIAL` and never produces `COMPLETE`.
   - `PRE_EXECUTION` stage is accepted with `completeness == ClassificationCompleteness.PARTIAL` ONLY when `missing_signals` is empty (`len(snapshot.signals.get("missing_signals", [])) == 0`).
   - Any snapshot with `completeness == ClassificationCompleteness.MINIMAL` or non-empty `missing_signals` MUST escalate -> `CLASSIFICATION_INCOMPLETE` -> `ESCALATE_PROVIDER_POLICY`.
3. **Complexity Gate:** `complexity` MUST equal `TaskComplexity.LOW`. `MEDIUM`, `HIGH`, or `UNKNOWN` -> `COMPLEXITY_NOT_LOW` -> `ESCALATE_PROVIDER_POLICY`.
4. **Zero-Tolerance Sensitive Risk Gate:**
   - All sensitive risk dimensions (`architectural_impact`, `persistence_impact`, `security_auth_impact`, `production_runtime`, `provider_orchestration`, `destructive_operations`, `deployment_config`) MUST equal `"NONE"` (or `TaskRiskLevel.NONE`).
   - `code_change_breadth` MAY be `"NONE"` or `"LOW"`.
   - Any non-`"NONE"` value in sensitive dimensions -> `HIGH_RISK_SURFACE` -> `ESCALATE_PROVIDER_POLICY`.
   - `destructive_operations == "PRESENT"` -> `HIGH_RISK_SURFACE` -> `ESCALATE_PROVIDER_POLICY`.
5. **Surface Gate:** `surface_kind` MUST be an allowed surface (`DOCS_ONLY`, `TESTS_ONLY`, `BACKEND_SERVICE`, `UI_FRONTEND`). `MIGRATION_SCHEMA`, `CONFIG_ONLY`, `INFRASTRUCTURE_DEPLOYMENT`, `ORCHESTRATION_LIFECYCLE`, `SECURITY_AUTH`, `MIXED`, or `UNKNOWN` -> `FORBIDDEN_SURFACE` -> `ESCALATE_PROVIDER_POLICY`.
6. **Task Class Gate:** `task_class` MUST be an allowed local task class (`SMALL_CODE_FIX`, `TEST_AUTHORING`, `LOG_ANALYSIS`, `SMALL_REFACTOR`, `API_SMALL_CHANGE`, `UI_SMALL_POLISH`). Unlisted class -> `TASK_CLASS_NOT_LOCAL` -> `ESCALATE_PROVIDER_POLICY`.
7. **Typed Explicitness Gate:** `LocalRoutingEvidence` MUST be present and valid:
   - `requires_discovery == True` or `unresolved_ambiguity == True` -> `TASK_NOT_MECHANICALLY_EXPLICIT` -> `ESCALATE_PROVIDER_POLICY`.
   - `authoritative_change_supplied == False` (for mutating tasks) -> `TASK_NOT_MECHANICALLY_EXPLICIT` -> `ESCALATE_PROVIDER_POLICY`.
   - `deterministic_acceptance_supplied == False` -> `TASK_NOT_MECHANICALLY_EXPLICIT` -> `ESCALATE_PROVIDER_POLICY`.
8. **Explicit File Boundary Gate:**
   - For mutating tasks (`mutation_mode == MUTATING`): `allowed_files` MUST be present, contain exactly 1 target file (`len(allowed_files) == 1`), and match `routing_evidence.target_file`. Absent, empty, or multi-file allowlist -> `MISSING_ALLOWED_FILE_BOUNDARY` / `SCOPE_TOO_BROAD` / `MULTI_MODULE_SCOPE` -> `ESCALATE_PROVIDER_POLICY`.
   - For non-mutating tasks (`mutation_mode == READ_ONLY`): Code edit file allowlist is not required, but strict read-only safety applies (zero secrets/auth paths).
9. **Model Capability Gate:** Canonical model identity MUST be `qwen2.5-coder:7b-instruct-q4_K_M`. Qwen 14B or unknown models -> `LOCAL_MODEL_NOT_CAPABLE_FOR_TASK` -> `ESCALATE_PROVIDER_POLICY`.

### 4. Integration Point in Execution Pipeline
Integrate `LocalWorkerCapabilityRouter.evaluate_capability_routing()` inside `LocalWorkerService.run()` prior to `preflight`, context packaging, or model dispatch:
```python
# Inside LocalWorkerService.run():
routing_decision = self.capability_router.evaluate_capability_routing(
    task=task,
    snapshot=classification_snapshot,
    routing_evidence=routing_evidence,
    worktree_path=worktree_path,
)
if routing_decision.verdict != LocalRoutingVerdict.LOCAL_ELIGIBLE:
    return ServiceOutcome(
        eligibility=_refusal_from_routing(routing_decision),
        preflight=PreflightResult(
            provider=OLLAMA_PROVIDER,
            model=self.model,
            status=PreflightStatus.NOT_QUALIFIED,
            reason=routing_decision.reason_summary,
        ),
        evidence=_routing_refusal_evidence(routing_decision),
    )
```
Refusal produces `PreflightStatus.NOT_QUALIFIED`, sets `escalation.required = True` and `escalation.target = EscalationTarget.EXISTING_PROVIDER_POLICY`, and immediately returns with zero Ollama API calls and zero token consumption. Caller consumes the escalation signal according to existing provider orchestration authority (automatic provider selection remains OUT OF SCOPE).

### 5. Differentiating Mutating vs Read-Only Non-Mutating Tasks
- **Mutating Tasks (`SMALL_CODE_FIX`, `TEST_AUTHORING`, `SMALL_REFACTOR`, `API_SMALL_CHANGE`, `UI_SMALL_POLISH`):** `mutation_mode == LocalMutationMode.MUTATING`. Require strict single-file `allowed_files` boundary (`len(allowed_files) == 1`), `authoritative_change_supplied == True`, worktree mutation isolation, patch policy verification, and post-apply diff verification.
- **Read-Only Non-Mutating Tasks (`LOG_ANALYSIS`):** `mutation_mode == LocalMutationMode.READ_ONLY`. Cannot mutate Git or filesystem. Evaluated without requiring code edit file allowlist boundaries. Fail closed on secrets, credentials, auth/security paths. Diagnostic output remains strictly non-authoritative.

### 6. Stable Reason Codes
- `LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY`
- `COMPLEXITY_NOT_LOW`
- `CLASSIFICATION_UNKNOWN`
- `CLASSIFICATION_INCOMPLETE`
- `HIGH_RISK_SURFACE`
- `FORBIDDEN_SURFACE`
- `SCOPE_TOO_BROAD`
- `MULTI_MODULE_SCOPE`
- `TASK_NOT_MECHANICALLY_EXPLICIT`
- `TASK_CLASS_NOT_LOCAL`
- `LOCAL_MODEL_NOT_CAPABLE_FOR_TASK`
- `MISSING_ALLOWED_FILE_BOUNDARY`
