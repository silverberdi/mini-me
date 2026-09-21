# Proposal: Canonical Lifecycle Transition Authority

## Problem Statement

mini me has multiple representations of lifecycle state (`Change`, `BacklogItem`, `WorkQueueItem`,
`OrchestrationRun`, `Job`, GitHub, OpenSpec, events). Several services directly mutate `Change.status` and
`BacklogItem.status` using generic repository `save()` calls, model copies, or local reconciliation logic.
As a result, observations and projections can act as de-facto writers, completed or cancelled work can become
rediscoverable or readmissible, and generic persistence calls can bypass lifecycle transition governance.

## Proposed Change

Establish `LifecycleTransitionAuthority` as the SINGLE WRITER of `Change.status` and `BacklogItem.status` using existing domain enums.
Business services (`SchedulerService`, `OrchestrationService`, `PostMergeService`, `IntakeService`, recovery, control plane) become authorized callers requesting transitions through `LifecycleTransitionAuthority` instead of persisting status directly.

The change SHALL:
1. enforce persistence-level bypass protection: for existing `Change` or `BacklogItem` entities, if a generic repository `save()` or `update()` call receives a `status` different from the current durable status in PostgreSQL, it MUST deterministically raise a `LifecycleBypassError`, MUST perform zero lifecycle mutation, MUST NOT silently ignore the requested status, and MUST NOT partially persist metadata from that operation;
2. permit generic `save()` to update non-lifecycle metadata when incoming `status == durable status`, and permit initial `INSERT` to set initial entity status (`DISCOVERED` or `BACKLOG`);
3. perform status transitions exclusively via `LifecycleTransitionAuthority` using atomic compare-and-set (CAS) SQL primitives (`UPDATE ... WHERE id = :id AND status = :expected`) expecting exactly 1 affected row;
4. enforce the exact `ChangeStatus` transition matrix (`DISCOVERED`, `READY`, `IN_PROGRESS`, `BLOCKED`, `DONE`, `CANCELLED`);
5. enforce the exact `WorkItemStatus` transition matrix (`BACKLOG`, `CONTEXT_CHECK`, `PREPARING`, `NEEDS_HUMAN`, `READY`, `ADMITTED`, `RUNNING`, `BLOCKED`, `COMPLETED`, `CANCELLED`);
6. treat terminal states (`Change.DONE`, `Change.CANCELLED`, `BacklogItem.COMPLETED`, `BacklogItem.CANCELLED`) as monotonic and non-reactivatable;
7. establish clear phase separation between `READY -> ADMITTED` (authorized exclusively by `SchedulerService` during fresh admission) and `ADMITTED -> RUNNING` (authorized by `OrchestrationService` upon confirmed execution start);
8. convert item deletion (`IntakeService.delete_work_item`) into a non-destructive request to transition to `CANCELLED`, preserving row identity, history, links, and audit evidence;
9. route `PostMergeService` state changes (`Change.DONE`, `BacklogItem.COMPLETED`) strictly through `LifecycleTransitionAuthority`;
10. enforce orthogonality between completion and readiness: terminal completion SHALL NOT overwrite or fabricate `readiness_state = READY`;
11. enforce `UNKNOWN` evaluation outcome semantics: missing or unobservable evidence yields `UNKNOWN`, which fails closed and NEVER authorizes `READY`, `ADMITTED`, `RUNNING`, `DONE`, or `COMPLETED`;
12. persist exactly one durable lifecycle transition event within the same database transaction as the state mutation, rolling back the state transition if event persistence fails;
13. preserve the specialized state machines for `Job` and `Run` while migrating all direct writers of `Change.status` and `BacklogItem.status`.

## Acceptance Criteria

- Any attempt to alter status on existing `Change` or `BacklogItem` entities via generic `repository.save()` raises a `LifecycleBypassError`, preserves durable status, and persists zero metadata or event changes.
- `LifecycleTransitionAuthority` is the single writer of `Change.status` and `BacklogItem.status`; business services interact solely as authorized callers.
- `Change.DONE/CANCELLED` and `BacklogItem.COMPLETED/CANCELLED` cannot transition to executable states under any discovery, intake, recovery, or operator scenario.
- `ChangeStatus` transitions strictly obey the explicit matrix (`DISCOVERED`, `READY`, `IN_PROGRESS`, `BLOCKED`, `DONE`, `CANCELLED`).
- `WorkItemStatus` transitions strictly obey the explicit matrix (`BACKLOG`, `CONTEXT_CHECK`, `PREPARING`, `NEEDS_HUMAN`, `READY`, `ADMITTED`, `RUNNING`, `BLOCKED`, `COMPLETED`, `CANCELLED`).
- `SchedulerService` acts as authorized caller for `READY -> ADMITTED`; `OrchestrationService` acts as authorized caller for `ADMITTED -> RUNNING`.
- `delete_work_item()` requests transition to `CANCELLED` without hard DB deletion, keeping row identity durable.
- `PostMergeService` requests `Change.DONE` and `BacklogItem.COMPLETED` transitions via `LifecycleTransitionAuthority`.
- Completing a BacklogItem preserves its actual `readiness_state` without forcing `readiness_state = READY`.
- Unobservable evidence evaluates as `UNKNOWN` and blocks transition to `READY`, `ADMITTED`, `RUNNING`, `DONE`, or `COMPLETED`.
- Successful state transition atomically inserts a single transition event in the same DB transaction; failed or stale requests emit zero transition events.
- Specialized `Job` and `Run` state machines remain intact.
