# Tasks: Canonical Lifecycle Transition Authority

- [x] 1. Define Change and WorkItem exact transition matrices and terminal-state invariant tests.
- [x] 2. Implement persistence-level bypass protection in `ChangeRepository` and `BacklogItemRepository` raising `LifecycleBypassError` on generic `save()` attempting status mutation on existing entities.
- [x] 3. Implement `LifecycleTransitionAuthority` as single transition authority for `Change.status` and `BacklogItem.status`.
- [x] 4. Implement atomic compare-and-set (CAS) SQL primitive and atomic transition audit event emission in the same DB transaction with full rollback.
- [x] 5. Centralize explicit flush / read-after-write behavior under `autoflush=False`.
- [x] 6. Make readiness lifecycle side-effect-free (`ReadinessService.evaluate()` produces pure evaluation without status mutation).
- [x] 7. Prevent discovery from resurrecting terminal work; emit blocking contradiction.
- [x] 8. Refactor intake transitions (`IntakeService`) including `NEEDS_HUMAN`/`PREPARING`/`CANCELLED` and make `delete_work_item()` non-destructive (`CANCELLED` transition without row deletion).
- [x] 9. Refactor scheduler admission (`SchedulerService`) as authorized caller for atomic `READY -> ADMITTED` authorization.
- [x] 10. Refactor execution start (`OrchestrationService`) as authorized caller for `ADMITTED -> RUNNING` transition without duplicate writers.
- [x] 11. Route post-merge completion (`PostMergeService._reconcile_change_and_backlog_item()`) for `DONE` and `COMPLETED` strictly through `LifecycleTransitionAuthority`.
- [x] 12. Ensure recovery and control-plane actions (`RestartRecoveryService`, `ControlPlaneService`) route state updates through authority as authorized callers.
- [x] 13. Ensure backlog and read projections retain orthogonality of completion and readiness (do not force `readiness_state = READY` on `COMPLETED`).
- [x] 14. Prove API GET and read surfaces (`DashboardService`, `StatusService`, `api/app.py`) produce zero lifecycle transitions.
- [x] 15. Add adversarial and concurrency tests (generic save `LifecycleBypassError`, atomic rollback on event failure, stale state, concurrent admission, cancelled item durability, read-only GETs, terminal non-resurrection).
- [x] 16. Execute exhaustive direct-writer audit in `src/` proving no unmigrated `Change`/`Backlog` lifecycle writer remains (search `.status =`, `model_copy(update={"status": ...})`, `changes.save(...)`, `backlog_items.save(...)`).
- [x] 17. Run Ruff, focused tests, full pytest, strict OpenSpec validation, and candidate-bound review evidence.

Do not implement Program B–J opportunistically.
