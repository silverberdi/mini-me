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

`tests/test_scheduler_wakeup_postgres_e2e.py` is present and exits 0 in this environment, but is skipped because `MINIME_TEST_DATABASE_URL` is unset. No PostgreSQL E2E PASS is claimed until that isolated test database is supplied.

The E2E file now exercises the real `PostgresOperatorActionRepository.save` writer for committed accepted actions, rollback, non-eligible actions, duplicate accepted writes, durable action identity, and listener reconciliation fallback. These scenarios remain candidate-specific `NOT_VERIFIED` while the isolated PostgreSQL database is unavailable; the passing exit code records collection/skip behavior only.

## Focused Apply evidence

- `python -m pytest tests/test_scheduler_wakeup.py` → exit 0 (`4 passed`), covering strict channel/reason validation, malformed-input rejection, duplicate coalescing, startup reconciliation, and clearing the in-memory wake marker after reconciliation.
- `python -m pytest tests/test_postgres_run_event_listener.py tests/test_run_transition_postgres_notify_e2e.py tests/test_human_gate_current_payload_postgres_e2e.py -q` → exit 0 (`10 passed, 3 skipped`); PostgreSQL cases remain skipped because the isolated test URL is unavailable.
- `python -m pytest tests/test_stage_invocation_lifecycle_postgres_e2e.py -q` was attempted as the existing concurrency evidence and failed before the Change behavior was exercised because the environment does not expose `process_identity().boot_id`; this is retained as an unresolved environment limitation, not claimed as passing evidence.
- Final scoped regression: `python -m pytest tests/test_scheduler_wakeup.py tests/test_scheduler_wakeup_postgres_e2e.py tests/test_postgres_run_event_listener.py tests/test_run_transition_postgres_notify_e2e.py tests/test_human_gate_current_payload_postgres_e2e.py -q` → exit 0 (`14 passed, 7 skipped`). `python -m compileall -q` for the changed source/tests and `git diff --check` also exit 0.
