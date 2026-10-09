# local-worker-capability-routing-policy Specification

## Purpose

Deterministic pre-inference capability routing policy for the mini me local worker (`minime.local_worker`). Evaluates structural classification snapshots, multi-dimensional risk profiles, surface bounds, allowed file boundaries, and mechanical explicitness evidence to decide whether a work unit is eligible for local Qwen 7B execution or must escalate directly to existing cloud provider policies.

## ADDED Requirements

### Requirement: Deterministic Local Capability Routing Decision Engine
The system SHALL evaluate work units against a deterministic capability routing policy prior to model preflight, context packaging, or inference dispatch. The decision SHALL evaluate to `LOCAL_ELIGIBLE`, `ESCALATE_PROVIDER_POLICY`, or `INSUFFICIENT_EVIDENCE` (which fails closed to `ESCALATE_PROVIDER_POLICY`).

#### Scenario 1: LOW complexity, COMPLETE snapshot, and one-file explicit edit evaluates to LOCAL_ELIGIBLE
- **GIVEN** a `PRE_EXECUTION` classification snapshot with `complexity=TaskComplexity.LOW`, `completeness=ClassificationCompleteness.COMPLETE`, all risk dimensions `NONE`, and surface kind `BACKEND_SERVICE`
- **AND** a task envelope with `allowed_files=["src/minime/utils.py"]` and an explicit mechanical transformation instruction with context-supplied contract values
- **WHEN** the capability router evaluates the task envelope and snapshot
- **THEN** the routing decision verdict SHALL be `LOCAL_ELIGIBLE`
- **AND** `reason_code` SHALL be `LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY`
- **AND** `selected_local_model` SHALL be `qwen2.5-coder:7b-instruct-q4_K_M`

#### Scenario 2: LOW surface but debugging or reasoning required evaluates to ESCALATE
- **GIVEN** a `PRE_EXECUTION` classification snapshot with `complexity=TaskComplexity.LOW` and surface `BACKEND_SERVICE`
- **AND** a task instruction requiring root-cause investigation or debugging ("Diagnose and fix why admission fails intermittently")
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `TASK_NOT_MECHANICALLY_EXPLICIT`
- **AND** `escalation_target` SHALL be `EXISTING_PROVIDER_POLICY`

#### Scenario 3: TEST_AUTHORING with unknown failing-test cause evaluates to ESCALATE
- **GIVEN** a task with `task_class=TEST_AUTHORING` and `allowed_files=["tests/test_intake.py"]`
- **AND** a task instruction stating "Fix failing test test_intake_admission without changing source" but lacking explicit fixture/contract changes
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `TASK_NOT_MECHANICALLY_EXPLICIT`

#### Scenario 4: TEST_AUTHORING with authoritative exact fixture transformation evaluates to LOCAL_ELIGIBLE
- **GIVEN** a task with `task_class=TEST_AUTHORING` and `allowed_files=["tests/test_fixture.py"]`
- **AND** a `PRE_EXECUTION` snapshot with `complexity=TaskComplexity.LOW`, completeness `ClassificationCompleteness.COMPLETE`, and all risk dimensions `NONE`
- **AND** an explicit instruction supplying the exact fixture updates and contract values
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `LOCAL_ELIGIBLE`

#### Scenario 5: MEDIUM complexity evaluates to ESCALATE
- **GIVEN** a `PRE_EXECUTION` snapshot with `complexity=TaskComplexity.MEDIUM`
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `COMPLEXITY_NOT_LOW`

#### Scenario 6: HIGH complexity evaluates to ESCALATE
- **GIVEN** a `PRE_EXECUTION` snapshot with `complexity=TaskComplexity.HIGH`
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `COMPLEXITY_NOT_LOW`

#### Scenario 7: UNKNOWN complexity evaluates to ESCALATE
- **GIVEN** a snapshot with `complexity=TaskComplexity.UNKNOWN`
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `CLASSIFICATION_UNKNOWN`

#### Scenario 8: Incomplete classification snapshot evaluates to ESCALATE
- **GIVEN** a snapshot with `classification_completeness=ClassificationCompleteness.PARTIAL` or `ClassificationCompleteness.MINIMAL`
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `CLASSIFICATION_INCOMPLETE`

#### Scenario 9: Security/auth risk evaluates to ESCALATE
- **GIVEN** a classification snapshot with `security_auth_impact=HIGH` or surface kind `SECURITY_AUTH`
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `HIGH_RISK_SURFACE`

#### Scenario 10: Migration/persistence risk evaluates to ESCALATE
- **GIVEN** a classification snapshot with `persistence_impact=HIGH` or surface kind `MIGRATION_SCHEMA`
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `HIGH_RISK_SURFACE`

