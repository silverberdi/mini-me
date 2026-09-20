# Design: Canonical Lifecycle Transition Authority

## Principle

`observation/evidence -> transition decision -> canonical state -> projection`

No observation, read-model generation, discovery check, or queue projection directly writes canonical lifecycle state.

## Authority Model: Single Writer vs. Authorized Callers

`LifecycleTransitionAuthority` is the SINGLE WRITER of `Change.status` and `BacklogItem.status`.

Business services act strictly as **authorized callers**:

1. **SchedulerService**: Authorized caller requesting `READY -> ADMITTED` during fresh admission.
2. **OrchestrationService**: Authorized caller requesting `ADMITTED -> RUNNING` when execution confirmedly starts, as well as valid execution outcome transitions (`RUNNING -> NEEDS_HUMAN`, `BLOCKED`, `COMPLETED`, `CANCELLED`).
3. **PostMergeService**: Authorized caller requesting `Change.DONE` and `BacklogItem.COMPLETED` when Stage A post-merge gates pass.
4. **IntakeService**: Authorized caller requesting transitions corresponding to intake commands, including `delete_work_item` requesting `-> CANCELLED`.
5. **ReadinessService & ContextDiscoveryService**: Pure evaluation/discovery services. They DO NOT write lifecycle status; they evaluate readiness or report findings to decision surfaces.
6. **RestartRecoveryService & ControlPlaneService**: Authorized callers for recovery or governed operator override commands.

None of these business services persist `Change.status` or `BacklogItem.status` directly.

### Scope Boundary: Job / Run State Machines

`Job` and `Run` maintain their specialized operational state machines (`JobStatus`, `OrchestrationStage`). Stage A migrates all direct writers of `Change.status` and `BacklogItem.status`, but does NOT rewrite or alter the specialized `Job` / `Run` state machines.

## Persistence Boundary Protection (Bypass Guard)

To ensure future codebase additions cannot bypass `LifecycleTransitionAuthority`:

- `ChangeRepository` and `BacklogItemRepository` `save()` and `update()` methods SHALL inspect if the target entity already exists in PostgreSQL.
- For an existing entity, if generic `save()` or `update()` receives a `status` different from the current durable status in PostgreSQL:
  - It MUST deterministically raise a `LifecycleBypassError`;
  - It MUST perform zero lifecycle mutation;
  - It MUST NOT silently ignore the requested status;
  - It MUST NOT partially persist metadata from that operation (failing the entire transaction so callers cannot believe the write succeeded).
- If incoming `status == durable status`, generic `save()` MAY update legitimate non-lifecycle metadata (e.g., descriptions, timestamps, tags).
- Initial entity creation (`INSERT`) CAN set the entity's initial status (`ChangeStatus.DISCOVERED` or `WorkItemStatus.BACKLOG`).
- All subsequent status mutations MUST be performed strictly via `LifecycleTransitionAuthority.transition_change(...)` or `LifecycleTransitionAuthority.transition_backlog_item(...)`.
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

- `READY -> ADMITTED`: Requested exclusively by `SchedulerService` (as authorized caller) when fresh admission is atomically authorized under concurrency protection.
- `ADMITTED -> RUNNING`: Requested exclusively by `OrchestrationService` (as authorized caller) when active execution confirmedly starts.
- Double writing of `RUNNING` across `SchedulerService` and `IntakeService` is eliminated.

## Non-Destructive Cancellation

- `IntakeService.delete_work_item()` SHALL NOT execute `self.uow.backlog_items.delete(item.item_id)`.
- It SHALL request `LifecycleTransitionAuthority.transition_backlog_item(..., to_state=WorkItemStatus.CANCELLED)`.
- The `BacklogItem` row, identity, history, links, and audit evidence SHALL be preserved in PostgreSQL.
- Hard DB deletion / purging is removed from normal SDLC lifecycle operations.

## PostMergeService Authority Integration

- `PostMergeService._reconcile_change_and_backlog_item()` SHALL request `Change.status = ChangeStatus.DONE` and `BacklogItem.status = WorkItemStatus.COMPLETED` transitions via `LifecycleTransitionAuthority`.
- Existing verification gates in `PostMergeService` remain temporary input gates for Stage A.

## Orthogonality of Readiness and Completion

- Completing a `BacklogItem` (`COMPLETED`) SHALL NOT update or overwrite `readiness_state` to `ReadinessState.READY`.
- `readiness_state` remains an evaluation output representing readiness/admissibility checks. Lifecycle terminal state does not alter readiness history.

## UNKNOWN Evaluation Semantics

- When an evaluation cannot observe required evidence, the evaluation outcome is explicitly `UNKNOWN`.
- `UNKNOWN` fails closed: it SHALL NEVER authorize `READY`, `ADMITTED`, `RUNNING`, `DONE`, or `COMPLETED`.
- `NOT_READY` SHALL NOT be used as a silent alias for `UNKNOWN`.
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
- Transactional coupling: if transition event insertion fails, the status mutation SHALL roll back in the same transaction.
- Rejected or stale transition requests (CAS failure = 0 rows) SHALL NOT emit a success transition event.
- Retries of failed or stale requests SHALL NOT produce phantom transition events.

## Readiness, Discovery, and GET Purity

- `ReadinessService.evaluate()` produces a pure evaluation result without mutating `Change.status` or `BacklogItem.status`.
- `DiscoveryService` updates discovery metadata without reactivating terminal `DONE` or `COMPLETED` work.
- Rebuilding `WorkQueueItem` projections creates zero lifecycle state changes.
- GET endpoints in `DashboardService`, `StatusService`, and `api/app.py` perform zero lifecycle mutations.

## Unit of Work & Explicit Flush

- Under `autoflush=False`, any same-UoW read requiring updated lifecycle visibility following a transition command SHALL trigger an explicit flush at the boundary.

## Concurrency & Atomic Admission

- Fresh admission uses atomic CAS SQL primitives on PostgreSQL:
  `UPDATE backlog_items SET status = 'ADMITTED' WHERE id = :id AND status = 'READY'`
- When two concurrent scheduler workers attempt admission on the same item, exactly one succeeds and the other receives a deterministic `STALE_STATE` / `TRANSITION_CONFLICT` refusal.
