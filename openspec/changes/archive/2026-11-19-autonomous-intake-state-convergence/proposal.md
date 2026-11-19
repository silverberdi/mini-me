# Proposal: Autonomous Intake Persisted State Convergence

## Summary
Introduce deterministic backlog item lifecycle convergence prior to autonomous intake sweep in the scheduler loop to prevent stale `READY` states from permanently stranding work.

## Problem
Production backlog items sitting in state `status = READY` with `readiness_state = NOT_READY` (such as when active OpenSpec change directories disappear or are archived) fall into a dead zone:
1. `IntakeService.sweep_unprepared_backlog_items()` only inspects items in `{BACKLOG, CONTEXT_CHECK, PREPARING}`, so stale `READY` items are never swept.
2. `SchedulerService.evaluate_admission()` requires `readiness_state == READY` and valid active OpenSpec change bindings, so stale `READY` items are refused.
3. `DiscoveryService.discover_work()` only scans active OpenSpec change directories on disk, so missing or archived changes produce no new queue items.

As a result, stale `READY` items remain permanently stranded without progressing or converging.

## Proposed Solution
1. **Lifecycle Matrix Extension**: Explicitly allow `WorkItemStatus.READY` -> `WorkItemStatus.COMPLETED` in `ALLOWED_WORK_ITEM_TRANSITIONS` within `LifecycleTransitionAuthority` to permit convergence of delivered/archived work.
2. **Backlog Lifecycle Convergence**: Implement `IntakeService.reconcile_and_persist_backlog_items()` which evaluates present evidence (archived changes, completed runs, `ChangeStatus.DONE`, `ChangeStatus.CANCELLED`, missing readiness artifacts) and persists transitions atomically through `LifecycleTransitionAuthority`.
3. **Scheduler Tick Ordering**: Insert backlog lifecycle convergence into `SchedulerService.tick()` immediately before autonomous intake sweep, ensuring intake operates on converged backlog truth.
4. **Stale READY Convergence**: Stale `READY` items with missing artifacts or unmet readiness converge to `BLOCKED`. Eligible `BLOCKED` items can then transition `BLOCKED` -> `PREPARING` and be re-evaluated cleanly during autonomous intake sweep.
