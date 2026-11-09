## MODIFIED Requirements

### Requirement: PWA Application Shell and Navigation
The system SHALL provide one Spanish web application with exactly five independent routed views: Dashboard, Trabajo, Trabajo actual, Proyectos and Backlog. Only Dashboard and Proyectos SHALL be primary navigation destinations. Dashboard SHALL link to Trabajo and Trabajo actual; Trabajo SHALL link to Trabajo actual; selected project detail SHALL link to its Backlog. Deep links, back and forward SHALL preserve authorized context. One reactive event lifecycle and initial bootstrap SHALL serve all views without redundant manual refresh controls or periodic polling spinners. The client connection state SHALL reflect true network availability (`navigator.onLine`) and core server reachability, and SHALL NOT oscillate to a disconnected state during normal SSE reconnect cycles or transient secondary endpoint background failures. The operator's manual project selection SHALL be durably persisted in `localStorage` across page reloads, route changes, and SSE event cycles, and SHALL NOT be reset automatically to default or active project fallbacks.

#### Scenario: View application shell with live health indicators
- **WHEN** the authenticated application initializes
- **THEN** it renders the brand header, stable backend connection indicator, compact health indicators and active project selector without manual refresh buttons or polling interval controls; scheduler and database health show only verified observations, with unavailable or stale sources explicitly labeled.

#### Scenario: Background SSE reconnect preserves connected indicator
- **WHEN** the server-sent events stream reconnects or experiences a transient transport interruption while browser network connectivity is active and core endpoints respond
- **THEN** the application maintains its connected state and does not flash or latch the transversal disconnection banner.

#### Scenario: Toggle auto-refresh interval
- **WHEN** the operator navigates between views or routes
- **THEN** updates are delivered reactively without requiring or rendering interval toggle controls and without sending polling mutations.

#### Scenario: Navigate five independent views
- **WHEN** the operator follows Dashboard → Trabajo → Trabajo actual and Proyectos → selected project → Backlog
- **THEN** each destination has its own URL and content, with exactly two primary destinations and no stacked Home screens.

#### Scenario: Reload a contextual deep link
- **WHEN** an authenticated operator reloads or traverses browser history for a project, Request, Run or stage link
- **THEN** the same authorized selection is restored and missing or forbidden identities produce an explicit error without silently selecting another Run.

#### Scenario: Change refresh interval without duplication
- **WHEN** the operator switches views while real-time execution events arrive
- **THEN** a single reactive event lifecycle handles updates and neither duplicates listeners nor starts background polling loops.

#### Scenario: Persistent operator project selection
- **WHEN** the operator selects a project in the application shell or project views
- **THEN** the selection is stored in `localStorage`
- **AND** subsequent background updates, route navigation, or page reloads preserve the operator's explicitly selected project without resetting to an arbitrary active project.
