# Design: Local Worker Capability Routing Policy

## Architecture Decisions

### 1. Subsystem Separation & Authority
Preserve strict architectural separation across three distinct components:
- **`TaskComplexityRiskClassifier`:** Responsible ONLY for producing observable, provider-agnostic classification snapshots (`TaskClassificationSnapshot`) containing complexity (`TaskComplexity.LOW`, `MEDIUM`, `HIGH`, `UNKNOWN`), multi-dimensional risk profiles (`TaskRiskProfile`), structural surface kinds (`TaskSurfaceKind`), and completeness metrics (`ClassificationCompleteness.COMPLETE`, `PARTIAL`, `MINIMAL`). It NEVER selects models or routes work.
- **`LocalRoutingEvidenceAuthority`:** Responsible ONLY for validating source-backed inputs (`LocalRoutingEvidenceSource`) and constructing trusted `LocalRoutingEvidence` with verifiable provenance. Callers CANNOT set provenance or assert evidence booleans directly.
- **`LocalWorkerCapabilityRouter`:** Responsible for taking the classification snapshot, task envelope, and trusted `LocalRoutingEvidence` from the authority to answer: *"Is this work safe, mechanically explicit, and sufficiently simple to attempt with canonical local Qwen 7B?"*
- **`ProviderPolicy`:** Responsible for selecting between primary cloud providers (Codex / Antigravity) and OpenRouter drain fallback whenever a task emits an escalation signal (`EscalationTarget.EXISTING_PROVIDER_POLICY`).

### 2. Source-Backed Evidence Input & Construction Authority

#### Source Contract & V1 Scope:
```python
class LocalRoutingEvidenceProvenance(str, Enum):
    OPERATOR_EXPLICIT_MECHANICAL_COMMAND = "OPERATOR_EXPLICIT_MECHANICAL_COMMAND"
    STRUCTURED_OPENSPEC_TASK_METADATA = "STRUCTURED_OPENSPEC_TASK_METADATA"  # Deferred in V1
    DETERMINISTIC_INTAKE_METADATA = "DETERMINISTIC_INTAKE_METADATA"          # Deferred in V1

@dataclass(frozen=True)
class OperatorMechanicalCommand:
    operation_type: LocalMechanicalOperation
    mutation_mode: LocalMutationMode
    target_file: str | None
    target_symbol: str | None
    authoritative_change: dict[str, Any] | str | None
    deterministic_acceptance: dict[str, Any] | str | None
    read_sources: list[str] = Field(default_factory=list)
    requires_discovery: bool = False
    unresolved_ambiguity: bool = False
    command_id: str | None = None

# Discriminated union for routing sources
LocalRoutingEvidenceSource = OperatorMechanicalCommand
```

#### Deferred Sources in V1:
`STRUCTURED_OPENSPEC_TASK_METADATA` and `DETERMINISTIC_INTAKE_METADATA` are DEFERRED / UNSUPPORTED in V1 because current `tasks.md` prose and intake models do not carry structured mechanical operation fields. Tasks.md prose or natural language instruction text MUST NOT be parsed to fabricate mechanical evidence.

#### Derived Evidence Fields & Provenance Assignment:
When `LocalRoutingEvidenceAuthority.construct_evidence(source)` receives a valid `OperatorMechanicalCommand`:
1. `provenance` is assigned directly by the authority: `LocalRoutingEvidenceProvenance.OPERATOR_EXPLICIT_MECHANICAL_COMMAND`.
2. `authoritative_change_supplied` is DERIVED: `source.authoritative_change is not None`.
3. `deterministic_acceptance_supplied` is DERIVED: `source.deterministic_acceptance is not None`.
4. Callers cannot pass or overwrite `provenance`, `authoritative_change_supplied`, or `deterministic_acceptance_supplied`.

#### Read-Only `LOG_ANALYSIS` Read-Source Contract:
For `mutation_mode == LocalMutationMode.READ_ONLY`:
- `read_sources` MUST be an explicit, bounded list of canonical file paths (`len(source.read_sources) > 0`).
- Unbounded read scopes (wildcards like `*` or directory traversal) -> authority failure -> `ESCALATE_PROVIDER_POLICY`.
- Paths containing secrets, `.env`, credentials, or auth/security keywords in `read_sources` -> authority failure -> `ESCALATE_PROVIDER_POLICY`.

