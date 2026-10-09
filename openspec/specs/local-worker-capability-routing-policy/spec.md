# local-worker-capability-routing-policy Specification

## Purpose

Deterministic pre-inference capability routing policy for the mini me local worker (`minime.local_worker`). Evaluates structural classification snapshots, zero-tolerance risk profiles, surface bounds, single-file allowlist boundaries, and source-backed `LocalRoutingEvidence` constructed by `LocalRoutingEvidenceAuthority` to decide whether a work unit is eligible for local Qwen 7B execution or must emit an escalation signal to existing cloud provider policies.

## Requirements

### Requirement: Source-Backed Evidence Construction & Capability Routing Engine
The system SHALL require all local capability routing evidence to be constructed exclusively by `LocalRoutingEvidenceAuthority` from a valid `LocalRoutingEvidenceSource`. Callers SHALL NOT set provenance or fabricate evidence booleans directly. The router SHALL evaluate evidence against a deterministic policy prior to model preflight, context packaging, or inference dispatch, producing either `LOCAL_ELIGIBLE` or `ESCALATE_PROVIDER_POLICY`.

#### Scenario 1: Caller cannot directly manufacture trusted LocalRoutingEvidence
- **GIVEN** a caller attempts to instantiate `LocalRoutingEvidence` directly with `provenance=LocalRoutingEvidenceProvenance.OPERATOR_EXPLICIT_MECHANICAL_COMMAND` without passing through `LocalRoutingEvidenceAuthority`
- **WHEN** `LocalWorkerService.run()` evaluates capability routing
- **THEN** authority verification SHALL fail
- **AND** the routing verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `UNSUPPORTED_EVIDENCE_SOURCE`
- **AND** zero HTTP requests SHALL be dispatched to Ollama

#### Scenario 2: Provenance is assigned by LocalRoutingEvidenceAuthority from actual source type
- **GIVEN** a valid `OperatorMechanicalCommand` input source passed to `LocalRoutingEvidenceAuthority`
- **WHEN** authority construction executes
- **THEN** `LocalRoutingEvidenceAuthority` SHALL assign `provenance=LocalRoutingEvidenceProvenance.OPERATOR_EXPLICIT_MECHANICAL_COMMAND`
- **AND** `authoritative_change_supplied` SHALL be DERIVED as `True` when `source.authoritative_change` is not None
- **AND** `deterministic_acceptance_supplied` SHALL be DERIVED as `True` when `source.deterministic_acceptance` is not None

#### Scenario 3: Unsupported or deferred source fails closed before Ollama
- **GIVEN** a source type marked DEFERRED/UNSUPPORTED in V1 (e.g. `STRUCTURED_OPENSPEC_TASK_METADATA` or `DETERMINISTIC_INTAKE_METADATA`)
- **WHEN** `LocalRoutingEvidenceAuthority.construct_evidence()` evaluates the source
- **THEN** authority construction SHALL fail
- **AND** `LocalWorkerService.run()` SHALL return `PreflightStatus.NOT_QUALIFIED`
- **AND** `reason_code` SHALL be `UNSUPPORTED_EVIDENCE_SOURCE`
- **AND** zero HTTP requests SHALL be dispatched to Ollama

#### Scenario 4: Missing source fails closed before Ollama
- **GIVEN** `routing_source` is `None`
- **WHEN** `LocalWorkerService.run()` executes
- **THEN** authority construction SHALL fail
- **AND** the routing verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `MISSING_ROUTING_SOURCE`
- **AND** zero HTTP requests SHALL be dispatched to Ollama

#### Scenario 5: V1 OperatorMechanicalCommand with authoritative payload constructs trusted evidence
- **GIVEN** an `OperatorMechanicalCommand` with `operation_type=LocalMechanicalOperation.TEXT_REPLACEMENT`, `mutation_mode=LocalMutationMode.MUTATING`, `target_file="src/minime/utils.py"`, structured `authoritative_change={"replacement": "..."}`, and structured `deterministic_acceptance={"test_target": "tests/test_utils.py"}`
- **AND** a `PRE_EXECUTION` snapshot with `complexity=TaskComplexity.LOW`, `completeness=ClassificationCompleteness.PARTIAL`, empty `snapshot.missing_signals=[]`, and all sensitive risk dimensions `"NONE"`
- **AND** a task envelope with `allowed_files=["src/minime/utils.py"]`
- **WHEN** capability routing is evaluated
- **THEN** authority construction SHALL succeed
- **AND** the routing verdict SHALL be `LOCAL_ELIGIBLE`
- **AND** `reason_code` SHALL be `LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY`
- **AND** `selected_local_model` SHALL be `qwen2.5-coder:7b-instruct-q4_K_M`

