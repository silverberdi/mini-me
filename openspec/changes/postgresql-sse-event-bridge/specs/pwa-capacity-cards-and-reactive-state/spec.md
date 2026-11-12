## MODIFIED Requirements

### Requirement: Real-time reactive updates via EventSource
The PWA `RefreshService` SHALL subscribe to the existing authenticated Server-Sent Events stream `/api/v1/events` and immediately refresh server-backed state for runs, gates, projects, and Requests when their relevant events arrive without running a global blind periodic timer. Successful project or global pause/resume operations SHALL publish `project.pause_changed`; successful Request creation, deactivation, and reactivation SHALL publish `request.created`, `request.deactivated`, and `request.reactivated`; acceptance of an operator gate response SHALL publish `run.gate_acknowledged` before the coordinator's subsequent agent work completes. Run transitions and capacity updates SHALL continue to use the existing stream. Scheduler-originated Run transition events SHALL reach the API across process boundaries and be broadcast to connected authenticated SSE clients so the existing client refreshes the authoritative Run projection. After the SSE stream reconnects, the PWA SHALL refresh the authoritative Run projection for the selected project before marking that observation current. When the API's PostgreSQL listener recovers after interruption, it SHALL publish a `run.resync` event so still-connected clients refresh their selected project's authoritative Run projection. If the server detects that a Run transition could not be delivered to a subscriber, it SHALL make the loss observable to that subscriber and cause its SSE connection to reconnect so the same authoritative refresh occurs; other subscribers SHALL remain connected. Events SHALL identify the affected scope/entity without carrying secrets or replacing authoritative API projections. The PWA SHALL NOT use a periodic unprompted global interval timer to re-fetch state while operators are interacting with configuration screens or forms.

#### Scenario: Run transition updates UI without polling delay
- **WHEN** an SSE event arrives indicating a run stage transition or `HUMAN_REQUIRED`
- **THEN** `RefreshService` updates its signals immediately, reflecting the new stage and rendering human gate cards without waiting for a polling interval

#### Scenario: Scheduler transition reaches connected clients across processes
- **WHEN** the scheduler process persists a Run stage transition while one or more authenticated clients are connected to the API SSE stream
- **THEN** each connected client receives a transition event identifying the affected project and Run
- **AND** the client refreshes the authoritative Run projection and displays the persisted stage without a page reload or periodic polling

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