### 3. Operational Verdict Model (`LocalRoutingVerdict` & `LocalRoutingDecision`)

```python
class LocalRoutingVerdict(str, Enum):
    LOCAL_ELIGIBLE = "LOCAL_ELIGIBLE"
    ESCALATE_PROVIDER_POLICY = "ESCALATE_PROVIDER_POLICY"

@dataclass(frozen=True)
class LocalEvidenceAuthorityResult:
    success: bool
    evidence: LocalRoutingEvidence | None
    reason: str

@dataclass(frozen=True)
class LocalRoutingDecision:
    verdict: LocalRoutingVerdict  # LOCAL_ELIGIBLE or ESCALATE_PROVIDER_POLICY
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

### 4. Deterministic Policy Rules & Gate Precedence

To achieve `LOCAL_ELIGIBLE` status, a task envelope MUST pass ALL of the following gates sequentially:

1. **Snapshot Gate:** A `PRE_EXECUTION` `TaskClassificationSnapshot` MUST exist. Missing snapshot -> `CLASSIFICATION_UNKNOWN` -> `ESCALATE_PROVIDER_POLICY`.
2. **Direct Completeness & Stage Gate:**
   - Canonical `classify_pre_execution()` initializes `classification_completeness` to `ClassificationCompleteness.PARTIAL` and never produces `COMPLETE`.
   - `PRE_EXECUTION` stage is accepted with `completeness == ClassificationCompleteness.PARTIAL` **ONLY** when `snapshot.missing_signals == []` (direct field check).
   - Any snapshot with `completeness == ClassificationCompleteness.MINIMAL` or `snapshot.missing_signals != []` MUST escalate -> `CLASSIFICATION_INCOMPLETE` -> `ESCALATE_PROVIDER_POLICY`.
3. **Complexity Gate:** `complexity` MUST equal `TaskComplexity.LOW`. `MEDIUM`, `HIGH`, or `UNKNOWN` -> `COMPLEXITY_NOT_LOW` -> `ESCALATE_PROVIDER_POLICY`.
4. **Zero-Tolerance Sensitive Risk Gate (String Risk Values):**
   - In `snapshot.risk_profile` (`TaskRiskProfile`), sensitive dimensions (`architectural_impact`, `persistence_impact`, `security_auth_impact`, `production_runtime`, `provider_orchestration`, `destructive_operations`, `deployment_config`) MUST equal string `"NONE"`.
   - `code_change_breadth` MAY be `"NONE"` or `"LOW"`.
   - Any non-`"NONE"` value in sensitive dimensions -> `HIGH_RISK_SURFACE` -> `ESCALATE_PROVIDER_POLICY`.
   - `destructive_operations == "PRESENT"` -> `HIGH_RISK_SURFACE` -> `ESCALATE_PROVIDER_POLICY`.
5. **Surface Gate:** `surface_kind` MUST be an allowed surface (`DOCS_ONLY`, `TESTS_ONLY`, `BACKEND_SERVICE`, `UI_FRONTEND`). `MIGRATION_SCHEMA`, `CONFIG_ONLY`, `INFRASTRUCTURE_DEPLOYMENT`, `ORCHESTRATION_LIFECYCLE`, `SECURITY_AUTH`, `MIXED`, or `UNKNOWN` -> `FORBIDDEN_SURFACE` -> `ESCALATE_PROVIDER_POLICY`.
6. **Task Class Gate:** `task_class` MUST be an allowed local task class (`SMALL_CODE_FIX`, `TEST_AUTHORING`, `LOG_ANALYSIS`, `SMALL_REFACTOR`, `API_SMALL_CHANGE`, `UI_SMALL_POLISH`). Unlisted class -> `TASK_CLASS_NOT_LOCAL` -> `ESCALATE_PROVIDER_POLICY`.
7. **Trusted Explicitness Gate:** `LocalRoutingEvidence` MUST be present, constructed by authority (`provenance == LocalRoutingEvidenceProvenance.OPERATOR_EXPLICIT_MECHANICAL_COMMAND`), and valid:
   - `requires_discovery == True` or `unresolved_ambiguity == True` -> `TASK_NOT_MECHANICALLY_EXPLICIT` -> `ESCALATE_PROVIDER_POLICY`.
   - `authoritative_change_supplied == False` (for mutating tasks) -> `TASK_NOT_MECHANICALLY_EXPLICIT` -> `ESCALATE_PROVIDER_POLICY`.
   - `deterministic_acceptance_supplied == False` -> `TASK_NOT_MECHANICALLY_EXPLICIT` -> `ESCALATE_PROVIDER_POLICY`.
8. **Explicit File Boundary Gate:**
   - For mutating tasks (`mutation_mode == LocalMutationMode.MUTATING`): `allowed_files` MUST be present, contain exactly 1 target file (`len(allowed_files) == 1`), and match `routing_evidence.target_file`. Absent, empty, or multi-file allowlist -> `MISSING_ALLOWED_FILE_BOUNDARY` / `SCOPE_TOO_BROAD` / `MULTI_MODULE_SCOPE` -> `ESCALATE_PROVIDER_POLICY`.
   - For non-mutating tasks (`mutation_mode == LocalMutationMode.READ_ONLY`): Code edit file allowlist is not required, but `read_sources` MUST be explicit (`len(read_sources) > 0`) with zero secrets/auth paths.
9. **Model Capability Gate:** Canonical model identity MUST be `qwen2.5-coder:7b-instruct-q4_K_M`. Qwen 14B or unknown models -> `LOCAL_MODEL_NOT_CAPABLE_FOR_TASK` -> `ESCALATE_PROVIDER_POLICY`.

### 5. Integration Point in Execution Pipeline & Service API Contract

Integrate `LocalRoutingEvidenceAuthority` and `LocalWorkerCapabilityRouter` inside `LocalWorkerService.run()` prior to `preflight`, context packaging, or model dispatch:

```python
# Service API signature:
async def run(
    self,
    task: LocalTaskEnvelope,
    *,
    validator: Validator,
    routing_source: LocalRoutingEvidenceSource | None = None,
    classification_snapshot: TaskClassificationSnapshot | None = None,
    client: httpx.AsyncClient | None = None,
    preflight: PreflightResult | None = None,
    worktree_path: Any | None = None,
    uow: Any | None = None,
    project_id: str = "mini-me",
    job_id: str | None = None,
):
    # 1. Evaluate authority construction
    authority_result = LocalRoutingEvidenceAuthority.construct_evidence(routing_source)
    if not authority_result.success or authority_result.evidence is None:
        return ServiceOutcome(
            eligibility=_refusal_from_authority(authority_result),
            preflight=PreflightResult(
                provider=OLLAMA_PROVIDER,
                model=self.model,
                status=PreflightStatus.NOT_QUALIFIED,
                reason=authority_result.reason,
            ),
            evidence=_authority_refusal_evidence(authority_result),
        )

    # 2. Evaluate capability router
    routing_decision = self.capability_router.evaluate_capability_routing(
        task=task,
        snapshot=classification_snapshot,
        evidence=authority_result.evidence,
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

    # 3. Proceed to Ollama preflight & Harness execution
    ...
```

Refusal produces `PreflightStatus.NOT_QUALIFIED`, sets `escalation.required = True` and `escalation.target = EscalationTarget.EXISTING_PROVIDER_POLICY`, and immediately returns with zero Ollama API calls and zero token consumption. Caller consumes the escalation signal per existing provider orchestration authority (automatic provider selection remains OUT OF SCOPE).

### 6. Defense-in-Depth Safety & Implement-Only Authority
Admittance by capability routing (`LOCAL_ELIGIBLE`) does NOT bypass existing local worker execution safety:
- `ManagedWorkspaceGuard`: Role must be `WorkspaceRole.EXECUTION_WORKTREE`.
- `WorktreeManager`: Validates durable worktree ownership and valid on-disk ownership marker.
- `LocalPatchApplier`: Validates patch policy (`validate_patch_policy`) ensuring generated patches touch ONLY `allowed_files`. If a model patch touches any file outside `allowed_files`, patch policy fails closed, zero unauthorized filesystem mutation occurs, and escalation evidence is produced.
- Local Authority: Remains strictly `implement` (zero review, audit, merge, or approve authority).

### 7. Stable Reason Codes
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
- `MISSING_ROUTING_SOURCE`
- `UNSUPPORTED_EVIDENCE_SOURCE`
- `AUTHORITY_CONSTRUCTION_FAILED`
