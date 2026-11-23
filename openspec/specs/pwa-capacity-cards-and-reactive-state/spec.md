# pwa-capacity-cards-and-reactive-state Specification

## Purpose
Mejora la PWA con una representación compacta y accesible de capacidad y una única proyección reactiva del estado operativo, manteniendo coherencia entre Dashboard, Trabajo, Trabajo actual, Backlog y refresco manual.

## Requirements

### Requirement: Compact capacity cards
The PWA SHALL display each verified provider/model capacity in the same compact, accessible analog-gauge card structure, with its active model, observed value, status (`Normal`, `En ventana`, or `Crítico`), reset time when known, and an explicit unknown state when not verified. A verified provider-reported `remaining_percent` SHALL control the gauge arc and retain the current percentage presentation. When a verified monetary `balance` and `currency` exist without a verified `remaining_percent`, the card SHALL show the actual balance and currency as its primary center value. For a USD balance, the gauge SHALL use USD 20 as a visual reference equal to 100%, computing `balance / 20 * 100` and clamping only the arc to the range 0–100%. The UI SHALL visibly identify this USD 20 reference as a display scale, not provider-reported quota, spending limit, budget, or authorization. A monetary balance in another currency SHALL remain visible but SHALL NOT be converted to a progress value without a defined reference. When neither a verified percentage nor a supported balance is available, the gauge SHALL show an explicit unknown value and a neutral arc. All four provider cards SHALL use the same shared gauge structure and the same precedence rules; provider-specific data acquisition SHALL NOT create provider-specific rendering branches.

#### Scenario: Responsive verified provider percentage
- **WHEN** a verified provider observation includes a finite `remaining_percent` on desktop or mobile
- **THEN** the card presents its provider/model, reported remaining percentage, status, and reset countdown when known within the shared analog-gauge structure
- **AND** the reported percentage controls the arc even when a monetary balance is also present

#### Scenario: Responsive verified quota card
- **WHEN** a verified five-hour observation is available on desktop or mobile
- **THEN** the card presents its provider/model, real remaining value, status, and reset countdown within the shared analog-gauge structure

#### Scenario: Unknown quota is truthful
- **WHEN** no verified capacity observation is available
- **THEN** the card displays an unavailable/unknown state and no fabricated percentage, balance, or reset countdown

#### Scenario: USD balance maps to visual progress when percentage is absent
- **WHEN** a verified observation has `balance: 10.00`, `currency: USD`, and `remaining_percent: null`
- **THEN** the card visibly presents `$10.00 USD` in the center of the shared gauge
- **AND** the gauge arc represents 50% progress
- **AND** the UI identifies USD 20 as the visual 100% reference

#### Scenario: Verified monetary balance is the primary DeepSeek value
- **WHEN** a verified DeepSeek observation contains `balance: 20.18`, `currency: USD`, and `remaining_percent: null`
- **THEN** the capacity card visibly presents `$20.18 USD` in the center of its gauge
- **AND** it does not present `—` or a percentage in place of that balance

#### Scenario: USD balance at or above the visual reference
- **WHEN** a verified observation has a USD balance of 20.00 or more and no verified percentage
- **THEN** the card presents the exact reported monetary balance in its center
- **AND** the gauge arc is full but does not exceed 100%
- **AND** the balance text is not clamped or altered

#### Scenario: Monetary balance does not invent a gauge denominator
- **WHEN** DeepSeek reports a USD balance without a provider-reported maximum limit or verified percentage
- **THEN** the card uses only the explicitly agreed USD 20 display reference for the arc
- **AND** it identifies the reference as visual only, not as a provider limit or spending policy
- **AND** it does not infer a provider quota or alter the actual balance

#### Scenario: Zero USD balance
- **WHEN** a verified observation has `balance: 0.00`, `currency: USD`, and no verified percentage
- **THEN** the card presents `$0.00 USD`
- **AND** the gauge arc shows 0% progress

#### Scenario: Other currencies do not use the USD reference
- **WHEN** a verified observation has a monetary balance in a currency other than USD and no verified percentage
- **THEN** the card presents the actual balance and currency
- **AND** the gauge arc remains neutral because no visual reference for that currency is defined

#### Scenario: Balance remains legible without hover
- **WHEN** a verified monetary balance is displayed on desktop, touch, or mobile
- **THEN** the balance and currency are readable directly inside the capacity card without requiring a mouse hover

