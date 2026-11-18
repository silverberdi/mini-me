## MODIFIED Requirements

### Requirement: Real-time reactive updates via EventSource
The PWA `RefreshService` SHALL subscribe to the existing authenticated Server-Sent Events stream `/api/v1/events` and immediately refresh server-backed state for runs, gates, projects, and Requests when their relevant events arrive without running a global blind periodic timer. Successful project or global pause/resume operations SHALL publish `project.pause_changed`; successful Request creation, deactivation, and reactivation SHALL publish `request.created`, `request.deactivated`, and `request.reactivated`; acceptance of an operator gate response SHALL publish `run.gate_acknowledged` before the coordinator's subsequent agent work completes. Run transitions and capacity updates SHALL continue to use the existing stream. Scheduler-originated Run transition events SHALL reach the API across process boundaries and be broadcast to connected authenticated SSE clients so the existing client refreshes the authoritative Run projection. Persisting a new active human gate, replacing the active gate, or resolving it SHALL also publish the existing bounded PostgreSQL Run notification and be relayed through the existing `run.transition` SSE event even when `current_stage` is unchanged; notification delivery SHALL occur only after commit, and the event SHALL NOT contain gate text or options. After the SSE stream reconnects, the PWA SHALL refresh the authoritative Run projection for the selected project before marking that observation current. When the API's PostgreSQL listener recovers after interruption, it SHALL publish a `run.resync` event so still-connected clients refresh their selected project's authoritative Run projection. If the server detects that a Run transition could not be delivered to a subscriber, it SHALL make the loss observable to that subscriber and cause its SSE connection to reconnect so the same authoritative refresh occurs; other subscribers SHALL remain connected. Events SHALL identify the affected scope/entity without carrying secrets or replacing authoritative API projections. A pending gate SHALL appear in Trabajo actual within five seconds of its durable `HUMAN_REQUIRED` transition when the authenticated SSE/API path is available. Following a reconnect, a still-pending gate SHALL reappear within five seconds after the authoritative Run refresh succeeds. The gate SHALL remain available through navigation and refresh until the API projection confirms its durable resolution. The PWA SHALL NOT use a periodic unprompted global interval timer to re-fetch state while operators are interacting with configuration screens or forms.

#### Scenario: Run transition updates UI without polling delay
- **WHEN** an SSE event arrives indicating a run stage transition or `HUMAN_REQUIRED`
- **THEN** `RefreshService` updates its signals immediately, reflecting the new stage and rendering human gate cards without waiting for a polling interval

#### Scenario: Scheduler transition reaches connected clients across processes
- **WHEN** the scheduler process persists a Run stage transition while one or more authenticated clients are connected to the API SSE stream
- **THEN** each connected client receives a transition event identifying the affected project and Run
- **AND** the client refreshes the authoritative Run projection and displays the persisted stage without a page reload or periodic polling

#### Scenario: Human gate change notifies clients when the stage is unchanged
- **GIVEN** the scheduler and API run as separate processes and an authenticated client is connected to the existing SSE stream
- **WHEN** the scheduler commits creation, replacement, or resolution of the active human gate without changing `current_stage`
- **THEN** PostgreSQL delivers the existing bounded Run notification after commit and the API relays `run.transition`
- **AND** the client fetches the authoritative Runs projection and displays or clears the current gate without manual reload
- **AND** the notification contains no question or option text

#### Scenario: Run state reconciles after SSE reconnection
- **WHEN** an authenticated client's SSE connection is re-established after interruption
- **THEN** the client refreshes the authoritative Run projection for its selected project
- **AND** it marks that observation current only after the refresh succeeds
- **AND** it does not start a periodic global polling timer

#### Scenario: API listener recovery reconciles connected clients
- **WHEN** the API's PostgreSQL listener reconnects after an interruption while a browser SSE stream remains connected
- **THEN** the API broadcasts `run.resync` on the authenticated stream
- **AND** the client refreshes the authoritative Run projection for its selected project

#### Scenario: Lost Run transition triggers only the affected client's reconciliation
- **WHEN** the server cannot enqueue a Run transition for one client's SSE subscriber
- **THEN** it marks that subscriber's stream for reconnection instead of silently dropping the transition
- **AND** the affected client reconnects and refreshes its authoritative Run projection
- **AND** other SSE subscribers remain connected

#### Scenario: Project or global pause changes
- **WHEN** an existing project or system pause/resume endpoint successfully changes execution pause state
- **THEN** an SSE event identifies the affected project or system scope and the PWA refreshes project state without waiting for polling

#### Scenario: Request is created, deactivated, or reactivated
- **WHEN** an existing Request mutation endpoint successfully creates, deactivates, or reactivates a Request
- **THEN** the matching SSE event identifies the affected project and Request and the PWA refreshes the authoritative Request projection

#### Scenario: Gate response is accepted before coordinator work completes
- **WHEN** the existing response endpoint accepts an operator answer for a current human gate
- **THEN** `run.gate_acknowledged` is published immediately with the affected Run identity, before subsequent coordinator work completes

#### Scenario: SSE disconnects or loses an event
- **WHEN** the EventSource stream is disconnected or an event is dropped
- **THEN** EventSource reconnects automatically, the PWA reconciles the authoritative Run projection before marking it current, and no global periodic polling disrupts configuration views

#### Scenario: Absence of unprompted periodic timer
- **WHEN** the operator is on any screen of the PWA
- **THEN** no background global interval timer triggers unrequested HTTP requests across all collections

#### Scenario: Scheduler-created human gate appears without manual reload
- **GIVEN** the scheduler and API run as separate processes and an authenticated operator has Trabajo actual open for the affected project
- **WHEN** the scheduler commits a Run transition to `HUMAN_REQUIRED`
- **THEN** the existing PostgreSQL/SSE path causes the UI to display the current Run, stage, and gate within five seconds without a page reload
- **AND** the displayed gate content comes from the authoritative Run projection.

#### Scenario: Pending gate returns after reconnect and survives navigation
- **GIVEN** a Run has a durably pending `HUMAN_REQUIRED` gate
- **WHEN** the operator reconnects the SSE stream, navigates away and back, or reloads Trabajo actual
- **THEN** the client refreshes the authoritative Run projection and displays the same current gate within five seconds after a successful refresh
- **AND** the gate is not discarded until the API confirms its durable resolution.