#### Scenario 11: Provider/orchestration risk evaluates to ESCALATE
- **GIVEN** a classification snapshot with `provider_orchestration=HIGH` or surface kind `ORCHESTRATION_LIFECYCLE`
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `HIGH_RISK_SURFACE`

#### Scenario 12: Lifecycle change evaluates to ESCALATE
- **GIVEN** a task description or snapshot touching lifecycle state machines or transition keys
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `FORBIDDEN_SURFACE`

#### Scenario 13: Architecture change evaluates to ESCALATE
- **GIVEN** a task with `task_class=ARCHITECTURE_CHANGE` or description matching architectural redesign
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `FORBIDDEN_SURFACE`

#### Scenario 14: Multi-file/multi-module semantic edit evaluates to ESCALATE
- **GIVEN** a task envelope with `allowed_files=["src/minime/a.py", "src/minime/b.py", "src/minime/c.py"]` spanning multiple modules
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `MULTI_MODULE_SCOPE`

#### Scenario 15: No explicit allowed file boundary for mutating task evaluates to ESCALATE
- **GIVEN** a mutating task envelope (`SMALL_CODE_FIX`) with `allowed_files=None` or `allowed_files=[]`
- **WHEN** the capability router evaluates the task
- **THEN** the routing decision verdict SHALL be `ESCALATE_PROVIDER_POLICY`
- **AND** `reason_code` SHALL be `MISSING_ALLOWED_FILE_BOUNDARY`

#### Scenario 16: Local refusal produces zero Ollama inference
- **GIVEN** a task that evaluates to `ESCALATE_PROVIDER_POLICY` at capability routing evaluation
- **WHEN** `LocalWorkerService.run()` executes
- **THEN** capability routing SHALL return refusal immediately
- **AND** zero HTTP API requests SHALL be dispatched to Ollama
- **AND** zero local inference tokens SHALL be consumed

#### Scenario 17: Local refusal delegates to EXISTING_PROVIDER_POLICY
- **GIVEN** a task refused by local capability routing
- **WHEN** the service outcome is built
- **THEN** `escalation_target` SHALL equal `EscalationTarget.EXISTING_PROVIDER_POLICY`
- **AND** the orchestration layer SHALL route the work unit to existing cloud provider policies (Codex / Antigravity)

#### Scenario 18: Admitted task still passes existing LocalWorker safety gates
- **GIVEN** a task evaluated as `LOCAL_ELIGIBLE` by capability routing
- **WHEN** local execution proceeds
- **THEN** execution SHALL still enforce `ManagedWorkspaceGuard` role `EXECUTION_WORKTREE`, `WorktreeManager` ownership, forbidden surface scans, patch policy verification, and deterministic validation

#### Scenario 19: Generated patch exceeding authorized scope fails closed
- **GIVEN** a task admitted as `LOCAL_ELIGIBLE` with `allowed_files=["src/minime/utils.py"]`
- **WHEN** the local model generates a patch touching `src/minime/service.py`
- **THEN** patch policy verification SHALL fail
- **AND** the harness SHALL fail closed and escalate to `EXISTING_PROVIDER_POLICY` without mutating the filesystem

#### Scenario 20: Read-only mechanical LOG_ANALYSIS evaluated under separate safe rules
- **GIVEN** a task with `task_class=LOG_ANALYSIS` and zero filesystem mutation authority
- **WHEN** the capability router evaluates the task
- **THEN** it SHALL verify no security/auth/secret paths are present
- **AND** it SHALL evaluate eligibility without requiring a code edit allowlist boundary
- **AND** the local worker outcome SHALL remain non-authoritative diagnostic evidence

#### Scenario 21: Local model never gains reviewer/audit/merge authority
- **GIVEN** any local routing decision or execution outcome
- **WHEN** local authorities are checked
- **THEN** authority SHALL remain strictly `implement`
- **AND** review, audit, merge, and approve authorities SHALL be prohibited

#### Scenario 22: Qwen 14B is not an available routing target
- **GIVEN** local model selection during capability routing
- **WHEN** the target model is determined
- **THEN** `selected_local_model` SHALL be `qwen2.5-coder:7b-instruct-q4_K_M`
- **AND** Qwen 14B (`qwen2.5-coder:14b-instruct-q4_K_M`) SHALL NOT be selectable under any condition

#### Scenario 23: Classification subsystem remains provider agnostic
- **GIVEN** execution of `TaskComplexityRiskClassifier`
- **WHEN** snapshots are generated
- **THEN** classification SHALL derive purely from observable file paths, diffs, and OpenSpec metadata without provider, model, or routing awareness

#### Scenario 24: Routing result is deterministic for identical inputs
- **GIVEN** identical task envelope, classification snapshot, and policy version inputs
- **WHEN** capability routing evaluation is performed twice
- **THEN** both evaluations SHALL yield identical `LocalRoutingDecision` values
