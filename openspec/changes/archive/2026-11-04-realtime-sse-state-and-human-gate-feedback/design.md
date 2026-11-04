## Context

See `proposal.md` for motivation. The authenticated `/api/v1/events` endpoint streams events from the bounded, process-local `EventBroker`. The PWA `RefreshService` already listens for run events and independently refreshes projects, runs, and the selected project's Requests on its configured timer. Existing synchronous project and Request mutation endpoints expose authoritative response payloads; gate responses are accepted asynchronously with HTTP 202. The coordinator currently publishes `run.transition` after its work returns.

## Goals / Non-Goals

**Goals:** Reuse the event broker and existing endpoints to trigger prompt refreshes for the enumerated state changes; make gate responses feel immediate while preserving the backend as authority; retain the existing bounded polling behavior for recovery.

**Non-Goals:** Persisting or replaying events, replacing EventSource, changing admission or pause semantics, adding mutation endpoints, or restructuring coordinator stages.

## Decisions

- Publish typed events from the existing API boundaries after their operation succeeds. For synchronous pause/resume and Request mutation handlers, queue publication as response background work so their synchronous service execution remains unchanged. The gate-response endpoint publishes `run.gate_acknowledged` immediately after it accepts and schedules the response, before the asynchronous coordinator finishes. This event means the answer was accepted for processing, not that the Run completed.
- Use `project.pause_changed` for project and system pause/resume, with scope and affected project identity; use `request.created`, `request.deactivated`, and `request.reactivated` with project and Request identity; include project and Run identity in `run.gate_acknowledged`. Keep payloads minimal and omit request bodies, gate answers, credentials, and other sensitive content. Publish no mutation event when the existing operation fails.
- Keep event handling in the existing `RefreshService`: state-change events trigger its existing authoritative `read()` flow, while `quota.update` continues to update quotas from its event payload. The PWA does not patch separate client-owned project/Request/Run copies from event payloads.
- Keep the current configured polling timer and EventSource auto-reconnect. Polling remains the bounded recovery path for dropped events and stream outages; no new timer, queue, or durable event table is introduced.
- Keep gate acknowledgement ephemeral in `TrabajoActualComponent`, keyed to the answered Run and current gate identity. Hide that gate immediately on submit and show submission progress; after a successful HTTP response, show «Respuesta enviada, procesando…». If HTTP or transport fails, clear the optimistic acknowledgement and show the error so the durable gate is visible again. Reconcile it when an authoritative refresh shows the gate cleared, replaced, or the Run completed, so a later gate cannot be hidden by an earlier acknowledgement.
- Test the real API/EventBroker delivery path using the repository's authenticated API test setup, and test the frontend's event and acknowledgement behavior using its existing test conventions. Include a production Angular build as compile evidence.

## Risks / Trade-offs

- [The process-local EventBroker can drop events when subscriber queues are full or a client disconnects] → Preserve the existing bounded polling timer and refresh from authoritative API responses; do not treat an event as durable state.
- [A gate acknowledgement event may arrive before the coordinator clears its stored payload] → Keep the local acknowledgement bound to that exact gate identity until a subsequent authoritative Run snapshot resolves or replaces it.
- [An event is published for an unsuccessful mutation] → Schedule or publish only after the existing endpoint operation returns success; test failure paths produce no event.
- [An event payload leaks operator text or credentials] → Publish only action and entity identities; the frontend refetches authoritative data through the already authenticated APIs.

## Migration Plan

No database migration or event-storage migration is required. Deploy the backend and frontend together; rollback by reverting the change. Clients continue to receive existing run events and use polling if new event types are not recognized.
