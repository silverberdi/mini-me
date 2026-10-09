# local-worker-capability-routing-policy Specification

## Purpose

Deterministic pre-inference capability routing policy for the mini me local worker (`minime.local_worker`). Evaluates structural classification snapshots, zero-tolerance risk profiles, surface bounds, single-file allowlist boundaries, and trusted `LocalRoutingEvidence` constructed by `LocalRoutingEvidenceAuthority` to decide whether a work unit is eligible for local Qwen 7B execution or must emit an escalation signal to existing cloud provider policies.

## ADDED Requirements

### Requirement: Deterministic Local Capability Routing Decision Engine
The system SHALL evaluate work units against a deterministic capability routing policy prior to model preflight, context packaging, or inference dispatch. The decision SHALL evaluate to `LOCAL_ELIGIBLE`, `ESCALATE_PROVIDER_POLICY`, or `INSUFFICIENT_EVIDENCE` (which fails closed to `ESCALATE_PROVIDER_POLICY`).

#### Scenario 1: Canonical PRE_EXECUTION PARTIAL with empty missing_signals and complete evidence evaluates to LOCAL_ELIGIBLE
- **GIVEN** a `PRE_EXECUTION` classification snapshot with `complexity=TaskComplexity.LOW`, `completeness=ClassificationCompleteness.PARTIAL`, empty `missing_signals=[]`, all sensitive risk dimensions `"NONE"`, and surface kind `BACKEND_SERVICE`
- **AND** a trusted `LocalRoutingEvidence` with `provenance=LocalRoutingEvidenceProvenance.STRUCTURED_OPENSPEC_TASK_METADATA`, `operation_type=LocalMechanicalOperation.TEXT_REPLACEMENT`, `mutation_mode=LocalMutationMode.MUTATING`, `target_file="src/minime/utils.py"`, `authoritative_change_supplied=True`, `deterministic_acceptance_supplied=True`, `requires_discovery=False`, and `unresolved_ambiguity=False`
- **AND** a task envelope with `allowed_files=["src/minime/utils.py"]`
- **WHEN** the capability router evaluates the task envelope, snapshot, and routing evidence
- **THEN** the routing decision verdict SHALL be `LOCAL_ELIGIBLE`
- **AND** `reason_code` SHALL be `LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY`
- **AND** `selected_local_model` SHALL be `qwen2.5-coder:7b-instruct-q4_K_M`
- **AND** the router SHALL evaluate `snapshot.missing_signals` directly as `[]`

#### Scenario 2: PRE_EXECUTION PARTIAL with snapshot.missing_signals=["no proposal text"] evaluates to ESCALATE
- **GIVEN** a `PRE_EXECUTION` classification snapshot with `completeness=ClassificationCompleteness.PARTIAL` and `missing_signals=["no proposal text"]`
- **WHEN** the capability router evaluates the snapshot
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `CLASSIFICATION_INCOMPLETE`
- **AND** the router SHALL read `snapshot.missing_signals` directly

#### Scenario 3: MINIMAL completeness evaluates to ESCALATE
- **GIVEN** a classification snapshot with `classification_completeness=ClassificationCompleteness.MINIMAL`
- **WHEN** the capability router evaluates the snapshot
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `CLASSIFICATION_INCOMPLETE`

#### Scenario 4: Missing or untrusted LocalRoutingEvidence evaluates to ESCALATE with zero Ollama calls
- **GIVEN** a task where `routing_evidence` is `None` or has `provenance=LocalRoutingEvidenceProvenance.UNTRUSTED_CALLER_PROSE`
- **WHEN** `LocalWorkerService.run()` evaluates capability routing
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `TASK_NOT_MECHANICALLY_EXPLICIT`
- **AND** zero HTTP requests SHALL be dispatched to Ollama

#### Scenario 5: requires_discovery=True evaluates to ESCALATE
- **GIVEN** a trusted `LocalRoutingEvidence` with `requires_discovery=True`
- **WHEN** the capability router evaluates the evidence
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `TASK_NOT_MECHANICALLY_EXPLICIT`
- **AND** `escalation_target` SHALL be `EscalationTarget.EXISTING_PROVIDER_POLICY`

#### Scenario 6: unresolved_ambiguity=True evaluates to ESCALATE
- **GIVEN** a trusted `LocalRoutingEvidence` with `unresolved_ambiguity=True`
- **WHEN** the capability router evaluates the evidence
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `TASK_NOT_MECHANICALLY_EXPLICIT`

#### Scenario 7: authoritative_change_supplied=False for mutating operation evaluates to ESCALATE
- **GIVEN** a trusted `LocalRoutingEvidence` with `mutation_mode=LocalMutationMode.MUTATING` and `authoritative_change_supplied=False`
- **WHEN** the capability router evaluates the evidence
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `TASK_NOT_MECHANICALLY_EXPLICIT`

#### Scenario 8: deterministic_acceptance_supplied=False evaluates to ESCALATE
- **GIVEN** a trusted `LocalRoutingEvidence` with `deterministic_acceptance_supplied=False`
- **WHEN** the capability router evaluates the evidence
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `TASK_NOT_MECHANICALLY_EXPLICIT`

#### Scenario 9: security_auth_impact="LOW" evaluates to ESCALATE
- **GIVEN** a classification snapshot with `security_auth_impact="LOW"`
- **WHEN** the capability router evaluates the risk profile
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `HIGH_RISK_SURFACE`

