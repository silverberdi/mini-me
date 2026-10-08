# operator-actions-control-plane Specification

## Purpose
TBD - created by archiving change 015-operator-actions-control-plane. Update Purpose after archive.

## Requirements

### Requirement: Canonical Operator Action Discovery
The system SHALL provide a canonical action discovery interface that returns all supported operator actions for a specified run, marking each action as enabled or disabled with a human-readable explanation, confirmation requirement, risk level, and required parameters schema without presentation layers implementing action business logic.

#### Scenario: Discover actions for resumable run
Given an orchestration run stopped at `STOPPED_AT_GATE` or with a valid `resumable_stage`
When an operator queries available actions for the run
Then the system SHALL return `CONTINUE` marked as `enabled=True`
And the system SHALL return `CANCEL` marked as `enabled=False` with `disabled_reason="Run is not active"`.

#### Scenario: Discover actions for active running execution
Given an active orchestration run currently in stage `IMPLEMENTING`
When an operator queries available actions for the run
Then the system SHALL return `CANCEL` marked as `enabled=True` with `requires_confirmation=True`
And the system SHALL return `CONTINUE` marked as `enabled=False` with `disabled_reason="Run is already active"`.

#### Scenario: Discover actions for UI validation gate
Given an orchestration run stopped at human gate `UI_VALIDATION_REQUIRED`
When an operator queries available actions for the run
Then the system SHALL return `RESOLVE_GATE` (validation) marked as `enabled=True` with required parameters schema for verdict and notes
And the system SHALL return `START_PREVIEW` and `TEARDOWN_PREVIEW` with appropriate enabled states.

### Requirement: Governed Action Execution with Authority Validation
The system SHALL execute operator actions only after verifying all authority requirements, including project registration, run existence, state compatibility, provider capacity/policy, and gate resolution rules, rejecting unpermitted actions before operational state mutation.

#### Scenario: Reject illegal action transition
Given an orchestration run in stage `PR_PREPARED`
When an operator requests a `REASSIGN` action
Then the system SHALL reject the request with status `REJECTED` and error code `ACTION_NOT_ALLOWED`
And the system SHALL NOT mutate run state or execute provider operations.

#### Scenario: Execute continue action on resumable run
Given an orchestration run stopped with `resumable_stage=PREPARING_EXECUTION`
When an operator submits a valid `CONTINUE` action request
Then the system SHALL accept the request with status `COMPLETED`
And the run SHALL resume execution using canonical orchestration semantics.

### Requirement: Optimistic Concurrency and Stale State Protection
The system SHALL accept expected state parameters (`expected_stage`, `expected_generation`, `expected_candidate_sha`, `expected_human_gate`) and reject requests where the canonical state in PostgreSQL has changed since the operator loaded their screen.

#### Scenario: Reject request with stale candidate SHA
Given an orchestration run whose current candidate SHA is `abc1234`
When an operator submits an action request specifying `expected_candidate_sha="def5678"`
Then the system SHALL reject the request with status `REJECTED` and error code `STALE_OPERATOR_STATE`
And the response SHALL summarize that the candidate SHA has changed.

#### Scenario: Accept request matching current state
Given an orchestration run whose current stage is `RUNNING_CHECKS` and generation is `1`
When an operator submits an action request specifying `expected_stage="RUNNING_CHECKS"` and `expected_generation=1`
Then the system SHALL proceed with authority evaluation and execution.

### Requirement: Deterministic Request Idempotency
The system SHALL require or generate a unique `action_request_id` for every action request and ensure that duplicate requests with the same ID return the previously persisted result without duplicate state transitions, duplicate jobs, or duplicate side effects.

#### Scenario: Repeated duplicate action request
Given an action request with ID `req-12345` that completed successfully
When the client re-submits an identical action request with ID `req-12345`
Then the system SHALL return the previously recorded result with status `COMPLETED`
And no additional database events, jobs, or handoffs SHALL be created.

### Requirement: Safe Non-Destructive Cancellation
The system SHALL support cancelling active runs safely, ensuring that candidate history, check evidence, review findings, Git references, and worktree ownership are preserved while stopping active subprocesses and tearing down owned container preview resources. A successful cancellation SHALL also terminalize the non-terminal Job referenced by the run's active-job identity, so neither the cancelled run nor its linked job consumes execution concurrency.

