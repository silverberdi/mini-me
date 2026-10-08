# Proposal: Provider Probe Stale Test Fixtures Update

## Executive Summary
This OpenSpec change updates legacy provider-probe unit test fixtures to align with the canonical contract established in `codex-provider-health-probe-safety`.
Specifically, expensive provider availability probes (`probe_is_expensive = True`) require actionable `READY` work for that provider before execution. Test setups that previously initialized empty work queues cause `check_and_probe_provider(...)` to return without probing, generating false test failures (`adapter.probe_call_count == 0`).

## Proposed Solution
1. Update `_setup_exhausted(...)` in `tests/test_probe_governance.py` and `test_concurrent_expensive_probes_serialized_at_cooldown_boundary` in `tests/test_provider_execution_safety_corrections.py` to seed a `READY` `WorkQueueItem` for provider `codex` (with matching `Project` implementer) in `in_memory_uow`.
2. Update `_seed_exhausted_provider(...)` in `tests/test_provider_probe_reservation_concurrency.py` to seed a `READY` `WorkQueueItem` and matching `Project` in `PostgresPersistenceUnitOfWork` for PostgreSQL cross-session probe reservation tests.
3. Add an explicit negative test proving that when no actionable `READY` work exists, expensive Codex probes are correctly skipped.

This change represents test-fixture alignment only; runtime code remains completely untouched and out of scope.

## Scope & Non-Goals

### In Scope
- Test fixture update in `tests/test_probe_governance.py`.
- Test fixture update in `tests/test_provider_execution_safety_corrections.py`.
- Test fixture update in `tests/test_provider_probe_reservation_concurrency.py`.
- Explicit negative test for idle expensive probe suppression.

### Out of Scope / Non-Goals
- Modifying runtime code in `src/minime`.
- Altering provider health, probing, or scheduler policy.
