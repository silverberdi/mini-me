# Proposal: Live Self-Hosting Pilot Diagnostic

## Why

To verify and prove the live self-hosting capabilities of Stage 016 (`016-autonomous-queue-work-selection`) in a real production-like environment with live PostgreSQL, GitHub App, and autonomous provider pipeline, a small, safe, real pilot change is required.

The pilot change introduces an operational diagnostic read-model field in `StatusService` that reports the self-hosting runtime capability and status.

## What Changes

- Add `get_self_hosting_diagnostic()` method in `src/minime/services/status_service.py`.
- Expose `"self_hosting"` dictionary inside `StatusService.get_system_status()` returning:
  - `runtime_engine`: `"mini-me-runtime"`
  - `status`: `"SELF_HOSTING_READY"`
  - `autonomous_queue`: `True`
- Add unit test coverage in `tests/test_self_hosting_diagnostic.py`.

## Capabilities

### New Capabilities
- `self-hosting-runtime-diagnostic`: Diagnostic read-model in StatusService exposing self-hosting operational readiness facts.

## Non-Goals (Scope Boundaries)

- No schema or database migrations required.
- No modifications to scheduler algorithms or queue prioritization.
- No modifications to external provider interfaces or budget rules.
