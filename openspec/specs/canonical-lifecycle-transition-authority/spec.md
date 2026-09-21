# canonical-lifecycle-transition-authority Specification

## Purpose
Define the single canonical transition authority (`LifecycleTransitionAuthority`) for durable `Change.status` and `BacklogItem.status`, enforcing compare-and-set atomic operations, persistence-level bypass protection, monotonic terminal state rules, observation purity, and explicit read-after-write transaction semantics.

## Requirements

### Requirement: Single canonical lifecycle transition authority

The system SHALL provide one canonical authority (`LifecycleTransitionAuthority`) as the SINGLE WRITER of durable `Change.status` and `BacklogItem.status`, with business services acting as authorized callers.

#### Scenario: Stale transition request
GIVEN a transition request expecting state READY
AND durable state is IN_PROGRESS
WHEN transition is evaluated by LifecycleTransitionAuthority
THEN it SHALL be rejected as stale
AND no lifecycle mutation SHALL occur.

### Requirement: Monotonic terminal lifecycle

The system SHALL treat `Change.DONE`, `Change.CANCELLED`, `BacklogItem.COMPLETED`, and `BacklogItem.CANCELLED`
as terminal for their existing identity.

#### Scenario: Completed Change cannot become READY
GIVEN Change status is DONE
WHEN any discovery, readiness, scheduler, recovery, intake, or operator path requests READY
THEN the transition SHALL be rejected
AND Change status SHALL remain DONE.

#### Scenario: Completed BacklogItem cannot become READY
GIVEN BacklogItem status is COMPLETED
WHEN any discovery or intake process requests transition to READY
THEN the transition SHALL be rejected
AND BacklogItem status SHALL remain COMPLETED.

### Requirement: Persistence-level lifecycle status protection

The system SHALL enforce that generic repository `save()` and `update()` methods on existing `Change` and `BacklogItem` entities deterministically reject status mutations by raising a `LifecycleBypassError` and performing zero lifecycle or metadata mutations.

#### Scenario: Generic repository save with status change fails deterministically with LifecycleBypassError
GIVEN an existing Change or BacklogItem entity in status READY
WHEN a caller modifies its status field to RUNNING and invokes generic repository save()
THEN save() SHALL fail deterministically by raising LifecycleBypassError
AND the durable status in PostgreSQL SHALL remain READY.

#### Scenario: Generic repository save fails atomically without persisting metadata or emitting events
GIVEN an existing BacklogItem in status READY
AND a caller modifies its status to RUNNING plus unrelated metadata fields
WHEN generic repository save() is invoked
THEN the operation SHALL raise LifecycleBypassError
AND durable status SHALL remain READY
AND no unrelated metadata SHALL be persisted
AND no lifecycle transition event SHALL be emitted.

#### Scenario: Generic repository save with matching status updates metadata
GIVEN an existing BacklogItem in status READY
AND a caller updates non-lifecycle metadata fields while keeping status as READY
WHEN generic repository save() is invoked
THEN the operation SHALL succeed and update the non-lifecycle metadata.

#### Scenario: Initial creation establishes initial status
GIVEN a newly created Change or BacklogItem entity being inserted for the first time
WHEN generic repository save() or insert is invoked
THEN the entity SHALL be saved with its initial status.

### Requirement: Atomic compare-and-set transition primitive

Lifecycle status transitions SHALL execute an atomic compare-and-set (CAS) SQL query expecting exactly 1
affected row, failing closed with a conflict error if 0 rows are affected.

#### Scenario: Atomic CAS succeeds on expected state
GIVEN a BacklogItem in status READY
WHEN a transition command requests state ADMITTED expecting status READY
THEN an atomic CAS query SHALL update status to ADMITTED
AND exactly 1 row SHALL be affected.

#### Scenario: Stale state fails CAS with conflict
GIVEN a BacklogItem currently in status IN_PROGRESS
WHEN a transition command requests state ADMITTED expecting status READY
THEN the atomic CAS query SHALL affect 0 rows
AND the transition SHALL fail with a state conflict error.

### Requirement: Canonical ChangeStatus transition matrix

Transitions for `Change.status` SHALL strictly conform to the allowed matrix:
DISCOVERED -> READY | BLOCKED | CANCELLED; READY -> IN_PROGRESS | BLOCKED | CANCELLED;
IN_PROGRESS -> BLOCKED | DONE | CANCELLED; BLOCKED -> READY | IN_PROGRESS | CANCELLED;
DONE -> none; CANCELLED -> none.

