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

### Requirement: Durable Closure Saga Persistence and Squash-Merge Aware Delivery Verification

The system SHALL execute post-human-merge closure and cleanup operations through a PostgreSQL-persisted, phase-checkpointed `DurableSagaModel` (`saga_type = CLOSURE`), delivery verification SHALL explicitly support both normal ancestry-preserving merges and squash merges, and terminal `Change.DONE` and `BacklogItem.COMPLETED` transitions SHALL be DENIED until ALL required closure phases are durably proven complete.

#### Scenario: Post-merge reconciliation creates durable closure saga
GIVEN a merged pull request observed for a change and run
WHEN PostMergeReconciliationService begins post-merge closure
THEN it SHALL create and commit a `DurableSagaModel` record in PostgreSQL with `saga_type = "CLOSURE"`, `status = "IN_PROGRESS"`, and `current_phase = "MERGE_OBSERVED"`
AND SHALL record PR merge observation evidence in the saga record.

#### Scenario: Squash merge delivery verified using merge commit evidence
GIVEN a pull request merged via GitHub squash merge
WHEN the closure saga evaluates phase `MERGED_DELIVERY_VERIFIED`
THEN it SHALL verify PR `is_merged == True`, repository/base identity is exact, PR head SHA equals audited candidate SHA, and observed `merge_commit_sha` exists on base branch
AND candidate non-ancestry SHALL NOT be treated as a verification failure.

#### Scenario: Normal merge delivery verified using Git ancestry
GIVEN a pull request merged via normal merge or fast-forward
WHEN the closure saga evaluates phase `MERGED_DELIVERY_VERIFIED`
THEN it SHALL verify that `git merge-base --is-ancestor candidate_sha base_ref` returns exit code 0.

#### Scenario: Missing phase evidence blocks terminal Change and BacklogItem closure
GIVEN a closure saga executing post-merge closure
WHEN OpenSpec spec sync, archive verification, worktree cleanup, or branch cleanup fails or is incomplete
THEN the saga engine SHALL transition saga status to `BLOCKED` with canonical outcome `WAIT_EXTERNAL` or `NEEDS_HUMAN`
AND SHALL NOT transition `Change` to `DONE` or `BacklogItem` to `COMPLETED`.

---

### Requirement: Single External Action Store, Action Ownership Invariant, and Stage B Exact Identity Reconciliation

All saga-bound external mutations (GitHub Issue creation, GitHub Project item addition, OpenSpec file authoring, GitHub Issue closure, GitHub Project item status update, OpenSpec spec sync, OpenSpec change archiving, worktree cleanup, branch deletion, lock release) SHALL reserve an `OrchestrationExternalActionModel` record in PostgreSQL with `status = RESERVED` and a deterministic `request_fingerprint` BEFORE invoking external adapters, action records SHALL satisfy the operational ownership invariant (`run_id is not None or saga_id is not None`), and reconciliation SHALL delegate to `reconcile_observe_before_repeat()` enforcing Stage B exact identity matching.

#### Scenario: Action reservation committed before remote mutation
GIVEN an intake or closure saga preparing an external action (such as creating a GitHub Issue)
WHEN the saga engine executes the action step
THEN it SHALL persist and COMMIT an `OrchestrationExternalActionModel` record with `status = "RESERVED"`, `action_key`, `target_identity`, `saga_id`, and `request_fingerprint`
AND SHALL invoke the external adapter ONLY AFTER durable DB commit confirmation.

#### Scenario: Action without operational owner denied by ownership invariant
GIVEN a request to create or persist an `OrchestrationExternalAction` record
WHEN both `run_id` and `saga_id` are `None`
THEN the domain model and repository SHALL reject the action record as invalid
AND NO record SHALL be persisted to PostgreSQL.

#### Scenario: GitHub Issue creation reconciled via exact Stage B comment marker
GIVEN a saga action `GITHUB_ISSUE_CREATE` in state `RESERVED` following a daemon restart
WHEN the saga engine executes reconciliation before retry via `reconcile_observe_before_repeat()`
THEN it SHALL search repository issues for the exact comment marker `<!-- minime-opkey: <operation_key> -->`
AND WHEN matching issue #42 is found, it SHALL adopt issue #42, update action status to `COMPLETED` (setting `reconciled_at`), and advance phase
AND title-only deduplication SHALL be strictly FORBIDDEN.

#### Scenario: GitHub Project item creation reconciled via exact issue URL
GIVEN a saga action `GITHUB_PROJECT_ITEM_ADD` in state `RESERVED` following a daemon restart
WHEN the saga engine executes reconciliation before retry via `reconcile_observe_before_repeat()`
THEN it SHALL query project items for the exact bound issue URL
AND WHEN matching project item is found, it SHALL adopt the item ID, update action status to `COMPLETED` (setting `reconciled_at`), and advance phase
AND fuzzy title matching SHALL be strictly FORBIDDEN.

#### Scenario: Unobservable remote state transitions action to AMBIGUOUS and blocks saga
GIVEN a saga action reconciliation attempt encountering remote HTTP 503 or network failure
WHEN external occurrence cannot be confirmed or disconfirmed
THEN the saga action SHALL transition to `AMBIGUOUS`
AND the saga status SHALL transition to `BLOCKED` with `blocking_reason`
AND the system SHALL emit a `DURABLE_SAGA_BLOCKED` event and wait for operator intervention.

---

### Requirement: Terminal Domain State Protection and Reconciliation Mode

The saga engine and lifecycle authority SHALL enforce that terminal domain items (`Change.status IN ('DONE', 'CANCELLED')` or `BacklogItem.status IN ('COMPLETED', 'CANCELLED')`) CANNOT be re-opened or re-admitted during intake, and an already terminal domain state during closure SHALL NOT infer saga closure success without complete required evidence.

#### Scenario: Intake attempt on COMPLETED backlog item rejected
GIVEN a backlog item with `status = COMPLETED`
WHEN an intake API call or background sweep attempts to create or start an intake saga for the item key
THEN the system SHALL reject the request with outcome `FAILURE`
AND reason_code SHALL be `POLICY_DENIED`
AND no saga SHALL be initialized.

#### Scenario: Terminal domain state with incomplete closure evidence enters reconciliation mode
GIVEN a Change with `status = DONE` in DB BUT a `ClosureSaga` with incomplete spec sync or archive evidence
WHEN post-merge reconciliation executes
THEN the saga engine SHALL NOT infer saga closure success and SHALL NOT resurrect domain work
AND it SHALL enter reconciliation-only mode to observe/check missing closure postconditions
AND it SHALL transition saga status to `COMPLETED` ONLY when all 12 required closure phase evidence records exist.

---

### Requirement: Daemon Restart Recovery and Control-Plane Continuation

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

---

### Requirement: Concurrency Scope Boundary Separation

Stage D SHALL provide durable saga identity, deterministic action identity, row-locking idempotency for sequential resume, and checkpoint recovery, and full multi-worker concurrent admission and race proving SHALL be explicitly deferred to `Stage F — transaction-and-concurrency-contract`.

#### Scenario: Concurrent resume requests execute sequentially via row lock
GIVEN two concurrent resume requests targeting the same saga ID S
WHEN both requests reach the saga engine
THEN the saga engine SHALL use atomic row locking (`SELECT ... FOR UPDATE`) to serialize execution
AND the second request SHALL observe the updated saga state idempotently without executing duplicate actions.
