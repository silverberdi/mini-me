## Context

See `proposal.md` for the user-visible problem. `minime-api.service` and `minime-scheduler.service` are separate processes. The authenticated `/api/v1/events` endpoint subscribes to `event_broker`, a process-local in-memory fanout. The scheduler persists Run state through PostgreSQL but cannot publish into the API process's in-memory subscribers. `RefreshService` already handles `run.transition` by re-reading the authoritative API projection, but its `EventSource.onopen` currently only updates connection signals. The API broker also drops a publication when a particular subscriber queue is full without triggering that subscriber to reconcile. The project already depends on psycopg 3 through SQLAlchemy.

The current OpenSpec capability `pwa-capacity-cards-and-reactive-state` requires updates through the existing SSE stream without a global periodic polling timer and requires configuration screens to remain undisturbed by broad refreshes.

## Goals / Non-Goals

**Goals:**
- Bridge scheduler-originated Run stage transitions across the existing PostgreSQL connection shared by the services.
- Re-broadcast notifications through the current authenticated SSE endpoint and reuse its existing client refresh path.
- Re-read the selected project's authoritative Run projection after an SSE reconnect and after the server detects loss of a Run transition for that subscriber.
- Keep PostgreSQL Run state authoritative; notification payloads are small wake-up hints, not state or audit records.
- Preserve existing endpoint events, API shape, authentication boundary, and no-periodic-polling behavior.

**Non-Goals:**
- Add a broker service, event table, persistent replay log, generic event framework, or a second API.
- Change scheduler admission, Run lifecycle semantics, or unrelated project/request/quota events.
- Deploy or restart production services as part of this Change.

## Decisions

1. **Use PostgreSQL `NOTIFY` and `LISTEN` over the existing psycopg 3 dependency.** The two services already share PostgreSQL, and notifications provide the requested cross-process wake-up without Redis, new infrastructure, or durable duplicate state. A dedicated long-lived asynchronous connection in the API is appropriate for `LISTEN`; it must be owned and closed by the existing API lifespan.
   - **Alternative considered:** keep the process-local broker only. Rejected because it cannot cross the systemd service boundary.
   - **Alternative considered:** add Redis or a durable event queue/table. Rejected because the Issue asks for PostgreSQL native notifications and persisted Run state is already authoritative.

2. **Emit notification from the existing scheduler transition write transaction.** The notification SHALL be issued only for the stage transition path and in the same PostgreSQL transaction that persists the new Run stage. PostgreSQL delivers transactional notifications only after commit, so rollback cannot announce an uncommitted transition. The payload SHALL contain only bounded identifiers and transition fields needed by the existing event contract.
   - **Alternative considered:** publish from the API or after the scheduler commit using a second connection. Rejected because the API does not own scheduler transitions and a post-commit failure could leave a committed transition with no notification.

3. **Keep the API listener as an adapter into the existing in-process `EventBroker`.** The listener validates the notification payload and publishes the existing `run.transition` event; the authenticated SSE endpoint and Angular `RefreshService` remain the fanout and projection-refresh path. The browser re-reads the Run from the API rather than treating PostgreSQL notification data as authoritative state.
   - **Alternative considered:** create a second SSE stream or have the browser connect to PostgreSQL-related infrastructure. Rejected because it duplicates the API contract and crosses the client/server security boundary.

4. **Reconcile state when either side of the stream recovers.** On each `EventSource` open, `RefreshService` refreshes only the selected project's Run/request projection through the existing API method; connection state is marked current after that read succeeds. If the API's PostgreSQL listener reconnects while browser streams remain open, it publishes `run.resync`; the client handles that event with the same scoped read. If the API's per-subscriber queue cannot accept a `run.transition`, mark only that stream for closure/reconnection. The browser's existing automatic reconnect then triggers the scoped authoritative read. This avoids a global polling timer and does not disrupt other subscribers or configuration forms.
   - **Alternative considered:** silently drop the event and add a fixed-interval global poll. Rejected because it leaves stale UI until the next tick and adds continuous requests to every screen.
   - **Alternative considered:** introduce a durable event log or replay cursor. Rejected because the Run projection already stores authoritative state and the Issue needs a resync after loss, not a second history source.
   - **Alternative considered:** leave connected browsers unaware when the API's PostgreSQL listener reconnects. Rejected because their SSE transport may remain healthy while scheduler notifications were missed.

5. **Prove the path with PostgreSQL and independent service processes.** The integration evidence must exercise the scheduler's real transition persistence, PostgreSQL delivery, API listener, authenticated SSE stream, and resulting authoritative Run read. Browser E2E must also cover reconnect and a deliberately saturated subscriber. A direct call to `EventBroker.publish`, an in-memory test database, or a mocked `NOTIFY` is not sufficient evidence for the cross-process behavior.

## Risks / Trade-offs

- **[Risk] PostgreSQL notifications are transient and have a bounded payload.** → Use only compact Run identifiers/stage fields, publish within the state transaction, and retain PostgreSQL Run state as the authority. Persistent replay is outside Issue #366.
- **[Risk] A broken listener connection stops live relay.** → Own listener startup, disconnect detection, bounded reconnect, and shutdown in the API lifespan; surface listener health through existing operational logging/health conventions without adding a new durable state model.
- **[Risk] A browser reconnects while the server is still unavailable.** → Keep the observation stale until the scoped authoritative API read succeeds; do not claim current state from the SSE transport alone.
- **[Risk] A slow SSE subscriber repeatedly overflows its bounded queue.** → Close/reconnect only that subscriber on a lost Run transition; its snapshot read converges to current Run state, while other streams remain unaffected.
- **[Risk] Notification is sent for non-transition Run writes.** → Attach publication only to the existing canonical stage transition writer and test that unrelated saves do not emit `run.transition`.
- **[Risk] Event payload leaks unnecessary evidence.** → Publish only project ID, Run ID, and stage/status fields; never include prompts, provider output, credentials, or evidence JSON.

## Migration Plan

No schema migration is expected: PostgreSQL notifications are ephemeral and use the existing database. Roll out through the normal code PR and the repository's CI/CD. If the listener is unavailable, the API continues serving HTTP and existing local SSE events; roll back the code change through the normal release process. Do not require a scheduler restart or production deployment as part of OpenSpec planning.
