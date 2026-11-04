## Context

The Backlog view already has handlers that POST to the existing deactivate/reactivate routes, but its template tests for `PAUSED`. The existing API returns remote open issues classified as `ELIGIBLE`, `BLOCKED`, or `DISABLED`; the refresh service currently prefers `eligible_requests`, so disabled items are absent from the rendered collection. The API's `all_requests` provides the authoritative disabled items, while the intake service already excludes the `disabled` label from FIFO admission.

## Goals / Non-Goals

**Goals:**
- Make existing deactivate/reactivate actions reachable for not-started Requests shown in Backlog.
- Show active/disabled state and any reason already supplied with the Request payload.
- Reflect successful changes by refreshing the authoritative list and preserve the existing FIFO behavior.

**Non-Goals:**
- Any backend, endpoint, permission, lifecycle, or admission change.
- New frontend state machine, reason field persistence, or other Request operations/views.
- Displaying fabricated reasons or reporting success before the existing endpoint succeeds.

## Decisions

1. Use only the existing `POST .../deactivate` and `POST .../reactivate` routes and existing UI action handlers. Match button visibility to the API's `DISABLED` value; remove the stale `PAUSED` comparison.
2. Feed the Backlog's current Request collection from the existing response's eligible Requests plus disabled Requests from `all_requests`, deduplicated by issue number. Preserve the existing FIFO order for eligible entries and append disabled entries in their existing source order. Do not introduce blocked Requests into the actionable list as part of this change.
3. Render explicit active/disabled logical state alongside any existing eligibility label. Render a reason only when the current Request payload actually supplies it. The backend does not currently persist a deactivation reason, so the UI must not synthesize one.
4. On successful endpoint response, use the existing refresh path to reread the list; retain current error handling on rejection, including the endpoint's existing started/completed guard. The backend remains the authority for whether a Request may be changed.
5. Keep tests focused on the Backlog projection and action routing. Verify FIFO exclusion using the existing intake behavior and integration coverage; do not alter or duplicate that backend behavior.

## Risks / Trade-offs

The existing Request list does not expose a dedicated started flag. The action remains limited to the unstarted Backlog states and the existing endpoint enforces the lifecycle boundary; a concurrent start may therefore be rejected, and the UI must show the error rather than claim success. No reason will be shown unless an existing payload supplies one.
