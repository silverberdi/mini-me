# Design: Local Worker Capability Routing Policy

## Architecture Decisions

### 1. Subsystem Separation & Authority
Preserve strict architectural separation across three distinct components:
- **`TaskComplexityRiskClassifier`:** Responsible ONLY for producing observable, provider-agnostic classification snapshots (`TaskClassificationSnapshot`) containing complexity (`TaskComplexity.LOW`, `MEDIUM`, `HIGH`, `UNKNOWN`), multi-dimensional risk profiles, structural surface kinds (`TaskSurfaceKind`), and completeness metrics (`ClassificationCompleteness.COMPLETE`, `PARTIAL`, `MINIMAL`). It NEVER selects models or routes work.
- **`LocalWorkerCapabilityRouter`:** Responsible for taking the classification snapshot, task envelope, and structural explicitness evidence to answer: *"Is this work safe, mechanically explicit, and sufficiently simple to attempt with canonical local Qwen 7B?"*
- **`ProviderPolicy`:** Responsible for selecting between primary cloud providers (Codex / Antigravity) and OpenRouter drain fallback whenever a task is refused by local capability routing or requires cloud-level capabilities.

### 2. Decision Model (`LocalRoutingDecision`)
Introduce a structured, evidence-bearing routing decision result:
```python
@dataclass(frozen=True)
class LocalRoutingDecision:
    verdict: LocalRoutingVerdict  # LOCAL_ELIGIBLE, ESCALATE_PROVIDER_POLICY, INSUFFICIENT_EVIDENCE
    reason_code: LocalRoutingReasonCode
    reason_summary: str
    classification_snapshot_id: str | None
    task_class: str
    complexity: TaskComplexity  # LOW, MEDIUM, HIGH, UNKNOWN
    classification_stage: ClassificationStage  # PRE_EXECUTION, POST_MATERIALIZATION
    classification_completeness: ClassificationCompleteness  # COMPLETE, PARTIAL, MINIMAL
    surface_kind: TaskSurfaceKind
    risk_evidence: dict[str, str]
    allowed_files_evidence: list[str]
    explicitness_evidence: dict[str, Any]
    selected_local_model: str | None  # qwen2.5-coder:7b-instruct-q4_K_M or None
    escalation_target: EscalationTarget  # EXISTING_PROVIDER_POLICY or NONE
    policy_version: str = "1.0.0"
```

If `verdict` evaluates to `INSUFFICIENT_EVIDENCE` or policy evaluation encounters an error, the router fails closed and sets `verdict = ESCALATE_PROVIDER_POLICY` and `escalation_target = EscalationTarget.EXISTING_PROVIDER_POLICY`.