#### Scenario 10: provider_orchestration="LOW" evaluates to ESCALATE
- **GIVEN** a classification snapshot with `provider_orchestration="LOW"`
- **WHEN** the capability router evaluates the risk profile
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `HIGH_RISK_SURFACE`

#### Scenario 11: persistence_impact="LOW" evaluates to ESCALATE
- **GIVEN** a classification snapshot with `persistence_impact="LOW"`
- **WHEN** the capability router evaluates the risk profile
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `HIGH_RISK_SURFACE`

#### Scenario 12: deployment_config="LOW" evaluates to ESCALATE
- **GIVEN** a classification snapshot with `deployment_config="LOW"`
- **WHEN** the capability router evaluates the risk profile
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `HIGH_RISK_SURFACE`

#### Scenario 13: architectural_impact="LOW" evaluates to ESCALATE
- **GIVEN** a classification snapshot with `architectural_impact="LOW"`
- **WHEN** the capability router evaluates the risk profile
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `HIGH_RISK_SURFACE`

#### Scenario 14: code_change_breadth="LOW" alone does not prohibit safe local work
- **GIVEN** a classification snapshot with `code_change_breadth="LOW"` and all other sensitive risk dimensions `"NONE"`
- **AND** a valid, explicit single-file mutating `LocalRoutingEvidence` with trusted provenance
- **WHEN** the capability router evaluates the risk profile
- **THEN** `code_change_breadth="LOW"` SHALL NOT cause risk gate refusal
- **AND** routing MAY evaluate to `LOCAL_ELIGIBLE` if all other gates pass

#### Scenario 15: Refusal uses canonical PreflightStatus.NOT_QUALIFIED
- **GIVEN** a task refused by capability routing
- **WHEN** `LocalWorkerService.run()` constructs the refusal outcome
- **THEN** `preflight.status` SHALL equal `PreflightStatus.NOT_QUALIFIED`
- **AND** `preflight.reason` SHALL contain the routing refusal summary

#### Scenario 16: Refusal emits EXISTING_PROVIDER_POLICY signal without claiming cloud selection
- **GIVEN** a task refused by capability routing
- **WHEN** the service outcome evidence is created
- **THEN** `escalation.required` SHALL be `True`
- **AND** `escalation.target` SHALL equal `EscalationTarget.EXISTING_PROVIDER_POLICY`
- **AND** zero Ollama calls SHALL occur
- **AND** provider selection itself SHALL remain strictly out of scope for the local capability router

#### Scenario 17: No eligibility decision depends on natural-language keyword parsing
- **GIVEN** any task instruction or task description string
- **WHEN** capability routing is evaluated
- **THEN** the decision SHALL be derived strictly from typed enum values, boolean evidence flags, and structured allowlist arrays
- **AND** no natural-language keyword matching or prompt parsing SHALL be performed by the capability router

#### Scenario 18: Admitted LOCAL_ELIGIBLE task does not bypass existing local worker safety
- **GIVEN** a task evaluated as `LOCAL_ELIGIBLE` by capability routing
- **WHEN** `LocalWorkerService.run()` executes
- **THEN** existing SDLC safety gates SHALL remain mandatory: `ManagedWorkspaceGuard` workspace role `EXECUTION_WORKTREE`, `WorktreeManager` durable ownership, ownership marker verification, patch policy, and deterministic validator

#### Scenario 19: Generated patch exceeding authorized single-file scope fails closed
- **GIVEN** a task admitted as `LOCAL_ELIGIBLE` with `allowed_files=["src/minime/utils.py"]`
- **WHEN** the local model generates a patch touching `src/minime/service.py`
- **THEN** patch policy verification SHALL fail
- **AND** no unauthorized filesystem mutation SHALL occur
- **AND** escalation evidence SHALL be produced

#### Scenario 20: Local authority remains strictly implement-only
- **GIVEN** any local routing decision or execution outcome
- **WHEN** local worker authorities are checked
- **THEN** authority SHALL remain strictly `implement`
- **AND** routing eligibility SHALL NOT grant review, audit, merge, approve, or lifecycle authority

#### Scenario 21: Routing result is deterministic for identical inputs
- **GIVEN** identical classification snapshot, trusted `LocalRoutingEvidence`, task envelope, model identity, and policy version
- **WHEN** capability routing evaluation is performed twice
- **THEN** both evaluations SHALL yield identical `LocalRoutingDecision` values

#### Scenario 22: Qwen 14B is not an available routing target
- **GIVEN** local model selection during capability routing
- **WHEN** target model identity is determined
- **THEN** `selected_local_model` SHALL be `qwen2.5-coder:7b-instruct-q4_K_M`
- **AND** Qwen 14B (`qwen2.5-coder:14b-instruct-q4_K_M`) SHALL NOT be selectable under any condition

#### Scenario 23: Classification subsystem remains provider agnostic
- **GIVEN** execution of `TaskComplexityRiskClassifier`
- **WHEN** snapshots are generated
- **THEN** classification SHALL derive purely from observable file paths, diffs, and OpenSpec metadata without provider, model, or routing awareness

#### Scenario 24: Read-only mechanical LOG_ANALYSIS evaluated under separate safe rules
- **GIVEN** a task with `task_class=LOG_ANALYSIS` and `routing_evidence.mutation_mode=LocalMutationMode.READ_ONLY`
- **WHEN** the capability router evaluates the task
- **THEN** it SHALL verify zero security/auth/secret paths are present
- **AND** it SHALL NOT require a code edit file allowlist boundary
- **AND** local execution output SHALL remain non-authoritative diagnostic evidence
