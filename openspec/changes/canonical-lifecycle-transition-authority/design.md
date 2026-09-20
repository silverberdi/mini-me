# Design: Canonical Lifecycle Transition Authority

## Principle

`observation/evidence -> transition decision -> canonical state -> projection`

No observation, read-model generation, discovery check, or queue projection directly writes canonical lifecycle state.

## Current Writers Inventory (Audited)

Direct status writers in current codebase identified for migration to `LifecycleTransitionAuthority`:

1. **ReadinessService**: Mutates `change_record.status = ChangeStatus.READY` or `DISCOVERED` during evaluation.
2. **ContextDiscoveryService / DiscoveryService**: Mutates `BacklogItem.status` (`BACKLOG`, `COMPLETED`, `READY`, `BLOCKED`) and `Change.status` during discovery scans and archive checks.
3. **IntakeService**: Mutates `BacklogItem.status` across multiple states and executes physical row deletion in `delete_work_item()`.
4. **SchedulerService**: Mutates `BacklogItem.status = RUNNING` directly upon admission.
5. **PostMergeService**: Mutates `Change.status = ChangeStatus.DONE`, `BacklogItem.status = WorkItemStatus.COMPLETED`, and forces `readiness_state = ReadinessState.READY` inside `_reconcile_change_and_backlog_item()`.
6. **OrchestrationService / ExecutionPipeline**: Mutates `WorkItemStatus` and `ChangeStatus` directly during execution stages.
7. **RestartRecoveryService & ControlPlaneService**: Mutate state during process restart or manual operator overrides.

All of the above direct status assignment paths SHALL be refactored to route exclusively through `LifecycleTransitionAuthority`.

## Persistence Boundary Protection (Bypass Guard)

To ensure future codebase additions cannot bypass `LifecycleTransitionAuthority`:

- `ChangeRepository` and `BacklogItemRepository` `save()` methods SHALL check if the target entity already exists in the database.
- For existing entities, generic `save()` or `update()` methods SHALL block modifications to `status` (either raising a deterministic `LifecycleBypassError` or ignoring status mutations in generic save).
- Initial entity creation (`INSERT`) SHALL set the entity's initial status (`ChangeStatus.DISCOVERED` or `WorkItemStatus.BACKLOG`).
- All subsequent status mutations SHALL be performed strictly via `LifecycleTransitionAuthority.transition_change(...)` or `LifecycleTransitionAuthority.transition_backlog_item(...)`.
- `LifecycleTransitionAuthority` SHALL execute an atomic compare-and-set (CAS) SQL primitive:
  ```sql
  UPDATE {table}
  SET status = :target_status, updated_at = :now
  WHERE id = :id AND status = :expected_status
  ```
- The authority SHALL verify that exactly 1 row was affected. If 0 rows were affected, the transition SHALL be rejected with `STALE_STATE` / `TRANSITION_CONFLICT`. Last-write-wins is forbidden.

## Exact ChangeStatus Matrix

- `DISCOVERED` -> `READY`, `BLOCKED`, `CANCELLED`
- `READY` -> `IN_PROGRESS`, `BLOCKED`, `CANCELLED`
- `IN_PROGRESS` -> `BLOCKED`, `DONE`, `CANCELLED`
- `BLOCKED` -> `READY`, `IN_PROGRESS`, `CANCELLED`
- `DONE` -> none (Terminal)
- `CANCELLED` -> none (Terminal)

`DONE` and `CANCELLED` are strictly monotonic and terminal. No administrative or recovery bypass may reactivate them.

## Exact WorkItemStatus Matrix

- `BACKLOG` -> `CONTEXT_CHECK`, `PREPARING`, `CANCELLED`
- `CONTEXT_CHECK` -> `PREPARING`, `NEEDS_HUMAN`, `BLOCKED`, `CANCELLED`
- `PREPARING` -> `NEEDS_HUMAN`, `READY`, `BLOCKED`, `CANCELLED`
- `NEEDS_HUMAN` -> `PREPARING`, `BLOCKED`, `CANCELLED`
- `READY` -> `ADMITTED`, `NEEDS_HUMAN`, `BLOCKED`, `CANCELLED`
- `ADMITTED` -> `RUNNING`, `NEEDS_HUMAN`, `BLOCKED`, `CANCELLED`
- `RUNNING` -> `NEEDS_HUMAN`, `BLOCKED`, `COMPLETED`, `CANCELLED`
- `BLOCKED` -> `PREPARING`, `READY`, `NEEDS_HUMAN`, `CANCELLED`
- `COMPLETED` -> none (Terminal)
- `CANCELLED` -> none (Terminal)

