# Design: Provider Probe Stale Test Fixtures Update

## Architectural Alignment
The `codex-provider-health-probe-safety` change added `_has_actionable_ready_work_for_provider(...)` gating in `ProviderHealthService.check_and_probe_provider()`.
Expensive probes (`probe_is_expensive = True`) require an actionable `READY` item in `uow.work_queue` where `implementer` or `reviewer` matches the provider.

## Test Modifications
1. `tests/test_probe_governance.py`:
   - Update `_setup_exhausted(service)` to save a `Project` with `implementer="codex"` and a `WorkQueueItem` with `readiness_state=ReadinessState.READY`.
   - Add test `test_expensive_probe_skipped_when_no_actionable_ready_work` asserting `adapter.probe_call_count == 0` when work queue is empty.
2. `tests/test_provider_execution_safety_corrections.py`:
   - Update `test_concurrent_expensive_probes_serialized_at_cooldown_boundary` to seed the matching `Project` and `READY` `WorkQueueItem`.
3. `tests/test_provider_probe_reservation_concurrency.py`:
   - Update helper `_seed_exhausted_provider(session_factory, provider)` to seed a `Project` with `implementer=provider` and a `WorkQueueItem` with `readiness_state=ReadinessState.READY` into PostgreSQL UOW.
   - Prior stale behavior: provider health was seeded as `EXHAUSTED` in PostgreSQL, but no actionable `READY` work existed, causing `check_and_probe_provider()` to skip probing before reaching the PostgreSQL `SELECT ... FOR UPDATE` lock check.
   - Current fixture behavior: seeds `Project` and `READY` `WorkQueueItem` so expensive probes are eligible under current governance.
   - Purpose: preserves the actual cross-session reservation/concurrency test while satisfying the canonical expensive-probe admission gate. This does NOT weaken reservation or concurrency assertions.
