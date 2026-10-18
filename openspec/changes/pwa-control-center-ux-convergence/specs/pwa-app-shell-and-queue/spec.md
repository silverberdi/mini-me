## MODIFIED Requirements

### Requirement: PWA Application Shell and Navigation
The system SHALL serve one authenticated, Spanish-language Control Center shell at the existing dashboard routes. It SHALL provide coherent navigation for Centro de Control, Backlog/Cola, Runs, Proyectos, Proveedores, Actividad y Métricas, preserve supported theme preferences, and expose API connectivity and refresh state. Scheduler service state (when authoritatively available) SHALL be shown separately from logical admission mode; absent or stale service evidence SHALL be shown as `UNKNOWN`, never inferred from the logical mode. The shell SHALL retain the existing OAuth/session flow and shall not expose operational data when authentication is absent or rejected.

#### Scenario: Load authenticated Control Center with distinct scheduler authorities
Given the operator has a valid authenticated session and API responses report a scheduler service state and a separate logical admission mode
When the operator opens the dashboard
Then the Spanish shell SHALL identify both values as separate statuses with source freshness
And it SHALL render navigation and theme controls without presenting illustrative reference-image values as live data.

#### Scenario: View application shell with live health indicators
Given the PWA Control Center is loaded in an authenticated browser and the current API responses include system health
When the application initializes
Then the shell SHALL render only the returned API/database and logical scheduler values with their labels
And any scheduler process lifecycle value absent from the response SHALL remain `UNKNOWN`.

#### Scenario: Toggle auto-refresh interval
Given the PWA Control Center is polling at an offered interval
When the operator selects another supported interval
Then the client SHALL apply that interval and request a fresh API snapshot
And it SHALL NOT claim the snapshot is current until the request succeeds.

#### Scenario: Missing scheduler service observation
Given the scheduler status API reports a logical admission mode but no authoritative service lifecycle observation
When the dashboard shell renders
Then the service lifecycle SHALL be displayed as `UNKNOWN` or not exposed
And the logical admission mode SHALL remain separately visible without implying that the scheduler process is active or enabled.

#### Scenario: Unauthenticated and expired session
Given the operator has no valid session or receives an authentication rejection
When the shell initializes or a session expires during use
Then protected operational content SHALL be hidden
And the interface SHALL present the existing sign-in or session-expired state without retaining stale data as current.

### Requirement: KPI Summary Overview Grid
The system SHALL display only summary counts and health values returned by the authoritative dashboard/read-model APIs. Each unavailable, stale, or unsupported value SHALL be represented as unavailable or `UNKNOWN`; the client SHALL NOT derive operational counts, total historical completion, service state, or health by interpreting unrelated fields.

#### Scenario: Render live overview facts
Given the dashboard overview returns active executions, attention items, recent completions, and explicit system health
When the authenticated overview is rendered
Then each displayed metric SHALL correspond to a field in that response and SHALL expose its meaning in text, not color alone.

#### Scenario: Render KPI summary with active executions
Given the overview API returns active execution and attention-item records
And a canonical run is in progress while another record requires human attention
When the KPI summary renders
Then its active and attention counts SHALL be derived from the corresponding returned records
And it SHALL NOT infer a total completed/merged count unless that exact metric is returned.

#### Scenario: Missing or stale summary field
Given a summary field is absent, stale, or has no authoritative source
When the KPI grid renders
Then the field SHALL display `UNKNOWN` or unavailable
And it SHALL NOT be replaced by a hardcoded value, zero, or a value inferred from another metric.

### Requirement: Autonomous Queue Prioritization Telemetry
The system SHALL present queue ordering, eligibility, priority, dependency and refusal explanations from the canonical queue and explainability read models. The browser SHALL NOT calculate scheduler priority, capacity, dependency completion, or admission eligibility. Unsupported score components SHALL be omitted or shown as unavailable.

#### Scenario: Inspect canonical queue ordering and explanation
Given the queue API returns ordered items and an explainability report for a bound project/change
When the operator inspects the queue item
Then the UI SHALL preserve the server order and show only score components, dependencies and reasons present in the response.

#### Scenario: Inspect ranked queue candidates and explainability
Given the server returns two ordered candidate items and an explanation for the selected item
When the operator inspects the queue
Then item order SHALL match the server response
And only server-provided priority components and admission explanations SHALL be shown.

#### Scenario: Display blocked reason for ineligible queue item
Given the queue API identifies a candidate as ineligible and returns a refusal reason
When the candidate is inspected
Then the UI SHALL display that exact refusal reason
And SHALL NOT synthesize a roadmap, provider, or concurrency code.

#### Scenario: Queue eligibility is unknown
Given the API cannot determine current admission eligibility or returns a transport/authentication error
When the queue view refreshes
Then the UI SHALL show a stale, unavailable, or `UNKNOWN` state
And SHALL NOT label an item READY or BLOCKED based only on missing values or visual styling.

#### Scenario: Project filter cannot authorize repository selection
Given a project selector or displayed GitHub text is changed
When queue data is requested
Then the request SHALL use an authorized project identifier and server binding
And SHALL NOT infer or change repository authority from a title, label, Project field, or prose.

## ADDED Requirements

### Requirement: Single PWA Runtime Coordinator
The authenticated shell SHALL have exactly one active client runtime coordinator responsible for application initialization, operational state subscriptions, telemetry polling/refresh scheduling, visibility/reconnection refresh, and each control's event-listener registration. A control SHALL have one listener owner; navigation or reconnection SHALL NOT register duplicate pollers, subscriptions or listeners.

#### Scenario: Initialize exactly one operational refresh owner
Given the dashboard HTML is loaded with its supported scripts
When the authenticated PWA initializes and renders its first snapshot
Then exactly one coordinator SHALL own telemetry polling, refresh and visibility/reconnection listeners
And no legacy controller and modular bootstrap SHALL concurrently refresh or render the same operational panels.

#### Scenario: Repeated navigation and reconnection do not duplicate listeners
Given the operator navigates between shell views and the API disconnects and reconnects
When the runtime reactivates panels and refreshes data
Then each control SHALL produce at most one corresponding action request per user activation
And the client SHALL maintain one polling schedule and one state subscription per coordinator.
