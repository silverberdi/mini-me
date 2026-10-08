## MODIFIED Requirements

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

## ADDED Requirements

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