#### Scenario 6: Missing authoritative_change payload causes authority construction failure
- **GIVEN** an `OperatorMechanicalCommand` where `authoritative_change` is `None`
- **WHEN** `LocalRoutingEvidenceAuthority.construct_evidence()` executes
- **THEN** authority construction SHALL fail
- **AND** `authoritative_change_supplied` SHALL evaluate to `False`
- **AND** the routing verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `AUTHORITY_CONSTRUCTION_FAILED`

#### Scenario 7: Missing deterministic_acceptance payload causes authority construction failure
- **GIVEN** an `OperatorMechanicalCommand` where `deterministic_acceptance` is `None`
- **WHEN** `LocalRoutingEvidenceAuthority.construct_evidence()` executes
- **THEN** authority construction SHALL fail
- **AND** `deterministic_acceptance_supplied` SHALL evaluate to `False`
- **AND** the routing verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `AUTHORITY_CONSTRUCTION_FAILED`

#### Scenario 8: tasks.md prose alone cannot create trusted mechanical routing evidence
- **GIVEN** a task where `routing_source` is omitted but `task.instruction` or `tasks.md` contains text describing a mechanical edit
- **WHEN** `LocalWorkerService.run()` evaluates capability routing
- **THEN** the router SHALL NOT parse the natural language text
- **AND** authority construction SHALL fail
- **AND** the routing verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `MISSING_ROUTING_SOURCE`

#### Scenario 9: Generic intake description strings alone cannot fabricate a mechanical operation
- **GIVEN** a job created from backlog intake metadata with free-form description text but no structured `OperatorMechanicalCommand`
- **WHEN** capability routing is evaluated
- **THEN** the intake metadata SHALL NOT be accepted as a V1 mechanical source
- **AND** authority construction SHALL fail
- **AND** the routing verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `UNSUPPORTED_EVIDENCE_SOURCE`

#### Scenario 10: READ_ONLY LOG_ANALYSIS requires explicit bounded read_sources
- **GIVEN** an `OperatorMechanicalCommand` with `mutation_mode=LocalMutationMode.READ_ONLY` and `operation_type=LocalMechanicalOperation.LOG_DIAGNOSTIC`
- **AND** explicit bounded `read_sources=["/var/log/minime/api.log"]`
- **WHEN** `LocalRoutingEvidenceAuthority.construct_evidence()` executes
- **THEN** authority construction SHALL succeed
- **AND** the local worker MAY evaluate eligibility under read-only rules without requiring code edit file allowlist boundaries
- **AND** execution output SHALL remain non-authoritative diagnostic evidence

#### Scenario 11: Secret, auth, or security path in read_sources escalates
- **GIVEN** a read-only `OperatorMechanicalCommand` with `read_sources=["config/secrets.env"]` or `read_sources=["/etc/minime/pki/key.pem"]`
- **WHEN** `LocalRoutingEvidenceAuthority.construct_evidence()` evaluates `read_sources`
- **THEN** authority construction SHALL fail
- **AND** the routing verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `FORBIDDEN_SURFACE`

#### Scenario 12: Unbounded read_sources escalates
- **GIVEN** a read-only `OperatorMechanicalCommand` with `read_sources=["*"]` or empty `read_sources=[]`
- **WHEN** `LocalRoutingEvidenceAuthority.construct_evidence()` evaluates `read_sources`
- **THEN** authority construction SHALL fail
- **AND** the routing verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `AUTHORITY_CONSTRUCTION_FAILED`

#### Scenario 13: LocalWorkerService obtains evidence through authority before router evaluation
- **GIVEN** a execution request sent to `LocalWorkerService.run()`
- **WHEN** service execution begins
- **THEN** `LocalWorkerService` SHALL pass `routing_source` to `LocalRoutingEvidenceAuthority.construct_evidence()` FIRST
- **AND** `LocalWorkerCapabilityRouter.evaluate_capability_routing()` SHALL receive only evidence verified by that authority
- **AND** if authority construction fails, capability router evaluation SHALL be skipped and refusal returned immediately

#### Scenario 14: Identical typed source + snapshot + envelope produces deterministic identical routing
- **GIVEN** identical `LocalRoutingEvidenceSource`, `TaskClassificationSnapshot`, `LocalTaskEnvelope`, model identity, and policy version
- **WHEN** capability routing is evaluated twice
- **THEN** both evaluations SHALL yield identical `LocalRoutingDecision` values

