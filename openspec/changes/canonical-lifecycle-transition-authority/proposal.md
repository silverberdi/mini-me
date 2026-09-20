# Proposal: Canonical Lifecycle Transition Authority

## Problem Statement

mini me has multiple representations of lifecycle state (`Change`, `BacklogItem`, `WorkQueueItem`,
`OrchestrationRun`, `Job`, GitHub, OpenSpec, events). Several services both observe and mutate
lifecycle, so observations/projections can become de-facto writers and completed work can become
rediscoverable/admissible.

## Proposed Change

Introduce one canonical transition authority for `Change` and `BacklogItem` lifecycle using the
existing enums. Do not introduce a duplicate monolithic lifecycle state machine.

The change SHALL:
1. define explicit allowed transitions;
2. make terminal states monotonic;
3. use expected-state/compare-and-set transition semantics;
4. persist transition evidence atomically;
5. define explicit flush semantics under `autoflush=False`;
6. make readiness evaluation lifecycle side-effect-free;
7. prevent discovery/queue projections from resurrecting terminal work;
8. prevent backlog completion from being inferred from filesystem alone;
9. require canonical non-terminal lifecycle before fresh admission;
10. route relevant recovery/control-plane Change/Backlog writes through the same authority;
11. report contradictions instead of silently regressing/repairing state;
12. add adversarial invariant tests.

## Acceptance Criteria

- `Change.DONE/CANCELLED` cannot transition to executable states.
- `BacklogItem.COMPLETED/CANCELLED` cannot transition to executable states.
- readiness evaluation alone never changes lifecycle.
- repeated discovery cannot resurrect terminal work.
- terminal + active OpenSpec/open Issue blocks admission and records contradiction.
- queue rebuild cannot change lifecycle.
- stale expected-state transition is rejected.
- concurrent fresh admission yields at most one active Run/Job.
- affected GET/read surfaces produce zero lifecycle writes.
- explicit flush makes same-UoW read-after-write deterministic.
