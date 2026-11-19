# Tasks: Codex Provider Health Probe Safety

- [x] 1. Update `CodexProviderAdapter.probe_availability()` in `src/minime/adapters/provider_adapter.py` to include `--skip-git-repo-check` and parse `401`/`token_expired`/`Failed to refresh token` errors.
- [x] 2. Update `ProviderHealthService` in `src/minime/services/provider_health_service.py` to gate expensive background probes on actionable `READY` work.
- [x] 3. Update `ProviderHealthService` to classify `401`/`token_expired` responses as `AUTH_REQUIRED` and transition health status to `ProviderHealthStatus.AUTH_REQUIRED`.
- [x] 4. Update `SchedulerService` in `src/minime/services/scheduler_service.py` to handle `AUTH_REQUIRED` status and return operational decision `NEEDS_HUMAN`.
- [x] 5. Add comprehensive unit tests in `tests/test_codex_provider_health_probe_safety.py` covering auth classification, probe gating, `--skip-git-repo-check`, and admission invariants.
- [x] 6. Run targeted tests, full pytest suite, ruff check, and OpenSpec strict validation.
