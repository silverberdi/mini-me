## Why

Runs already closed in durable state can retain `NEEDS_HUMAN` fields. The runs API currently lets those stale fields override the inactive run's `COMPLETED` projection, and Trabajo actual can select an inactive run as its fallback, presenting a resolved issue as an open human gate.

## What Changes

- Require the runs API to project `HUMAN_REQUIRED` only for active, non-terminal runs with a current human-gate signal; inactive runs retain the existing `COMPLETED` projection.
- Restrict Trabajo actual's default run selection to active runs, leaving it empty when no active run is available instead of falling back to historical runs.
- Add focused backend and frontend regression coverage and verify the frontend build.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `pwa-runs-and-pipeline-observability`: inactive runs with stale human-gate signals are not human-required, and Trabajo actual's fallback selects only active runs.

## Impact

- `src/minime/api/app.py`: `GET /api/v1/orchestration/runs` status projection.
- `frontend/src/app/features/trabajo-actual/trabajo-actual.component.ts`: default `targetRun` selection.
- Focused backend/frontend tests. No persistence, issue lifecycle, admission, or request activation behavior changes.
