# Proposal: Canonical Lifecycle Transition Authority

## Problem Statement

mini me has multiple representations of lifecycle state (`Change`, `BacklogItem`, `WorkQueueItem`,
`OrchestrationRun`, `Job`, GitHub, OpenSpec, events). Several services directly mutate `Change.status` and
`BacklogItem.status` using generic repository `save()` calls, model copies, or local reconciliation logic.
As a result, observations and projections can act as de-facto writers, completed or cancelled work can become
rediscoverable or readmissible, and generic persistence calls can bypass lifecycle transition governance.

## Proposed Change

Introduce one canonical transition authority (`LifecycleTransitionAuthority`) for `Change` and `BacklogItem`
lifecycle using the existing domain enums. Do not introduce a duplicate monolithic state machine.

The change SHALL:
1. enforce persistence-level bypass protection so generic repository `save()` and model update methods on existing entities explicitly block direct status mutations;
2. perform status transitions exclusively via `LifecycleTransitionAuthority` using atomic compare-and-set (CAS) SQL primitives (`UPDATE ... WHERE id = :id AND status = :expected`) expecting exactly 1 affected row;
3. enforce the exact `ChangeStatus` transition matrix (`DISCOVERED`, `READY`, `IN_PROGRESS`, `BLOCKED`, `DONE`, `CANCELLED`);
4. enforce the exact `WorkItemStatus` transition matrix (`BACKLOG`, `CONTEXT_CHECK`, `PREPARING`, `NEEDS_HUMAN`, `READY`, `ADMITTED`, `RUNNING`, `BLOCKED`, `COMPLETED`, `CANCELLED`);
5. treat terminal states (`Change.DONE`, `Change.CANCELLED`, `BacklogItem.COMPLETED`, `BacklogItem.CANCELLED`) as monotonic and non-reactivatable;
6. establish clear phase separation between `READY -> ADMITTED` (atomic fresh admission gate in `SchedulerService`) and `ADMITTED -> RUNNING` (confirmed execution start in `OrchestrationService`);
7. convert item deletion (`IntakeService.delete_work_item`) into non-destructive transition to `CANCELLED`, preserving row identity, history, links, and audit evidence;
8. route `PostMergeService` state changes (`Change.DONE`, `BacklogItem.COMPLETED`) strictly through `LifecycleTransitionAuthority`;
9. enforce orthogonality between completion and readiness: terminal completion SHALL NOT overwrite or fabricate `readiness_state = READY`;
10. enforce `UNKNOWN` evaluation state semantics: missing or unobservable evidence yields `UNKNOWN`, which fails closed and blocks state progression;
11. persist exactly one durable lifecycle transition event within the same database transaction as the state mutation;
12. ensure readiness evaluations, discovery checks, queue rebuilds, and GET API endpoints are strictly side-effect-free with respect to lifecycle.

## Acceptance Criteria

- Generic `repository.save()` or `model_copy()` attempts to alter status on existing `Change` or `BacklogItem` entities fail deterministically or preserve durable status.
- `Change.DONE/CANCELLED` and `BacklogItem.COMPLETED/CANCELLED` cannot transition to executable states under any discovery, intake, recovery, or operator scenario.
- `ChangeStatus` transitions strictly obey the explicit matrix (`DISCOVERED`, `READY`, `IN_PROGRESS`, `BLOCKED`, `DONE`, `CANCELLED`).
- `WorkItemStatus` transitions strictly obey the explicit matrix (`BACKLOG`, `CONTEXT_CHECK`, `PREPARING`, `NEEDS_HUMAN`, `READY`, `ADMITTED`, `RUNNING`, `BLOCKED`, `COMPLETED`, `CANCELLED`).
- `SchedulerService` atomically executes `READY -> ADMITTED`; `OrchestrationService` executes `ADMITTED -> RUNNING`; no redundant double writers of `RUNNING` exist.
- `delete_work_item()` transitions BacklogItem status to `CANCELLED` without hard DB deletion, keeping row identity durable.
- `PostMergeService` executes `Change.DONE` and `BacklogItem.COMPLETED` transitions via `LifecycleTransitionAuthority`.
- Completing a BacklogItem preserves its actual `readiness_state` without forcing `readiness_state = READY`.
- Unobservable evidence evaluates as `UNKNOWN` and blocks transition to `READY`, `ADMITTED`, `RUNNING`, `DONE`, or `COMPLETED`.
- Successful state transition atomically inserts a single transition event in the same DB transaction; rejected/stale transitions emit zero success events.
- Concurrent fresh admission attempts yield at most one `READY -> ADMITTED` transition and at most one active Run/Job.
- Readiness evaluation, discovery checks, queue rebuilds, and GET/read API endpoints perform zero lifecycle writes.