#### Scenario 15: PRE_EXECUTION PARTIAL with empty missing_signals evaluates to LOCAL_ELIGIBLE
- **GIVEN** a `PRE_EXECUTION` classification snapshot with `complexity=TaskComplexity.LOW`, `completeness=ClassificationCompleteness.PARTIAL`, empty `snapshot.missing_signals=[]`, all sensitive risk dimensions `"NONE"`, and surface kind `BACKEND_SERVICE`
- **AND** a valid, trusted `LocalRoutingEvidence` constructed by `LocalRoutingEvidenceAuthority`
- **WHEN** the capability router evaluates the snapshot and evidence
- **THEN** the routing decision verdict SHALL be `LOCAL_ELIGIBLE`
- **AND** the router SHALL read `snapshot.missing_signals` directly as `[]`

#### Scenario 16: PRE_EXECUTION PARTIAL with snapshot.missing_signals=["no proposal text"] evaluates to ESCALATE
- **GIVEN** a `PRE_EXECUTION` classification snapshot with `completeness=ClassificationCompleteness.PARTIAL` and `missing_signals=["no proposal text"]`
- **WHEN** the capability router evaluates the snapshot
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `CLASSIFICATION_INCOMPLETE`
- **AND** the router SHALL read `snapshot.missing_signals` directly

#### Scenario 17: MINIMAL completeness evaluates to ESCALATE
- **GIVEN** a classification snapshot with `classification_completeness=ClassificationCompleteness.MINIMAL`
- **WHEN** the capability router evaluates the snapshot
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `CLASSIFICATION_INCOMPLETE`

#### Scenario 18: Sensitive risk dimension equals LOW evaluates to ESCALATE
- **GIVEN** a classification snapshot with `security_auth_impact="LOW"`, `persistence_impact="LOW"`, `provider_orchestration="LOW"`, `deployment_config="LOW"`, or `architectural_impact="LOW"`
- **WHEN** the capability router evaluates the risk profile
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `HIGH_RISK_SURFACE`

#### Scenario 19: Refusal uses canonical PreflightStatus.NOT_QUALIFIED
- **GIVEN** a task refused by capability routing or authority construction
- **WHEN** `LocalWorkerService.run()` constructs the refusal outcome
- **THEN** `preflight.status` SHALL equal `PreflightStatus.NOT_QUALIFIED`
- **AND** `preflight.reason` SHALL contain the refusal summary

#### Scenario 20: Refusal emits EXISTING_PROVIDER_POLICY signal without claiming cloud selection
- **GIVEN** a task refused by capability routing or authority construction
- **WHEN** the service outcome evidence is created
- **THEN** `escalation.required` SHALL be `True`
- **AND** `escalation.target` SHALL equal `EscalationTarget.EXISTING_PROVIDER_POLICY`
- **AND** zero Ollama calls SHALL occur
- **AND** provider selection itself SHALL remain strictly out of scope for the local capability router

#### Scenario 21: Admitted LOCAL_ELIGIBLE task does not bypass existing local worker safety
- **GIVEN** a task evaluated as `LOCAL_ELIGIBLE` by capability routing
- **WHEN** `LocalWorkerService.run()` executes
- **THEN** existing SDLC safety gates SHALL remain mandatory: `ManagedWorkspaceGuard` workspace role `EXECUTION_WORKTREE`, `WorktreeManager` durable ownership, ownership marker verification, patch policy, and deterministic validator

#### Scenario 22: Generated patch exceeding authorized single-file scope fails closed
- **GIVEN** a task admitted as `LOCAL_ELIGIBLE` with `allowed_files=["src/minime/utils.py"]`
- **WHEN** the local model generates a patch touching `src/minime/service.py`
- **THEN** patch policy verification SHALL fail
- **AND** no unauthorized filesystem mutation SHALL occur
- **AND** escalation evidence SHALL be produced

#### Scenario 23: Local authority remains strictly implement-only
- **GIVEN** any local routing decision or execution outcome
- **WHEN** local worker authorities are checked
- **THEN** authority SHALL remain strictly `implement`
- **AND** routing eligibility SHALL NOT grant review, audit, merge, approve, or lifecycle authority

#### Scenario 24: Qwen 14B is not an available routing target
- **GIVEN** local model selection during capability routing
- **WHEN** target model identity is determined
- **THEN** `selected_local_model` SHALL be `qwen2.5-coder:7b-instruct-q4_K_M`
- **AND** Qwen 14B (`qwen2.5-coder:14b-instruct-q4_K_M`) SHALL NOT be selectable under any condition
