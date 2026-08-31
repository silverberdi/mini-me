# Autonomous Worktree Startup Specification

## Purpose
Natively initiate candidate execution runs and allocate isolated candidate worktrees upon scheduler admission without external operator intervention.

## Requirements

### Requirement: Autonomous Candidate Worktree and Run Creation
Upon successful admission of a candidate work item, the system SHALL automatically create an `OrchestrationRun`, allocate an isolated candidate worktree under `.minime/worktrees/<job_id>`, instantiate a `Job` with the assigned primary implementer, and transition the run to `ADMITTED`.

#### Scenario: Successfully admitted item initiates execution
- **GIVEN** candidate change `016-autonomous-queue-work-selection` is admitted by the scheduler
- **WHEN** `SchedulerService.admit_work_item()` executes
- **THEN** an `OrchestrationRun` in stage `ADMITTED` SHALL be persisted
- **AND** an immutable `SchedulerDecisionRecord` with `decision=ADMITTED` SHALL be logged
- **AND** the work queue item SHALL be updated with the active run reference.

### Requirement: Startup Idempotency
Repeated scheduler ticks or concurrent evaluation attempts SHALL NOT create duplicate orchestration runs, duplicate jobs, or colliding worktree directories for an already active change.

#### Scenario: Repeated tick for admitted change is idempotent
- **GIVEN** an orchestration run is already active for change `016-autonomous-queue-work-selection`
- **WHEN** subsequent scheduler ticks evaluate the same change
- **THEN** admission SHALL be refused with `AdmissionRefusalCode.CHANGE_ALREADY_ACTIVE`
- **AND** no duplicate run or worktree SHALL be created.
