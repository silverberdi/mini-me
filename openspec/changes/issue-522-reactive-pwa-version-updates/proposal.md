## Why

When a new version of mini me is deployed, the single-page application remains unaware of the release because the Service Worker never proactively checks for updates while the tab remains open. Due to the Service Worker's cache-first static shell strategy, operators are forced to perform a blind manual refresh to trigger the background check and then a second refresh to activate the downloaded assets. This change makes version detection reactive and eliminates the double-refresh friction.

## What Changes

- Emit an `app.version` event over the existing Server-Sent Events (SSE) stream (`/api/v1/events`) immediately upon connection and upon backend service startup, containing the semantic version, immutable commit SHA, and build timestamp.
- In the Angular frontend (`RefreshService` and `AppComponent`), reactively listen for `app.version` events and compare the emitted commit SHA with the currently loaded version.
- When an updated commit SHA is detected or when the SSE stream reconnects after a service restart, automatically invoke `SwUpdate.checkForUpdate()` in the background without user intervention.
- Display the existing prominent Spanish update notice (*«Hay una nueva versión de mini me disponible. [Recargar]»*) as soon as `VERSION_READY` is emitted, allowing the operator to activate the update in a single click via `SwUpdate.activateUpdate()` and page reload.
- Maintain full offline resilience and graceful degradation when offline or when the Service Worker is disabled.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `pwa-responsive-and-offline-pwa`: Update the Service Worker static shell caching and update notice requirements to mandate reactive SSE version event emission and automated Service Worker update checks upon event reception or stream reconnection.

## Impact

- Backend: `/api/v1/events` stream generator in `src/minime/api/app.py` to yield the initial `app.version` event.
- Frontend: `RefreshService` in `frontend/src/app/core/refresh.service.ts` to handle `app.version` and reconnection triggers, and `AppComponent` in `frontend/src/app/app.component.ts` to trigger `swUpdate.checkForUpdate()`.
- Tests: Backend SSE stream unit test verifying `app.version` event format, and frontend component/E2E test verifying reactive update check triggering.
- Database & Deployment: Zero schema migrations, zero changes to PostgreSQL, zero breaking changes to existing API contracts.
