# Spec: Durable Intake and Closure Sagas

## ADDED Requirements

### Requirement: Durable Intake Saga Persistence and Phase Checkpointing

The system SHALL manage all work intake operations (backlog creation, OpenSpec change generation, GitHub Issue binding, GitHub Project item binding, and Definition of Ready evaluation) through a PostgreSQL-persisted, phase-checkpointed `DurableSagaModel` (`saga_type = INTAKE`), and phase transitions SHALL occur strictly upon positive durable evidence.

#### Scenario: Intake saga persists initial state before external actions
GIVEN a new work item creation or intake preparation request for a project
WHEN IntakeService initializes intake preparation
THEN the system SHALL create and commit a `DurableSagaModel` record in PostgreSQL with `saga_type = "INTAKE"`, `status = "IN_PROGRESS"`, and `current_phase = "INTAKE_CREATED"`
AND NO external side effect SHALL be executed prior to durable saga record commit.

#### Scenario: Process crash during intake preparation resumes from last completed phase
GIVEN an active intake saga in phase `OPENSPEC_AUTHORED` when the daemon process crashes
WHEN the daemon restarts and recovers the intake saga
THEN the saga engine SHALL resume execution at phase `OPENSPEC_AUTHORED`
AND SHALL NOT re-generate or overwrite completed OpenSpec artifacts unless evidence is missing.

#### Scenario: Intake saga completes cleanly at scheduler admission handoff boundary
GIVEN an intake saga executing for a backlog item
WHEN OpenSpec generation, GitHub Issue binding, GitHub Project item binding, and Definition of Ready evaluation succeed
THEN the saga engine SHALL update `BacklogItem.status` to `READY` via `LifecycleTransitionAuthority`
AND SHALL transition the intake saga status to `COMPLETED`
AND the backlog item SHALL be eligible for scheduler admission.

---

### Requirement: Durable Closure Saga Persistence and Phase Checkpointing

The system SHALL execute post-human-merge closure and cleanup operations through a PostgreSQL-persisted, phase-checkpointed `DurableSagaModel` (`saga_type = CLOSURE`), and terminal `Change.DONE` and `BacklogItem.COMPLETED` transitions SHALL be DENIED until ALL required closure phases are durably proven complete.

#### Scenario: Post-merge reconciliation creates durable closure saga
GIVEN a merged pull request observed for a change and run
WHEN PostMergeReconciliationService begins post-merge closure
THEN it SHALL create and commit a `DurableSagaModel` record in PostgreSQL with `saga_type = "CLOSURE"`, `status = "IN_PROGRESS"`, and `current_phase = "MERGE_OBSERVED"`
AND SHALL record PR merge observation evidence in the saga record.

#### Scenario: Process crash during closure resumes at exact persisted checkpoint
GIVEN a closure saga that completed `SPEC_SYNCED` and `SYNC_VERIFIED` phases before daemon crash
WHEN the daemon restarts and reconciles active sagas
THEN the closure saga SHALL resume at phase `SPEC_ARCHIVED`
AND SHALL NOT re-sync main specs or re-verify already completed sync phases.

#### Scenario: Missing phase evidence blocks terminal Change and BacklogItem closure
GIVEN a closure saga executing post-merge closure
WHEN OpenSpec spec sync, archive verification, worktree cleanup, or branch cleanup fails or is incomplete
THEN the saga engine SHALL transition saga status to `BLOCKED` with canonical outcome `WAIT_EXTERNAL` or `NEEDS_HUMAN`
AND SHALL NOT transition `Change` to `DONE` or `BacklogItem` to `COMPLETED`.

---

### Requirement: Pre-Execution Action Reservation and Idempotent Action Identity

Every non-idempotent or externally observable side effect (GitHub Issue creation, GitHub Project item addition, OpenSpec file authoring, GitHub Issue closure, GitHub Project item status update, OpenSpec spec sync, OpenSpec change archiving, worktree cleanup, branch deletion, lock release) SHALL reserve a `SagaActionModel` record in PostgreSQL with `execution_state = REQUESTED` and a deterministic `request_fingerprint` BEFORE invoking external adapters.

#### Scenario: Action reservation committed before remote mutation
GIVEN an intake or closure saga preparing an external action (such as creating a GitHub Issue)
WHEN the saga engine executes the action step
THEN it SHALL persist and COMMIT a `SagaActionModel` record with `execution_state = "REQUESTED"`, `action_key`, `target_identity`, and `request_fingerprint`
AND SHALL invoke the external adapter ONLY AFTER durable DB commit confirmation.