### 3. Deterministic Policy Rules & Gate Precedence
To achieve `LOCAL_ELIGIBLE` status, a task envelope MUST pass ALL of the following gates sequentially:
1. **Snapshot Gate:** A `PRE_EXECUTION` `TaskClassificationSnapshot` MUST exist. Missing snapshot -> `CLASSIFICATION_UNKNOWN` -> `ESCALATE_PROVIDER_POLICY`.
2. **Completeness Gate:** `classification_completeness` MUST equal `ClassificationCompleteness.COMPLETE`. `PARTIAL` or `MINIMAL` -> `CLASSIFICATION_INCOMPLETE` -> `ESCALATE_PROVIDER_POLICY`.
3. **Complexity Gate:** `complexity` MUST equal `TaskComplexity.LOW`. `MEDIUM`, `HIGH`, or `UNKNOWN` -> `COMPLEXITY_NOT_LOW` -> `ESCALATE_PROVIDER_POLICY`.
4. **Risk Gate:** All high-risk dimensions (persistence/schema/migration, security/auth, provider/orchestration, deployment/runtime/infrastructure, destructive operations, lifecycle/state-machine, architecture, provider policy) MUST equal `NONE` or `LOW` (zero `HIGH` risk dimensions permitted). Any `HIGH` risk -> `HIGH_RISK_SURFACE` -> `ESCALATE_PROVIDER_POLICY`.
5. **Surface Gate:** `surface_kind` MUST NOT be `MIGRATION_SCHEMA`, `CONFIG_ONLY`, `INFRASTRUCTURE_DEPLOYMENT`, `ORCHESTRATION_LIFECYCLE`, `SECURITY_AUTH`, `MIXED`, or `UNKNOWN`. Forbidden surface -> `FORBIDDEN_SURFACE` -> `ESCALATE_PROVIDER_POLICY`.
6. **Task Class Gate:** `task_class` MUST be an allowed local task class (`SMALL_CODE_FIX`, `TEST_AUTHORING`, `LOG_ANALYSIS`, `SMALL_REFACTOR`, `API_SMALL_CHANGE`, `UI_SMALL_POLISH`). Unlisted class -> `TASK_CLASS_NOT_LOCAL` -> `ESCALATE_PROVIDER_POLICY`.
7. **Explicit Boundary Gate:** For mutating task classes, `allowed_files` MUST be present and contain $\le 1$ explicit target file (`len(allowed_files) == 1`). Absent, empty, or multi-file allowlist -> `MISSING_ALLOWED_FILE_BOUNDARY` / `SCOPE_TOO_BROAD` / `MULTI_MODULE_SCOPE` -> `ESCALATE_PROVIDER_POLICY`.
8. **Deterministic Mechanical Explicitness Gate:** The task MUST provide observable, structured evidence of mechanical transformation:
   - `explicit_operation_type`: Upstream-declared mechanical operation (e.g. `TEXT_REPLACEMENT`, `FIXTURE_UPDATE`, `LITERAL_UPDATE`, `LOG_DIAGNOSTIC`).
   - `authoritative_context_supplied`: Desired replacement value, contract, or fixture value is explicitly supplied in context.
   - `zero_unresolved_discovery_flags`: No unresolved debugging/discovery flags, no broad "fix failing test" without explicit fixture values, no requirement to infer intended behavior across services.
   - Tasks lacking structured explicitness evidence -> `TASK_NOT_MECHANICALLY_EXPLICIT` -> `ESCALATE_PROVIDER_POLICY`.
9. **Model Capability Gate:** Canonical model identity MUST be `qwen2.5-coder:7b-instruct-q4_K_M`. Qwen 14B or unknown models -> `LOCAL_MODEL_NOT_CAPABLE_FOR_TASK` -> `ESCALATE_PROVIDER_POLICY`.

### 4. Integration Point in Execution Pipeline
Integrate `LocalWorkerCapabilityRouter.evaluate_capability_routing()` inside `LocalWorkerService.run()` prior to `preflight`, context packaging, or model dispatch:
```python
# Inside LocalWorkerService.run():
routing_decision = self.capability_router.evaluate_capability_routing(
    task=task,
    snapshot=classification_snapshot,
    worktree_path=worktree_path,
)
if routing_decision.verdict != LocalRoutingVerdict.LOCAL_ELIGIBLE:
    return ServiceOutcome(
        eligibility=_refusal_from_routing(routing_decision),
        preflight=PreflightResult(status=PreflightStatus.SKIPPED_LOCAL_REFUSAL),
        evidence=_routing_refusal_evidence(routing_decision),
    )
```
This guarantees zero Ollama HTTP requests and zero token consumption when a task is refused.

### 5. Differentiating Mutating vs Read-Only Non-Mutating Tasks
- **Mutating Tasks (`SMALL_CODE_FIX`, `TEST_AUTHORING`, `SMALL_REFACTOR`, `API_SMALL_CHANGE`, `UI_SMALL_POLISH`):** Require strict single-file `allowed_files` boundary, worktree mutation isolation, patch policy verification, and post-apply diff verification.
- **Read-Only Non-Mutating Tasks (`LOG_ANALYSIS`):** Cannot mutate Git or filesystem. Must pass classification, risk, and explicitness gates (no secrets/sensitive content), but do not require code edit file allowlist boundaries. Local output remains strictly non-authoritative diagnostic evidence.

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