#### Scenario: Valid ChangeStatus transition succeeds
GIVEN a Change in DISCOVERED status
WHEN a transition to READY is requested via LifecycleTransitionAuthority
THEN the transition SHALL succeed and Change status SHALL become READY.

#### Scenario: Invalid ChangeStatus transition rejected
GIVEN a Change in DISCOVERED status
WHEN a transition to DONE is requested via LifecycleTransitionAuthority
THEN the transition SHALL be rejected as invalid.

### Requirement: Canonical WorkItemStatus transition matrix

Transitions for `BacklogItem.status` SHALL strictly conform to the allowed matrix:
BACKLOG -> CONTEXT_CHECK | PREPARING | CANCELLED; CONTEXT_CHECK -> PREPARING | NEEDS_HUMAN | BLOCKED | CANCELLED;
PREPARING -> NEEDS_HUMAN | READY | BLOCKED | CANCELLED; NEEDS_HUMAN -> PREPARING | BLOCKED | CANCELLED;
READY -> ADMITTED | NEEDS_HUMAN | BLOCKED | CANCELLED; ADMITTED -> RUNNING | NEEDS_HUMAN | BLOCKED | CANCELLED;
RUNNING -> NEEDS_HUMAN | BLOCKED | COMPLETED | CANCELLED; BLOCKED -> PREPARING | READY | NEEDS_HUMAN | CANCELLED;
COMPLETED -> none; CANCELLED -> none.

#### Scenario: Valid WorkItemStatus transition succeeds
GIVEN a BacklogItem in PREPARING status
WHEN a transition to READY is requested via LifecycleTransitionAuthority
THEN the transition SHALL succeed and BacklogItem status SHALL become READY.

#### Scenario: Invalid WorkItemStatus transition rejected
GIVEN a BacklogItem in BACKLOG status
WHEN a transition to RUNNING is requested via LifecycleTransitionAuthority
THEN the transition SHALL be rejected as invalid.

### Requirement: Phase separation for ADMITTED and RUNNING

The system SHALL separate fresh admission authorization (`READY -> ADMITTED`) requested by `SchedulerService` from execution start (`ADMITTED -> RUNNING`) requested by `OrchestrationService`.

#### Scenario: Scheduler admits READY work to ADMITTED
GIVEN a BacklogItem in status READY
WHEN SchedulerService requests fresh admission authorization
THEN status SHALL transition from READY to ADMITTED via LifecycleTransitionAuthority.

#### Scenario: Execution start transitions ADMITTED to RUNNING
GIVEN a BacklogItem in status ADMITTED
WHEN OrchestrationService starts execution of the admitted work
THEN status SHALL transition from ADMITTED to RUNNING via LifecycleTransitionAuthority.

### Requirement: Non-destructive cancellation

The system SHALL execute work item cancellation (`delete_work_item`) as a non-destructive transition to `CANCELLED`, preserving the entity row, identity, history, links, and evidence in PostgreSQL.

#### Scenario: Delete work item transitions to CANCELLED and preserves row
GIVEN an existing BacklogItem in PostgreSQL
WHEN delete_work_item is invoked by an operator or service
THEN status SHALL transition to CANCELLED via LifecycleTransitionAuthority
AND the BacklogItem row SHALL remain persisted in the database.

#### Scenario: Cancelled item cannot be readmitted or rediscovered
GIVEN a BacklogItem in status CANCELLED
WHEN discovery, intake, or scheduler processes evaluate the item
THEN it SHALL NOT be readmitted, resurrected, or transitioned to executable states.

### Requirement: PostMergeService authority integration

PostMergeService SHALL route all `Change` and `BacklogItem` lifecycle completions through `LifecycleTransitionAuthority`.

#### Scenario: PostMergeService requests DONE and COMPLETED via authority
GIVEN a merged change undergoing post-merge reconciliation
WHEN PostMergeService completes reconciliation
THEN Change status SHALL transition to DONE and BacklogItem status SHALL transition to COMPLETED strictly via LifecycleTransitionAuthority.

### Requirement: Orthogonality of readiness and completion

Terminal completion of a BacklogItem SHALL NOT overwrite or force `readiness_state` to `READY`.

#### Scenario: Terminal completion preserves actual readiness state without forcing READY
GIVEN a BacklogItem transitioning to status COMPLETED
WHEN the transition is persisted by LifecycleTransitionAuthority
THEN the existing `readiness_state` SHALL be preserved without forcing `readiness_state = READY`.

### Requirement: UNKNOWN evaluation result fails closed

When an evaluation cannot observe required evidence, the evaluation outcome SHALL be explicitly `UNKNOWN`, which fails closed and NEVER authorizes `READY`, `ADMITTED`, `RUNNING`, `DONE`, or `COMPLETED`.

