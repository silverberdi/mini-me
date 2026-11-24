## Context

See `proposal.md` for motivation. The backend currently provides a Server-Sent Events (SSE) endpoint at `GET /api/v1/events` backed by `event_broker` (`src/minime/api/app.py`), and the Angular frontend maintains a persistent `EventSource('/api/v1/events')` connection in `RefreshService`. The frontend also uses Angular's `@angular/service-worker` `SwUpdate` service in `AppComponent` to listen for `VERSION_READY` events, which activates the update banner. However, `SwUpdate.checkForUpdate()` is currently never called, leaving the Service Worker oblivious to new releases until manual navigation occurs.

## Goals / Non-Goals

**Goals:**
- Provide instantaneous, push-based awareness of newly deployed versions to all connected clients over the existing SSE stream.
- Trigger `SwUpdate.checkForUpdate()` automatically upon detecting a version change or upon SSE reconnection following a backend deployment restart.
- Preserve the operator's choice to reload via the existing Spanish notice without unprompted, disruptive page refreshes.
- Ensure zero errors or unhandled rejections when offline or in environments where Service Worker is disabled.

**Non-Goals:**
- Introducing WebSockets or secondary notification protocols.
- Forcing silent reloads that could interrupt active operator forms or navigation.
- Database schema changes, migrations, or credential handling.

## Decisions

### 1. Emit `app.version` on SSE connection and startup
In `src/minime/api/app.py`, enhance the `stream()` generator of `GET /api/v1/events` to yield an `app.version` event immediately after connection establishment:
```text
event: app.version
data: {"version": "...", "commit_sha": "...", "build_at": "..."}
```
The payload reads from the server's existing static version metadata (`src/minime/static/version.json` or config).
*Alternatives considered:*
- Polling `/version.json` on a client timer: Rejected because polling introduces arbitrary latency (minutes) and needless HTTP traffic, whereas SSE delivers immediate push notifications with zero overhead.

### 2. Trigger `SwUpdate.checkForUpdate()` on event mismatch and stream reconnection
In `frontend/src/app/core/refresh.service.ts`:
- Add a listener for `this.events.addEventListener('app.version', ...)`: compare the received `commit_sha` against `VersionService.info()?.commit_sha`. When a mismatch is observed, or when `this.events.onopen` fires after an initial connection (indicating a server restart post-deployment), request a Service Worker update check.
- Debounce update checks to avoid redundant calls during rapid network oscillations (e.g. minimum 30-second interval between checks).
*Alternatives considered:*
- Automatically executing `activateUpdate()` and `location.reload()` without operator prompt: Rejected because unprompted reloads risk losing unsaved state if the operator is currently answering a human gate or reviewing a diff.

### 3. Graceful degradation when offline or Service Worker disabled
All calls to `this.swUpdate.checkForUpdate()` check `this.swUpdate.isEnabled` and are wrapped in `try/catch` blocks. In development mode or browsers without Service Worker support, the event quietly updates the in-memory `VersionService` without error.

## Risks / Trade-offs

- **[Rapid SSE reconnects during network instability]** → Debounce `checkForUpdate()` with a 30-second throttle so transient reconnects do not flood the network with manifest requests.
- **[Service Worker disabled in local dev mode]** → Guard all calls with `swUpdate.isEnabled`; dev workflows continue running without warnings.
- **[Stale static version.json caching]** → The server emits the version directly in the SSE stream payload, bypassing HTTP cache headers entirely.

## Migration Plan

Zero database migrations or configuration changes required. Backward compatible with all existing clients. Rollback is a simple code revert.
