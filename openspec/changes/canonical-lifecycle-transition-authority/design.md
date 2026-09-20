# Design: Canonical Lifecycle Transition Authority

## Principle

`observation/evidence -> transition decision -> canonical state -> projection`

No observation or projection writes canonical lifecycle directly.

## ChangeStatus

Existing states:
`DISCOVERED, READY, IN_PROGRESS, BLOCKED, DONE, CANCELLED`

Terminal:
`DONE, CANCELLED`

Allowed:
- DISCOVERED -> READY | BLOCKED | CANCELLED
- READY -> IN_PROGRESS | BLOCKED | CANCELLED
- IN_PROGRESS -> BLOCKED | DONE | CANCELLED
- BLOCKED -> READY | IN_PROGRESS | CANCELLED
- DONE -> none
- CANCELLED -> none

## WorkItemStatus

Existing states are retained. `COMPLETED` and `CANCELLED` are terminal. The implementation must
derive the complete transition matrix from current behavior while preserving:
- no terminal-to-nonterminal transition;
- admission only through canonical READY -> ADMITTED authorization;
- no projection/discovery/readiness ownership of lifecycle.

## LifecycleTransitionAuthority

Responsibilities:
- validate current state;
- validate target transition;
- validate expected-state/version;
- validate required evidence;
- persist state and transition evidence atomically;
- explicitly flush when same-UoW visibility is required.

It does NOT discover work, rank queue, call providers, mutate GitHub/OpenSpec, or repair integrity.

## Readiness

Readiness becomes a pure evaluation result. It may report READY/NOT_READY/BLOCKED plus reasons and
evidence refs, but it does not assign Change/Backlog status or commit lifecycle state.

## Discovery

Discovery may observe OpenSpec/GitHub and refresh discovery/projection metadata. Before admission,
canonical lifecycle is checked. Terminal state plus active external evidence yields a blocking
integrity contradiction, not reactivation.

## Queue

WorkQueueItem is disposable. Rebuilding it does not change lifecycle. `admission_eligible` is never
sufficient authority to create a Run.

## Admission

Fresh admission:
1. load canonical lifecycle under concurrency protection;
2. reject terminal/integrity-conflicted work;
3. evaluate existing prerequisites;
4. atomically authorize READY -> ADMITTED;
5. create at most one active Run/Job;
6. persist decision evidence.

## UoW

`autoflush=False` may remain. `save()` does not imply query visibility. Explicit flush is centralized
at lifecycle/UoW boundaries when same-transaction reads require new state.

## Migration

Strangler sequence:
1. transition authority + matrix tests;
2. terminal regression guard;
3. route readiness-driven transitions;
4. route intake/backlog transitions;
5. harden discovery/queue;
6. harden fresh admission;
7. route relevant recovery/control-plane writes;
8. prevent direct lifecycle writes in migrated surfaces;
9. remove legacy direct-write paths after parity.

No phase may leave two contradictory writers active.
