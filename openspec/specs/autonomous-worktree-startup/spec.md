# Autonomous Worktree Startup Specification

## Purpose
Natively initiate candidate execution runs and allocate isolated candidate worktrees upon scheduler admission without external operator intervention.

## Requirements

### Requirement: Autonomous Candidate Worktree and Run Creation
Upon successful admission of a candidate work item, the system SHALL automatically create an `OrchestrationRun`, allocate an isolated candidate worktree under `.minime/worktrees/<job_id>`, instantiate a `Job` with the assigned primary implementer, and transition the run to `ADMITTED`. When the registered base repository has a valid installed `node_modules` directory corresponding to a root or `frontend/package.json`, the new worktree SHALL make those dependencies available at the matching package path without network installation or manual agent action. Dependency links and their targets SHALL remain ignored by Git and SHALL NOT enter the candidate index or commit.

#### Scenario: Successfully admitted item initiates execution
- **GIVEN** candidate change `016-autonomous-queue-work-selection` is admitted by the scheduler
- **WHEN** `SchedulerService.admit_work_item()` executes
- **THEN** an `OrchestrationRun` in stage `ADMITTED` SHALL be persisted
- **AND** an immutable `SchedulerDecisionRecord` with `decision=ADMITTED` SHALL be logged
- **AND** the work queue item SHALL be updated with the active run reference.

#### Scenario: New worktree reuses installed root dependencies
- **GIVEN** the registered base repository contains a root `package.json` and valid root `node_modules`
- **WHEN** the scheduler creates a candidate worktree
- **THEN** dependencies SHALL be available at the worktree root without fetching or installing packages
- **AND** the dependency link SHALL be ignored and absent from the Git index and candidate commit.

#### Scenario: New worktree reuses installed frontend dependencies
- **GIVEN** the registered base repository contains `frontend/package.json` and valid `frontend/node_modules`
- **WHEN** the scheduler creates a candidate worktree
- **THEN** dependencies SHALL be available at `frontend/node_modules` without fetching or installing packages
- **AND** the dependency link SHALL be ignored and absent from the Git index and candidate commit.

### Requirement: Startup Idempotency
Repeated scheduler ticks or concurrent evaluation attempts SHALL NOT create duplicate orchestration runs, duplicate jobs, or colliding worktree directories for an already active change.

#### Scenario: Repeated tick for admitted change is idempotent
- **GIVEN** an orchestration run is already active for change `016-autonomous-queue-work-selection`
- **WHEN** subsequent scheduler ticks evaluate the same change
- **THEN** admission SHALL be refused with `AdmissionRefusalCode.CHANGE_ALREADY_ACTIVE`
- **AND** no duplicate run or worktree SHALL be created.
