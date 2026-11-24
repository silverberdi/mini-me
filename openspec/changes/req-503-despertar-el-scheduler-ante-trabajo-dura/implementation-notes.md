# Apply implementation notes

## Integration census

- `src/minime/db/repository.py:PostgresOperatorActionRepository.save` is the writer for accepted durable operator actions. It is modified to enqueue a PostgreSQL `NOTIFY` in the same SQLAlchemy transaction only for Scheduler-owned continuation actions with a Run identity.
- `src/minime/db/notifications.py` retains `minime_run_transition` for UI/SSE and adds the separate ephemeral `minime_scheduler_wakeup` channel. No outbox row, work table, migration, or direct Scheduler call was added.
- `src/minime/services/postgres_run_event_listener.py` remains the UI/SSE listener and is conserved; it does not consume Scheduler wake-ups.
- `src/minime/cli/main.py:scheduler_run_cmd` remains the canonical durable reconciliation and dispatch entry. `SchedulerWakeupBridge` only interrupts its existing lightweight poll wait; it never selects a Run or executes a stage.
- Existing claims, fencing, gate fingerprints, Run identity, dispatch intents, and external execution remain in `NativeOrchestrationCoordinator` and existing repositories; this Change does not duplicate them.

## Retirement ledger

`NONE` — the census found no demonstrably obsolete SSE listener or polling/reconciliation route. The existing SSE listener and periodic poll are retained because they have independent UI and lost-notification recovery responsibilities.

## Apply evidence limitation

`tests/test_scheduler_wakeup_postgres_e2e.py` runs against the configured isolated PostgreSQL test database and passes. The test database identity is checked before writes; no production database is used.

The E2E file exercises the real `PostgresOperatorActionRepository.save` writer for committed accepted actions, rollback, non-eligible actions, duplicate accepted writes, durable action identity, and listener reconciliation fallback.

## Focused Apply evidence

- `python -m pytest tests/test_scheduler_wakeup.py` → exit 0 (`4 passed`), covering strict channel/reason validation, malformed-input rejection, duplicate coalescing, startup reconciliation, and clearing the in-memory wake marker after reconciliation.
- `python -m pytest tests/test_postgres_run_event_listener.py tests/test_run_transition_postgres_notify_e2e.py tests/test_human_gate_current_payload_postgres_e2e.py -q` → exit 0 as part of the final scoped run; PostgreSQL cases execute against the isolated test database.
- `python -m pytest tests/test_stage_invocation_lifecycle_postgres_e2e.py -q` → exit 0 (`3 passed`). The test preserves real PostgreSQL claim/fencing assertions and uses a managed-runner-only identity fixture when `/proc` is isolated; production process identity remains fail-closed.
- Final scoped regression: `python -m pytest tests/test_scheduler_wakeup.py tests/test_scheduler_wakeup_postgres_e2e.py tests/test_postgres_run_event_listener.py tests/test_run_transition_postgres_notify_e2e.py tests/test_human_gate_current_payload_postgres_e2e.py -q` → exit 0 (`21 passed`). `python -m compileall -q` for the changed source/tests and `git diff --check` also exit 0.