#### Scenario: Completed action with SUCCESS state is skipped on retry
GIVEN a saga action step whose `SagaActionModel` record exists in DB with `execution_state = "SUCCESS"` and valid `observed_result_identity`
WHEN the saga engine retries or resumes execution of the phase
THEN it SHALL skip the external mutation entirely
AND SHALL reuse the persisted `observed_result_identity`.

---

### Requirement: Reconcile Before Retry Protocol for Ambiguous Outcomes

When an external action is found in `REQUESTED`, `IN_FLIGHT`, or `AMBIGUOUS` state following a restart, network timeout, or ambiguous response, the saga engine SHALL query the target external system using target and fingerprint evidence before attempting to re-execute the mutation.

#### Scenario: Remote side effect discovered during reconciliation is adopted without duplication
GIVEN a saga action `GITHUB_ISSUE_CREATE` in state `REQUESTED` due to a process crash during HTTP call
WHEN the saga engine executes reconciliation before retry
THEN it SHALL search the target GitHub repository for an issue matching the request fingerprint and title
AND WHEN matching issue #42 is found, it SHALL record `observed_result_identity = "#42"`, update action state to `SUCCESS`, and advance phase without creating a duplicate issue.

#### Scenario: Non-occurrence confirmed by reconciliation authorizes safe execution
GIVEN a saga action `GITHUB_ISSUE_CREATE` in state `REQUESTED`
WHEN reconciliation queries the remote GitHub repository and positively confirms no matching issue exists
THEN the saga engine SHALL classify the retry as `SAFE_TO_RETRY`
AND SHALL proceed to invoke `GitHubAdapter.create_issue()` safely.

#### Scenario: Unobservable remote state transitions action to AMBIGUOUS and blocks saga
GIVEN a saga action reconciliation attempt encountering remote HTTP 503 or network failure
WHEN external occurrence cannot be confirmed or disconfirmed
THEN the saga action SHALL transition to `AMBIGUOUS`
AND the saga status SHALL transition to `BLOCKED` with `blocking_reason`
AND the system SHALL emit a `DURABLE_SAGA_BLOCKED` event and wait for operator intervention.

---

### Requirement: Terminal Identity Protection and Non-Resurrection Guarantee

The saga engine and lifecycle authority SHALL enforce that terminal work items (`Change.status IN ('DONE', 'CANCELLED')` or `BacklogItem.status IN ('COMPLETED', 'CANCELLED')`) CANNOT be resurrected or re-executed by intake or closure sagas.

#### Scenario: Intake attempt on COMPLETED backlog item rejected
GIVEN a backlog item with `status = COMPLETED`
WHEN an intake API call or background sweep attempts to create or start an intake saga for the item key
THEN the system SHALL reject the request with outcome `FAILURE`
AND reason_code SHALL be `POLICY_DENIED`
AND no saga SHALL be initialized.

#### Scenario: Closure attempt on DONE change rejected
GIVEN an OpenSpec change with `status = DONE`
WHEN a post-merge reconciliation trigger attempts to start a closure saga for the change name
THEN the system SHALL reject the execution with outcome `SUCCESS` and `already_closed = True`
AND SHALL NOT re-run spec sync, archiving, worktree cleanup, or branch deletion.

---

### Requirement: Daemon Restart Recovery and Control-Plane Saga Continuation

The system SHALL automatically discover, reconcile, and safely resume in-flight and blocked sagas on daemon startup and SHALL provide control-plane endpoints for manual operator saga inspection and resume.

#### Scenario: Startup recovery resumes in-progress sagas from safe checkpoints
GIVEN one or more sagas in `durable_sagas` with `status IN ('IN_PROGRESS', 'BLOCKED')`
WHEN `RestartRecoveryService.reconcile_on_startup()` executes on daemon startup
THEN it SHALL iterate over active sagas, inspect action states, execute reconciliation before retry for ambiguous actions, and resume safe execution from persisted checkpoints.

#### Scenario: Control-plane operator saga resume triggers idempotent continuation
GIVEN an operator issuing a saga resume command via `ControlPlaneService` for saga ID S
WHEN the control plane processes the command
THEN it SHALL acquire row lock on saga S, inspect phase evidence, and resume execution from the current phase checkpoint
AND IF saga S is already `COMPLETED`, it SHALL return outcome `SUCCESS` with `already_closed = True`.
