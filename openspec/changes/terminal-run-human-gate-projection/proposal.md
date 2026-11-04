## Why

Runs completed before the current human-payload handling can retain `human_gate=NEEDS_HUMAN`. The runs endpoint then reports `HUMAN_REQUIRED` despite terminal completion, presenting stale work as a pending operator decision.

## What Changes

- Make terminal run state take precedence over stale human-gate fields when projecting whether a run requires human action.
- Add a focused regression test for a completed, inactive run that retains `human_gate=NEEDS_HUMAN`.

## Capabilities

### New Capabilities

### Modified Capabilities

- `pwa-runs-and-pipeline-observability`: terminal runs are projected as non-human-required even when stale gate fields remain.

## Impact

- `src/minime/api/app.py`, endpoint `GET /api/v1/orchestration/runs`.
- Focused endpoint regression coverage in `tests/test_human_gate_current_payload.py`.
- No database cleanup, lifecycle mutation, UI change, or other projection behavior is in scope.
