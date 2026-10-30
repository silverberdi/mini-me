# Spec Delta

## MODIFIED Requirements

### Requirement: PWA Application Shell and Navigation
The system SHALL provide one Spanish web application with exactly five independent routed views: Dashboard, Trabajo, Trabajo actual, Proyectos and Backlog. Only Dashboard and Proyectos SHALL be primary navigation destinations. Dashboard SHALL link to Trabajo and Trabajo actual; Trabajo SHALL link to Trabajo actual; selected project detail SHALL link to its Backlog. Deep links, refresh, back and forward SHALL preserve authorized context. One bootstrap and one refresh lifecycle SHALL serve all views, with manual and 5s/10s/30s refresh options and no mutation during polling. A future frontend implementation MAY replace the legacy JavaScript view layer with Angular and TypeScript, but SHALL preserve these observable routes, navigation destinations and lifecycle guarantees without enabling F8 by this planning Change.

#### Scenario: View application shell with live health indicators
- **WHEN** the authenticated application initializes
- **THEN** it renders the brand header, backend connection state, compact health indicators and manual/5s/10s/30s refresh controls; scheduler and database health show only verified observations, with unavailable or stale sources explicitly labeled.

#### Scenario: Toggle auto-refresh interval
- **WHEN** the operator selects 5s while the application is polling at 10s
- **THEN** the single polling timer changes to 5s and performs an immediate read without sending a mutation.

#### Scenario: Navigate five independent views
- **WHEN** the operator follows Dashboard → Trabajo → Trabajo actual and Proyectos → selected project → Backlog
- **THEN** each destination has its own URL and content, with exactly two primary destinations and no stacked Home screens, regardless of whether the current frontend is legacy JavaScript or the future Angular implementation.

#### Scenario: Reload a contextual deep link
- **WHEN** an authenticated operator reloads or traverses browser history for a project, Request, Run or stage link
- **THEN** the same authorized selection is restored and missing or forbidden identities produce an explicit error without silently selecting another Run.

#### Scenario: Change refresh interval without duplication
- **WHEN** the operator changes from 10s to 5s while switching views
- **THEN** a single refresh lifecycle uses 5s, performs an immediate read and neither duplicates listeners nor starts work.

### Requirement: KPI Summary Overview Grid
The system SHALL present Dashboard for an explicitly identified project in focus, with analog project and current Request/task progress gauges, model quota gauges, completed-Request effectiveness, and compact human attention and operational health. Every measured value SHALL expose source, unit, scope, observation time and freshness. Percentages SHALL require a verified numerator and denominator; absent data SHALL be labeled No disponible, never zero or fabricated. Administrative ACTIVE SHALL NOT imply a global executor selection or a started Run. A frontend migration SHALL preserve the same verified data semantics and SHALL NOT move KPI authority or calculations into the client.

#### Scenario: Render KPI summary with active executions
- **WHEN** authoritative observations identify an active Run and one unresolved HUMAN_REQUIRED for the focused project
- **THEN** Dashboard shows the actual work state and attention count of one with source and freshness, links to Trabajo actual, and displays progress only where verified counts and denominators exist; a legacy NEEDS_HUMAN label alone does not establish a human request.

#### Scenario: Progress with and without a denominator
- **WHEN** Request tasks have verified completed/applicable counts but project objectives have no authoritative denominator
- **THEN** only Request progress shows a percentage with its counts and source, and the project gauge shows No disponible with a reason.

#### Scenario: Quota is not subscription capacity
- **WHEN** model usage provides tokens or cost but no verified quota limit and period
- **THEN** the gauge area shows measured units or No disponible, without quota percentages, invented renewal dates or attributing usage to a default model.

#### Scenario: Inspect real quota by model
- **WHEN** a provider publishes verified model usage, limit, period and renewal
- **THEN** the operator sees consumed and remaining quota for that model with the source, period and observation time.

#### Scenario: Health and attention are distinct
- **WHEN** scheduler state, provider capacity or health is unavailable, stale, intentionally disabled or WAITING_CAPACITY
- **THEN** the compact health area describes that fact, distinguishes physical scheduler state from logical admission, and does not create a HUMAN_REQUIRED notification without a real request.

### Requirement: Effectiveness Dimensions for Completed Requests
The system SHALL provide selectable line-chart dimensions for quality/autonomy, time, and measured AI resources per completed Request, with separate scales and explicit missing-data states. Quality SHALL distinguish avoidable clarification/correction iterations from mandatory authorization gates; time SHALL distinguish total, active and waiting duration; resources SHALL preserve provider/model attribution and actual measured units. A future frontend migration SHALL preserve the chart's three dimensions, traceability and missing-data semantics without inventing client-side measurements.

#### Scenario: Compare measured history
- **WHEN** the operator changes the effectiveness dimension over completed Requests
- **THEN** the graph shows attributable observations on the selected scale without combining incompatible units or penalizing mandatory approvals as avoidable corrections.

#### Scenario: Instrumentation is absent
- **WHEN** no verified observations support a selected dimension
- **THEN** the graph is empty with an explanation Pendiente de datos — F7, and no demonstration points or inferred durations appear.

### Requirement: Honest Global Pause Control
The system SHALL display Pausar mini me with its deferred semantics, but SHALL keep it non-actionable with Disponible en F7 when global deferred-pause authority is absent. A future frontend migration SHALL preserve this disabled state and explanation and SHALL NOT add pause authority.

#### Scenario: Pause lacks authority
- **WHEN** the operator inspects Pausar mini me without a supported backend capability
- **THEN** its accessible explanation says pause would occur after the full Change, PR2 and closure, and no pause request or success confirmation is emitted.
