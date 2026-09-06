# Partial implementation evidence

## Recovery corrections

- A capacity window with an unknown reset no longer prevents an explicitly supplied probe from running.
- Probes have a 30-second timeout; failure or timeout preserves provider unavailability and records a failure event.
- Successful probes reset consecutive failure counts.
- Scheduler reconciliation no longer promotes EXHAUSTED to AVAILABLE solely because an estimated reset has elapsed.

These corrections do not establish periodic production probing. The existing probe callback still needs real adapter integration and durable scheduling metadata.

## Checks

`python -m pytest tests/test_capacity_recovery_regressions.py tests/test_provider_health.py tests/test_waiting_capacity.py --basetemp=.test-tmp/capacity-recovery -q`

Result: 22 passed. Tests use in-memory repositories; this is not PostgreSQL or production validation.

`python -m ruff check src/minime/services/provider_health_service.py src/minime/services/scheduler_service.py tests/test_capacity_recovery_regressions.py`

Result: passed. `git diff --check` also passed.

## Required clarification

Neither the active design nor provider configuration defines a lightweight capacity-probe command/endpoint and positive capacity response for Codex or Antigravity. Implementation/review invocations exist, but substituting those for a health probe can consume execution quota and does not establish a read-only capacity protocol. The operator has been asked to supply the supported protocol for each adapter. AGENTS.md requires surfacing ambiguity that materially affects behavior, cost, or architecture.

## Remaining work

The full change remains incomplete: generic adapters and registration, periodic durable probing, reset metadata and operator mutations, bounded wait decisions, material execution eligibility and generic drain integration, PWA/TUI parity, PostgreSQL verification, candidate-bound container preview and human validation, and production recovery evidence. Existing task checkmarks were supplied with the workspace and have not been independently substantiated by this attempt. No additional acceptance task is marked complete by this evidence.