#### Scenario: Cancel active running execution
- **GIVEN** an active orchestration run in stage `IMPLEMENTING` with an active container preview
- **WHEN** an operator submits a `CANCEL` action request
- **THEN** the system SHALL mark the run `is_active=False` with `stop_outcome="CANCELLED"`
- **AND** the container preview SHALL be torn down
- **AND** historical candidate evidence and Git worktrees SHALL remain preserved.

#### Scenario: Cancel active running execution with linked queued job
- **GIVEN** an active orchestration run in stage `IMPLEMENTING` with an active container preview and a linked `QUEUED` job
- **WHEN** an operator submits a valid `CANCEL` action request
- **THEN** the system SHALL canonically transition the linked job to `CANCELLED`
- **AND** the system SHALL mark the run `is_active=False` with `stop_outcome="CANCELLED"`
- **AND** the container preview SHALL be torn down
- **AND** historical candidate evidence and Git worktrees SHALL remain preserved
- **AND** the linked job SHALL not be returned by the canonical active-job selector.

#### Scenario: Preserve an already terminal linked job
- **GIVEN** an active orchestration run whose linked job is `COMPLETED` or `CANCELLED`
- **WHEN** an operator submits a valid `CANCEL` action request
- **THEN** the system SHALL preserve the linked job's terminal status without reopening or rewriting it
- **AND** the system SHALL cancel the run while preserving its history and evidence.

#### Scenario: Reject broken linked-job identity without partial cancellation
- **GIVEN** an active orchestration run whose active-job identity references no Job
- **WHEN** an operator submits a `CANCEL` action request
- **THEN** the action SHALL not report `COMPLETED`
- **AND** the run SHALL remain active and not cancelled
- **AND** no linked Job state SHALL be fabricated or mutated
- **AND** the action failure SHALL be durably auditable.

#### Scenario: Fail closed if linked-job cancellation cannot complete
- **GIVEN** an active orchestration run with a non-terminal linked Job
- **WHEN** linked-job cancellation fails before the cancellation command commits
- **THEN** the run SHALL remain active and not cancelled
- **AND** the Job SHALL retain its pre-command state
- **AND** only the failed operator-action outcome SHALL be durably recorded after rollback.

### Requirement: Durable Action Audit Persistence
The system SHALL record every operator action request and outcome in an immutable PostgreSQL audit table (`operator_action_records`) capturing request ID, actor, source interface, target, precondition state, outcome, error code, timestamps, and redacted parameter payloads.

#### Scenario: Persist audit record on action execution
Given an operator action request submitted via the TUI
When the action is processed to completion or rejection
Then an immutable `OperatorActionRecord` SHALL be persisted in PostgreSQL
And the record SHALL contain redacted parameters without sensitive credentials or secrets.

### Requirement: TUI Operator Console Action Integration
The TUI operator console SHALL display available actions for the selected run, enable only legal actions with clear disabled explanations, prompt for confirmation on material actions, provide immediate visual feedback, and render action history without querying the database directly.

#### Scenario: Trigger action with confirmation in TUI
Given an active run selected in the TUI Run Detail view
When the operator presses `a` or clicks `Cancel`
Then the TUI SHALL display a confirmation modal explaining the cancellation consequence
And when confirmed, the TUI SHALL execute the action via the control plane and refresh the run detail view.

### Requirement: Reconcile cancelled-run linked-job terminality
The system SHALL provide a narrow, idempotent canonical reconciliation for a run that is already inactive with `stop_outcome="CANCELLED"` and whose active-job identity references a non-terminal Job. The reconciliation SHALL transition only that linked Job to `CANCELLED` through the canonical job transition authority and SHALL not reopen the run, replay cancellation side effects, delete history, or alter Change or BacklogItem lifecycle state.

#### Scenario: Reconcile historical cancelled run with active linked job
- **GIVEN** an inactive run with `stop_outcome="CANCELLED"` and a linked `QUEUED` Job
- **WHEN** the canonical reconciliation is invoked
- **THEN** the Job SHALL transition to `CANCELLED`
- **AND** the run SHALL remain inactive with `stop_outcome="CANCELLED"`
- **AND** preserved candidate, worktree, and audit evidence SHALL remain unchanged.

#### Scenario: Repeat reconciliation after linked job is terminal
- **GIVEN** an inactive cancelled run whose linked Job is already `CANCELLED` or `COMPLETED`
- **WHEN** the canonical reconciliation is invoked again
- **THEN** the reconciliation SHALL be idempotent
- **AND** it SHALL not rewrite the terminal Job or replay cancellation side effects.
