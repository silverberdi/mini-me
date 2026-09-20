# Spec: Canonical Lifecycle Transition Authority

## ADDED Requirements

### Requirement: Single canonical lifecycle transition authority

The system SHALL provide one canonical authority for durable Change and BacklogItem lifecycle
transitions and SHALL use the existing lifecycle enums rather than introduce a duplicate monolithic
state machine.

#### Scenario: Stale transition request
GIVEN a request expects READY
AND durable state is IN_PROGRESS
WHEN transition is evaluated
THEN it SHALL be rejected as stale
AND no lifecycle mutation SHALL occur.

### Requirement: Monotonic terminal lifecycle

The system SHALL treat Change.DONE, Change.CANCELLED, BacklogItem.COMPLETED, and
BacklogItem.CANCELLED as terminal for their existing identity.

#### Scenario: Completed Change cannot become READY
GIVEN Change is DONE
WHEN any discovery, readiness, scheduler, recovery, intake, or operator path requests READY
THEN the transition SHALL be rejected
AND Change SHALL remain DONE.

### Requirement: Observations do not directly mutate lifecycle

Readiness, discovery, integrity, filesystem, GitHub, queue reconstruction, and read-model generation
SHALL produce observations/evaluations/projections and SHALL NOT directly regress canonical lifecycle.

#### Scenario: Readiness is side-effect-free
GIVEN readiness evaluates READY
WHEN no transition command is executed
THEN canonical lifecycle SHALL remain unchanged.

#### Scenario: Active OpenSpec contradicts terminal state
GIVEN Change is DONE
AND active OpenSpec exists
WHEN discovery/integrity runs
THEN DONE SHALL be preserved
AND a blocking contradiction SHALL be reported
AND no admission-eligible execution SHALL be created.

### Requirement: Queue is a disposable projection

WorkQueueItem SHALL be rebuildable without lifecycle mutation and canonical lifecycle SHALL be
revalidated before every fresh admission.

#### Scenario: Corrupted queue cannot admit terminal work
GIVEN terminal canonical lifecycle
AND queue says admission_eligible=true
WHEN admission executes
THEN no new Run or Job SHALL be created.

### Requirement: Backlog completion is not inferred from filesystem alone

OpenSpec archive presence SHALL be evidence only and SHALL NOT independently transition BacklogItem
to COMPLETED.

#### Scenario: OpenSpec archive presence without lifecycle completion event
GIVEN an OpenSpec change exists in the archive folder
AND the corresponding BacklogItem is in IN_PROGRESS state
WHEN discovery or backlog evaluation runs
THEN the BacklogItem SHALL NOT automatically transition to COMPLETED
AND explicit transition via authority SHALL be required.

### Requirement: Fresh admission is lifecycle-atomic

Fresh admission SHALL require canonical READY state and SHALL atomically authorize admission so
concurrent attempts cannot create duplicate active execution.

#### Scenario: Concurrent admission
GIVEN READY work with no active run
WHEN two scheduler processes admit concurrently
THEN at most one SHALL succeed
AND at most one active Run/Job SHALL exist.

### Requirement: Explicit read-after-write persistence semantics

Under `autoflush=False`, same-UoW reads requiring updated lifecycle state SHALL use explicit flush at
the lifecycle/UoW boundary and SHALL NOT rely on implicit autoflush.

#### Scenario: Same unit of work read-after-write
GIVEN a unit of work with autoflush=False
WHEN a lifecycle state transition is emitted
AND a subsequent query in the same unit of work requires updated state
THEN an explicit flush SHALL occur at the boundary before read.

### Requirement: Pure read surfaces do not perform lifecycle writes

Read-only API/service operations SHALL NOT persist Change/Backlog lifecycle transitions merely
because status/readiness/queue/dashboard/backlog was read.

#### Scenario: Querying status or dashboard
GIVEN a read-only request to inspect Change or Backlog status
WHEN status or queue projections are generated
THEN zero lifecycle transitions or database mutations SHALL be persisted.

### Requirement: Recovery and operator actions preserve terminality

Restart recovery and operator actions SHALL use canonical lifecycle rules when touching
Change/Backlog state and SHALL NOT reopen terminal canonical work.

#### Scenario: Restart recovery encounters terminal work
GIVEN a Change or BacklogItem in terminal state (DONE, COMPLETED, or CANCELLED)
WHEN daemon restart recovery or operator actions execute
THEN the canonical lifecycle state SHALL remain terminal
AND work SHALL NOT be reopened or transitioned to executable states.

### Requirement: Contradictions fail closed

When canonical lifecycle conflicts with external/projection evidence, terminal canonical state SHALL
be preserved, contradiction evidence SHALL be reported, and fresh admission SHALL be blocked.
UNKNOWN SHALL remain blocking when required evidence cannot be observed.

#### Scenario: Terminal state with conflicting external evidence
GIVEN a Change in DONE status
AND conflicting external evidence indicating active work
WHEN integrity or discovery checks evaluate the item
THEN the terminal state SHALL be preserved
AND a blocking contradiction SHALL be recorded
AND fresh admission SHALL be rejected.
