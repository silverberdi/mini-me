# pwa-capacity-cards-and-reactive-state Specification Delta

## MODIFIED Requirements

### Requirement: Real-time reactive updates via EventSource
The PWA `RefreshService` SHALL subscribe to the existing authenticated Server-Sent Events stream `/api/v1/events` and immediately refresh server-backed state for runs, gates, projects, and Requests when their relevant events arrive without running a global blind periodic timer. Successful project or global pause/resume operations SHALL publish `project.pause_changed`; successful Request creation, deactivation, and reactivation SHALL publish `request.created`, `request.deactivated`, and `request.reactivated`; acceptance of an operator gate response SHALL publish `run.gate_acknowledged` before the coordinator's subsequent agent work completes. Run transitions and capacity updates SHALL continue to use the existing stream. Events SHALL identify the affected scope/entity without carrying secrets or replacing authoritative API projections. The PWA SHALL NOT use a periodic unprompted global interval timer to re-fetch state while operators are interacting with configuration screens or forms.

#### Scenario: Run transition updates UI without polling delay
- **WHEN** an SSE event arrives indicating a run stage transition or `HUMAN_REQUIRED`
- **THEN** `RefreshService` updates its signals immediately, reflecting the new stage and rendering human gate cards without waiting for a polling interval

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
- **THEN** the PWA reflects the disconnected connectivity state and EventSource reconnects automatically without unprompted periodic polling disrupting configuration views

#### Scenario: Absence of unprompted periodic timer
- **WHEN** the operator is on any screen of the PWA
- **THEN** no background global interval timer triggers unrequested HTTP requests across all collections

## ADDED Requirements

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
