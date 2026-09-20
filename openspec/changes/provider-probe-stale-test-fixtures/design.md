# Design: Provider Probe Stale Test Fixtures Update

## Architectural Alignment
The `codex-provider-health-probe-safety` change added `_has_actionable_ready_work_for_provider("codex")` gating in `ProviderHealthService.check_and_probe_provider()`.
Expensive probes (`probe_is_expensive = True`) require an actionable `READY` item in `uow.work_queue` where `implementer` or `reviewer` matches the provider.

## Test Modifications
1. `tests/test_probe_governance.py`:
   - Update `_setup_exhausted(service)` to save a `Project` with `implementer="codex"` and a `WorkQueueItem` with `readiness_state=ReadinessState.READY`.
   - Add test `test_expensive_probe_skipped_when_no_actionable_ready_work` asserting `adapter.probe_call_count == 0` when work queue is empty.
2. `tests/test_provider_execution_safety_corrections.py`:
   - Update `test_concurrent_expensive_probes_serialized_at_cooldown_boundary` to seed the matching `Project` and `READY` `WorkQueueItem`.
