# Tasks: Canonical Lifecycle Transition Authority

1. Define Change and WorkItem exact transition matrices and terminal-state invariant tests.
2. Implement persistence-level bypass protection in `ChangeRepository` and `BacklogItemRepository` raising `LifecycleBypassError` on generic `save()` attempting status mutation on existing entities.
3. Implement `LifecycleTransitionAuthority` as single transition authority for `Change.status` and `BacklogItem.status`.
4. Implement atomic compare-and-set (CAS) SQL primitive and atomic transition audit event emission in the same DB transaction with full rollback.
5. Centralize explicit flush / read-after-write behavior under `autoflush=False`.
6. Make readiness lifecycle side-effect-free (`ReadinessService.evaluate()` produces pure evaluation without status mutation).
7. Prevent discovery from resurrecting terminal work; emit blocking contradiction.
8. Refactor intake transitions (`IntakeService`) including `NEEDS_HUMAN`/`PREPARING`/`CANCELLED` and make `delete_work_item()` non-destructive (`CANCELLED` transition without row deletion).
9. Refactor scheduler admission (`SchedulerService`) as authorized caller for atomic `READY -> ADMITTED` authorization.
10. Refactor execution start (`OrchestrationService`) as authorized caller for `ADMITTED -> RUNNING` transition without duplicate writers.
11. Route post-merge completion (`PostMergeService._reconcile_change_and_backlog_item()`) for `DONE` and `COMPLETED` strictly through `LifecycleTransitionAuthority`.
12. Ensure recovery and control-plane actions (`RestartRecoveryService`, `ControlPlaneService`) route state updates through authority as authorized callers.
13. Ensure backlog and read projections retain orthogonality of completion and readiness (do not force `readiness_state = READY` on `COMPLETED`).
14. Prove API GET and read surfaces (`DashboardService`, `StatusService`, `api/app.py`) produce zero lifecycle transitions.
15. Add adversarial and concurrency tests (generic save `LifecycleBypassError`, atomic rollback on event failure, stale state, concurrent admission, cancelled item durability, read-only GETs, terminal non-resurrection).
16. Execute exhaustive direct-writer audit in `src/` proving no unmigrated `Change`/`Backlog` lifecycle writer remains (search `.status =`, `model_copy(update={"status": ...})`, `changes.save(...)`, `backlog_items.save(...)`).
17. Run Ruff, focused tests, full pytest, strict OpenSpec validation, and candidate-bound review evidence.

Do not implement Program B–J opportunistically.
