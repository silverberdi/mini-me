# Spec: Autonomous Intake Preparation & Admission Policy

## ADDED Requirements

### Requirement: Automatic Preparation upon Backlog Item Creation
The system SHALL automatically initiate canonical intake preparation when a new backlog item is created for a project configured with `auto_prepare = true`, creating or synchronizing the GitHub Issue, GitHub Project item, and OpenSpec change artifacts without manual operator intervention.

#### Scenario: Automatic preparation on creation
Given a registered project with `auto_prepare = true`
When a new backlog item is created with valid title and description
Then canonical preparation executes automatically without operator intervention
And GitHub Issue, GitHub Project item, and OpenSpec change artifacts are created or synchronized.

### Requirement: Product Ambiguity Gate
The system SHALL detect missing or ambiguous product requirements during intake preparation, transition the backlog item to `NEEDS_HUMAN` with targeted clarification questions, and automatically resume preparation upon receipt of answers.

#### Scenario: Ambiguity detection and resume
Given a backlog item created with insufficient or ambiguous requirements
When preparation evaluates the item
Then the item transitions to `NEEDS_HUMAN` with specific clarification questions
And when the operator provides answers, preparation resumes automatically.

### Requirement: Automatic Definition of Ready (DoR) Transition
The system SHALL evaluate Definition of Ready criteria upon completion of preparation and transition qualifying items automatically to `READY` status.

#### Scenario: Automatic transition to READY
Given a prepared backlog item satisfying all Definition of Ready criteria
When readiness evaluation completes
Then the backlog item transitions automatically to `READY`
And `WorkQueueItem` is updated with `admission_eligible = true`.

### Requirement: Project-Level Admission Policy Defaults
The system SHALL support configurable project-level admission policies with canonical default values: `auto_prepare = true`, `auto_admit = true`, and `max_concurrent_jobs = 1`.

#### Scenario: Project policy defaults
Given a project registered or updated in mini me
When admission policy is queried
Then default configuration is `auto_prepare = true`, `auto_admit = true`, and `max_concurrent_jobs = 1`.

### Requirement: Auto-Admission Eligibility Verification
The system SHALL verify all required admission preconditions before admitting a `READY` backlog item to execution.

#### Scenario: Precondition verification
Given a backlog item in `READY` status
When the scheduler evaluates the item for admission
Then admission is granted only if:
  - all prerequisite dependencies are `COMPLETED`,
  - project/repository binding is valid,
  - no blocking human gate is active,
  - active concurrent runs are less than `max_concurrent_jobs`,
  - required primary execution provider is `AVAILABLE`,
  - scheduler mode is `RUN`.

### Requirement: Provider Unavailability Waiting
The system SHALL hold eligible `READY` work in a waiting state when the required primary execution provider is unavailable, strictly preventing OpenRouter drain fallback from starting new work and preserving attempt budgets.

#### Scenario: Waiting for primary provider capacity
Given an eligible `READY` work item and an unavailable primary provider (e.g. `TEMPORARILY_UNAVAILABLE` or `EXHAUSTED`)
When admission is evaluated
Then the item remains in `READY` waiting state without consuming attempt budget
And OpenRouter drain fallback is strictly prevented from starting the new work
And the reason is observable as awaiting provider capacity.

### Requirement: Autonomous Recovery Admission
The system SHALL automatically admit waiting `READY` work on the subsequent scheduler tick when generic provider recovery probing restores provider status to `AVAILABLE`.

#### Scenario: Auto-admission on capacity recovery
Given an eligible `READY` work item waiting for provider capacity
When generic provider recovery probing restores provider health to `AVAILABLE`
Then the scheduler automatically admits the item on the next tick without requiring a manual "Start Work" click.

### Requirement: Deterministic Backlog Ranking & Priority Selection
The system SHALL rank eligible `READY` backlog items deterministically using priority, dependency topology, and creation timestamp, persisting explicit selection rationales.

#### Scenario: Backlog priority ranking
Given multiple eligible `READY` backlog items in a project
When the scheduler selects work for available concurrency slots
Then items are ranked deterministically by priority (`CRITICAL` > `HIGH` > `NORMAL` > `LOW`), dependency depth, and creation timestamp
And the selection rationale is persisted and observable.

### Requirement: Sequential Execution & Slot Release
The system SHALL release the concurrency slot upon terminal closure of an execution and immediately evaluate the backlog to admit the next eligible item.

#### Scenario: Sequential execution with concurrency limit
Given `max_concurrent_jobs = 1` and an admitted active execution
When the active execution reaches terminal closure (`COMPLETED` or `CANCELLED`)
Then the concurrency slot is released
And the scheduler automatically re-evaluates the backlog and admits the next eligible `READY` item.

### Requirement: Excluded States Protection
The system SHALL strictly exclude backlog items in non-ready states from auto-admission.

#### Scenario: Ineligible states excluded
Given backlog items in `DRAFT`, `NEEDS_HUMAN`, `BLOCKED`, or paused state
When auto-admission evaluates candidates
Then these items are strictly excluded from admission.

### Requirement: Idempotency & Bookkeeping Efficiency
The system SHALL ensure that continuous scheduler evaluation cycles produce zero duplicate artifacts or executions and consume zero LLM tokens for deterministic bookkeeping.

#### Scenario: Idempotent cycle evaluation
Given continuous periodic scheduler ticks
When backlog and queue states are evaluated
Then zero duplicate Issues, Project items, OpenSpec changes, Runs, or Jobs are created
And zero routine LLM calls are used for deterministic bookkeeping.

### Requirement: Observability in PWA & TUI
The system SHALL expose preparation state, readiness state, auto-admission policy, waiting reasons, and queue priority across PWA and TUI interfaces.

#### Scenario: Interface observability
Given the operator views the Backlog & Intake surface in PWA or TUI
When items are rendered
Then preparation state, readiness state, auto-admission policy, waiting reasons, and queue priority are explicitly displayed.