#### Scenario: Unobservable evidence yields UNKNOWN and blocks progression
GIVEN required evidence is missing or unobservable during evaluation
WHEN readiness or intake evaluation runs
THEN the outcome SHALL evaluate to UNKNOWN
AND transition to READY, ADMITTED, RUNNING, DONE, or COMPLETED SHALL be blocked.

### Requirement: Atomic lifecycle transition audit event

Every successful lifecycle transition SHALL produce exactly one durable transition audit event within the same database transaction unit of work as the state mutation, rolling back state if event persistence fails.

#### Scenario: Successful transition emits durable event in same transaction
GIVEN a valid lifecycle transition request
WHEN LifecycleTransitionAuthority executes the transition
THEN status SHALL be updated and a single `LIFECYCLE_TRANSITION` event SHALL be persisted in the same DB transaction.

#### Scenario: Event persistence failure rolls back state transition
GIVEN a valid lifecycle transition request
WHEN status is updated but event insertion fails within the transaction
THEN the entire transaction SHALL roll back
AND the status mutation SHALL NOT be persisted.

#### Scenario: Rejected transition emits no success event
GIVEN an invalid or stale lifecycle transition request
WHEN LifecycleTransitionAuthority rejects the transition
THEN no `LIFECYCLE_TRANSITION` success event SHALL be emitted.

### Requirement: Observations and projections do not mutate lifecycle

Readiness evaluations, discovery checks, queue projections, and read-only GET API requests SHALL NOT directly or indirectly mutate canonical lifecycle state.

#### Scenario: Readiness is side-effect-free
GIVEN readiness evaluates READY
WHEN no transition command is executed
THEN canonical lifecycle SHALL remain unchanged.

#### Scenario: Discovery preserves terminal state and reports contradiction
GIVEN Change status is DONE
AND active OpenSpec files exist on disk
WHEN discovery runs
THEN DONE status SHALL be preserved
AND a blocking contradiction SHALL be reported.

#### Scenario: Queue projection is disposable and rebuildable
GIVEN terminal canonical lifecycle
AND a reconstructed queue projection indicating admission_eligible=true
WHEN admission executes
THEN canonical terminal status SHALL block execution and no new Run or Job SHALL be created.

#### Scenario: Querying status or dashboard produces zero lifecycle writes
GIVEN a read-only request to inspect Change or Backlog status or dashboard
WHEN status projections or response payloads are generated
THEN zero lifecycle transitions or database mutations SHALL be persisted.

### Requirement: Backlog completion is not inferred from filesystem alone

OpenSpec archive presence SHALL be evidence only and SHALL NOT independently transition BacklogItem to COMPLETED.

#### Scenario: OpenSpec archive presence without lifecycle completion event
GIVEN an OpenSpec change exists in the archive folder
AND the corresponding BacklogItem is in IN_PROGRESS state
WHEN discovery or backlog evaluation runs
THEN the BacklogItem SHALL NOT automatically transition to COMPLETED
AND explicit transition via authority SHALL be required.

### Requirement: Explicit read-after-write persistence semantics

Under `autoflush=False`, same-UoW reads requiring updated lifecycle state SHALL use explicit flush at the lifecycle/UoW boundary.

#### Scenario: Same unit of work read-after-write
GIVEN a unit of work with autoflush=False
WHEN a lifecycle state transition is emitted
AND a subsequent query in the same unit of work requires updated state
THEN an explicit flush SHALL occur at the boundary before read.

### Requirement: Recovery and operator actions preserve terminality

Restart recovery and operator actions SHALL use canonical lifecycle rules when touching Change/Backlog state and SHALL NOT reopen terminal canonical work.

#### Scenario: Restart recovery encounters terminal work
GIVEN a Change or BacklogItem in terminal state (DONE, COMPLETED, or CANCELLED)
WHEN daemon restart recovery or operator actions execute
THEN the canonical lifecycle state SHALL remain terminal
AND work SHALL NOT be reopened or transitioned to executable states.

### Requirement: Contradictions fail closed

When canonical lifecycle conflicts with external/projection evidence, terminal canonical state SHALL be preserved, contradiction evidence SHALL be reported, and fresh admission SHALL be blocked.

#### Scenario: Terminal state with conflicting external evidence
GIVEN a Change in DONE status
AND conflicting external evidence indicating active work
WHEN integrity or discovery checks evaluate the item
THEN the terminal state SHALL be preserved
AND a blocking contradiction SHALL be recorded
AND fresh admission SHALL be rejected.
