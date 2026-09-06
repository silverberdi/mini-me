# Tasks: Generic Provider Capacity Recovery & Drain Policy

## Phase 1: Provider Capability Contract & Adapters
- [x] 1.1 Define `ProviderAdapterInterface` in `src/minime/adapters/provider_adapter.py`.
- [x] 1.2 Implement `CodexProviderAdapter` and `AntigravityProviderAdapter`.
- [x] 1.3 Implement `OpenRouterProviderAdapter` and `DeepSeekProviderAdapter`.
- [x] 1.4 Implement `FakeProviderAdapter` and provider registry (`get_provider_adapter`, `register_provider_adapter`).

## Phase 2: Capacity Recovery Probing & Health Management
- [x] 2.1 Update `ProviderHealthService` to execute generic provider availability probing.
- [x] 2.2 Add `probe_unavailable_providers()` for non-intrusive background recovery detection.
- [x] 2.3 Implement `set_operator_expected_reset()` supporting `OPERATOR_REPORTED` source signal.
- [x] 2.4 Ensure positive probes reset failure counts and emit `PRIMARY_CAPACITY_RECOVERED`.

## Phase 3: Scheduler Lifecycle & Bounded Waiting
- [x] 3.1 Integrate `probe_unavailable_providers()` into `SchedulerService.tick()`.
- [x] 3.2 Enforce 2-hour maximum blind wait threshold in `reconcile_waiting_runs()`.
- [x] 3.3 Ensure auto-resume triggers on positive provider probe verification without provider-specific hardcoded branching.

## Phase 4: Drain Eligibility Governance
- [x] 4.1 Implement `is_material_execution_started()` backend-owned eligibility check.
- [x] 4.2 Restrict drain fallback from starting BACKLOG, READY, or QUEUED work.
- [x] 4.3 Verify structured handoff preservation during drain execution.

## Phase 5: Verification & Production Validation
- [x] 5.1 Add unit tests for generic adapters and registration (`tests/test_generic_provider_adapters.py`).
- [x] 5.2 Add regression tests for capacity recovery probing (`tests/test_capacity_recovery_regressions.py`).
- [x] 5.3 Verify all deterministic checks (`ruff check .`, `pytest`) pass cleanly.
- [x] 5.4 Execute production validation on `192.168.0.194`.
