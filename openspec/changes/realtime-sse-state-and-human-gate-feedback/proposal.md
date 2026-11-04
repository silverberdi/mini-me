## Why

The PWA currently relies on its 10–30 second refresh interval for project pause and Request changes, and the human gate remains visible while an accepted response waits for the asynchronous coordinator. The existing authenticated SSE stream and event broker can deliver these updates promptly without adding another event mechanism.

## What Changes

- Publish an immediate SSE acknowledgement when an operator's gate response is accepted, and hide the answered gate optimistically with processing feedback; restore it if submission fails.
- Publish SSE updates after successful project/global pause or resume and Request create/deactivate/reactivate operations, reusing the existing event broker and endpoints.
- Subscribe the PWA refresh service to these events so affected server projections update without waiting for polling.
- Retain the configured polling interval as a bounded fallback when SSE disconnects or drops events.

## Capabilities

### New Capabilities

### Modified Capabilities
- `pwa-capacity-cards-and-reactive-state`: Expand SSE-driven updates to project pause, Request mutations and gate acknowledgement while retaining bounded polling fallback.
- `pwa-runs-and-pipeline-observability`: Provide immediate optimistic feedback for gate responses and restore the gate on failed submission.

## Impact

- Backend: existing `/api/v1/events` stream, event broker, project pause/resume and Request create/deactivate/reactivate endpoints, and the existing async gate-response endpoint.
- Frontend: `RefreshService` and `trabajo-actual.component.ts`.
- Tests: focused backend/API and frontend coverage plus an authenticated integration path that observes mutation and gate events over the existing SSE stream.
- No new event broker, endpoint family, persistence, admission behavior, or coordinator flow; the coordinator is notified only at the existing response acceptance/transition boundary.