`COMPLETED` and `CANCELLED` are strictly monotonic and terminal.

## Phase Separation: ADMITTED vs. RUNNING

- `READY -> ADMITTED`: Executed exclusively by `SchedulerService` / admission authority when fresh admission is atomically authorized under concurrency protection.
- `ADMITTED -> RUNNING`: Executed exclusively by `OrchestrationService` / execution engine when active execution confirmedly starts.
- Double writing of `RUNNING` across `SchedulerService` and `IntakeService` is eliminated.

## Non-Destructive Cancellation

- `IntakeService.delete_work_item()` SHALL NOT execute `self.uow.backlog_items.delete(item.item_id)`.
- It SHALL execute `LifecycleTransitionAuthority.transition_backlog_item(..., to_state=WorkItemStatus.CANCELLED)`.
- The `BacklogItem` row, identity, history, links, and audit evidence SHALL be preserved in PostgreSQL.
- Hard DB deletion / purging is removed from normal SDLC lifecycle operations.

## PostMergeService Authority Integration

- `PostMergeService._reconcile_change_and_backlog_item()` SHALL route `Change.status = ChangeStatus.DONE` and `BacklogItem.status = WorkItemStatus.COMPLETED` transitions via `LifecycleTransitionAuthority`.
- Existing verification gates in `PostMergeService` remain temporary input gates for Stage A.

## Orthogonality of Readiness and Completion

- Completing a `BacklogItem` (`COMPLETED`) SHALL NOT update or overwrite `readiness_state` to `ReadinessState.READY`.
- `readiness_state` remains an evaluation output representing readiness/admissibility checks. Lifecycle terminal state does not alter readiness history.

## UNKNOWN Evaluation Semantics

- When an evaluation cannot observe required evidence, the evaluation result is explicitly `UNKNOWN`.
- `UNKNOWN` fails closed: it SHALL NOT authorize `READY`, `ADMITTED`, `RUNNING`, `DONE`, or `COMPLETED`.
- `UNKNOWN` generates a blocking decision or integrity finding according to caller context.

## Atomic Lifecycle Transition Audit Event

- Every successful lifecycle transition SHALL produce exactly one durable transition event within the SAME database transaction unit of work as the state mutation.
- Event structure:
  - `event_type`: `LIFECYCLE_TRANSITION`
  - `aggregate_type`: `"Change"` | `"BacklogItem"`
  - `aggregate_id`: string ID of entity
  - `project_id`: project string ID
  - `change_name` / `item_key`: string key
  - `from_state`: string representation of prior status
  - `to_state`: string representation of target status
  - `reason_code`: string code explaining transition rationale
  - `actor` / `source`: caller identity
  - `correlation_id` / `operation_id`: request context ID
  - `evidence_references`: list/dict of evidence IDs or SHAs
  - `timestamp`: UTC timestamp
- Rejected or stale transition requests SHALL NOT emit a success transition event.

## Readiness, Discovery, and GET Purity

- `ReadinessService.evaluate()` produces a pure `ReadinessEvaluationResult` without mutating `Change.status` or `BacklogItem.status`.
- `DiscoveryService` updates discovery metadata without reactivating terminal `DONE` or `COMPLETED` work.
- Rebuilding `WorkQueueItem` projections creates zero lifecycle state changes.
- GET endpoints in `DashboardService`, `StatusService`, and `api/app.py` perform zero lifecycle mutations.

## Unit of Work & Explicit Flush

- Under `autoflush=False`, any same-UoW read requiring updated lifecycle visibility following a transition command SHALL trigger an explicit flush at the boundary.

## Concurrency & Atomic Admission

- Fresh admission uses atomic CAS SQL primitives on PostgreSQL:
  `UPDATE backlog_items SET status = 'ADMITTED' WHERE id = :id AND status = 'READY'`
- When two concurrent scheduler workers attempt admission on the same item, exactly one succeeds and the other receives a deterministic `STALE_STATE` / `TRANSITION_CONFLICT` refusal.