#### Scenario: Unknown quota is truthful and consistent
- **WHEN** no verified percentage or supported monetary balance is available
- **THEN** each provider card displays the same unknown value and neutral gauge treatment
- **AND** it shows no fabricated balance or progress

#### Scenario: Missing monetary balance remains truthful
- **WHEN** a DeepSeek observation has no verified `balance` and no verified `remaining_percent`
- **THEN** the card displays an explicit unavailable/unknown state and does not invent a monetary value, percentage, or maximum

#### Scenario: Shared gauge remains usable on mobile
- **WHEN** the Dashboard displays provider capacity cards on a mobile viewport
- **THEN** all four cards retain the same gauge dimensions and readable primary values without horizontal overflow

### Requirement: Single reactive run projection
The PWA SHALL derive `activeRun`, `nextEligible`, and related view state from one current server snapshot so an active Run cannot also be shown as next work.

#### Scenario: Active work excluded from next work
- **WHEN** a Run is active or transitioning stages
- **THEN** Dashboard, Trabajo, Trabajo actual, and Backlog identify the same Run consistently and exclude its Request from Siguiente Trabajo

#### Scenario: Snapshot updates all views
- **WHEN** a refreshed server snapshot changes a Run stage or eligibility
- **THEN** all affected views reactively update without duplicate local copies or contradictory status labels

### Requirement: Explicit complete refresh
The navigation refresh action SHALL revalidate all observable data from the server, expose a transient synchronization indicator, and report failure without presenting stale data as current.

#### Scenario: Manual refresh succeeds
- **WHEN** the operator activates Refrescar
- **THEN** all observable collections are revalidated, the synchronization indicator is shown transiently, and the displayed timestamp reflects the completed refresh

#### Scenario: Manual refresh fails
- **WHEN** the server cannot be reached during refresh
- **THEN** the PWA marks the observation stale/offline, preserves the last timestamp, and does not claim synchronization success

### Requirement: Accessible light theme
The affected navigation, text, cards, focus indicators, and status badges SHALL meet WCAG AA contrast and remain operable in both light and dark themes.

#### Scenario: Light theme remains legible
- **WHEN** the operator selects light mode
- **THEN** sidebar, text, cards, controls, and focus states remain readable and distinguishable at the supported responsive breakpoints

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

### Requirement: Isolated on-demand configuration view lifecycle
Configuration views including `Proyectos` and `Admin Modelos` SHALL load authoritative collections strictly upon component mounting (`ngOnInit`) or following an explicit user mutation (saving, updating, or toggling). Background refresh events SHALL NOT reset form inputs, active modal dialogs, or dropdown selections while an operator is interacting with configuration views.

#### Scenario: Form stability during configuration editing
- **WHEN** an operator has an edit modal, create form, or model dropdown open in the Proyectos or Admin Modelos view
- **THEN** no background timer or SSE event overwrites the local component form signals, closes dialogs, or resets user selection

#### Scenario: Explicit mutation triggers scoped revalidation
- **WHEN** the operator submits a project configuration change or model enablement toggle successfully
- **THEN** the component revalidates its target collection and reflects the updated settings without re-triggering full-app polling

### Requirement: Optimistic human gate resolution
When the operator submits a clarification or resolution for an active `HUMAN_REQUIRED` gate, the PWA SHALL apply an optimistic update immediately hiding or resolving the gate card and displaying inline processing feedback without waiting for subsequent background network round-trips.

#### Scenario: Immediate human gate dismissal upon action
- **WHEN** the operator submits a valid clarification response or action for an active gate
- **THEN** the modal or attention banner is dismissed immediately and the UI communicates processing state without remaining visible for several seconds

### Requirement: Decoupled historical metrics caching
Historical cost series and analytics in the `Dashboard` SHALL be cached in-memory and revalidated on-demand or through an amortized window of at least 5 minutes, preventing high-frequency metric queries from saturating the network or degrading real-time run observation.

#### Scenario: Dashboard metrics reuse cached series
- **WHEN** navigating to or viewing the Dashboard within the amortized cache window
- **THEN** previously fetched cost series are rendered without executing immediate redundant HTTP requests to `/api/v1/dashboard/overview`
