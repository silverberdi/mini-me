# Design: Autonomous Intake Persisted State Convergence

## Architecture & Design Decisions

### 1. WorkItem Lifecycle Transition Matrix Extension
In `LifecycleTransitionAuthority` (`src/minime/services/lifecycle_transition_authority.py`):
Extend `ALLOWED_WORK_ITEM_TRANSITIONS[WorkItemStatus.READY]` to include `WorkItemStatus.COMPLETED`:
```python
    WorkItemStatus.READY: {
        WorkItemStatus.ADMITTED,
        WorkItemStatus.NEEDS_HUMAN,
        WorkItemStatus.BLOCKED,
        WorkItemStatus.CANCELLED,
        WorkItemStatus.COMPLETED,
    },
```
This enables direct, atomic convergence of `READY` backlog items to `COMPLETED` when evidence demonstrates that the change is archived or completed.

### 2. Backlog Lifecycle Convergence Authority
In `IntakeService` (`src/minime/services/intake_service.py`):
Implement `reconcile_and_persist_backlog_items(project_id: str | None = None) -> list[BacklogItem]`:
- Iterates backlog items for the given project(s).
- Checks terminal status (skips already `COMPLETED` or `CANCELLED` items).
- Inspects disk archive directories (`openspec/changes/archive/`), `Change` table records, and `OrchestrationRun` history.
- Performs atomic CAS state transitions through `LifecycleTransitionAuthority` to update persisted DB rows and emit `LIFECYCLE_TRANSITION` events:
  - Archive / DONE / Completed Run -> `COMPLETED`
  - Cancelled Change / Cancelled Run -> `CANCELLED`
  - Stale `READY` (missing active directory or `readiness_state != READY`) -> `BLOCKED`

### 3. Intake Sweep Integration
In `IntakeService.sweep_unprepared_backlog_items()`:
- Include `WorkItemStatus.BLOCKED` items in the sweep set if they meet roadmap/source eligibility.
- Transition eligible `BLOCKED` items to `WorkItemStatus.PREPARING` via `LifecycleTransitionAuthority` before calling `prepare_work_item()`.

### 4. Scheduler Execution Ordering
In `SchedulerService.tick()` (`src/minime/services/scheduler_service.py`):
Revise tick step sequence:
1. `0.0` Provider health probe
2. `0.01` Recovery convergence cycle (`recovery_convergence_service.reconcile_cycle()`)
3. `0.02` Backlog lifecycle convergence (`intake_service.reconcile_and_persist_backlog_items()`)
4. `0.1` Autonomous intake sweep (`intake_service.sweep_unprepared_backlog_items()`)
5. `1.0` Work discovery (`discovery_service.discover_work()`)
6. `2.0 - 4.0` Ranking and admission evaluation
