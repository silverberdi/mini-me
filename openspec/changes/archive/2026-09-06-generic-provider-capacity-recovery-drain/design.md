# Design: Generic Provider Capacity Recovery & Drain Policy

## Architectural Approach

### 1. Provider Adapter Architecture (`minime.adapters.provider_adapter`)
Define `ProviderAdapterInterface` with contract:
- `provider_name: str`
- `supported_roles: set[str]`
- `probe_availability(timeout_seconds: float) -> bool`
- `extract_capacity_signal(raw_output: str, exit_code: int) -> CapacitySignal | None`

Concrete adapters:
- `CodexProviderAdapter`: executes lightweight ephemeral subshell commands to test Codex CLI availability.
- `AntigravityProviderAdapter`: executes lightweight plan commands to test Antigravity CLI availability.
- `OpenRouterProviderAdapter`: verifies API key and model discovery endpoint.
- `DeepSeekProviderAdapter`: verifies API key and endpoint.
- `FakeProviderAdapter`: pluggable mock verifying that third-party / future providers (e.g. Cursor) plug in seamlessly.

### 2. Proactive Recovery Probing (`minime.services.provider_health_service`)
- `ProviderHealthService.check_and_probe_provider(provider)` dynamically retrieves the registered provider adapter and runs `probe_availability()`.
- Probes are bounded to 30s timeout and create zero Runs or Jobs.
- Positive probe transitions provider to `AVAILABLE` and emits `PRIMARY_CAPACITY_RECOVERED`.
- Negative probe preserves `TEMPORARILY_UNAVAILABLE` and emits `PROVIDER_PROBE_FAILED`.
- `SchedulerService.tick()` calls `probe_unavailable_providers()` to detect capacity restoration autonomously.

### 3. Capacity Window & Operator Reported Reset
- `CapacityWindow` stores `source_signal` (`AUTO_DISCOVERED` vs `OPERATOR_REPORTED`) and `capacity_reset_at`.
- `ProviderHealthService.set_operator_expected_reset(provider, reset_at)` saves operator-supplied recovery timestamps.
- Reset timestamps do not blindly restore capacity; positive probe verification remains authoritative.

### 4. Drain Fallback Eligibility Boundary (`minime.services.openrouter_eligibility`)
- Backend helper `is_material_execution_started(job)` checks `job.attempt_count > 0` or candidate existence.
- Evaluator rejects fallback when `is_new_ready_change` is True or when material execution has not started.

### 5. Bounded Blind WAITING_CAPACITY & Operator Choices (`minime.services.scheduler_service`)
- Unknown reset periods in `WAITING_CAPACITY` are capped at 2 hours.
- When elapsed wait > 2 hours, run transitions to `NEEDS_HUMAN` with explicit decision payload:
  1. `SET_RETURN_TIME`: operator supplies reset timestamp.
  2. `FINISH_WITH_DRAIN`: operator authorizes drain fallback (if materially eligible).
  3. `KEEP_WAITING`: operator confirms waiting without consuming retry budget.
