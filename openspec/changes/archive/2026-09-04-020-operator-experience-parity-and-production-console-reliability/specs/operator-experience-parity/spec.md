# spec: operator-experience-parity

## Purpose
Expose all governed operator actions, dynamic parameter modals, action safety confirmations, provider efficiency metrics, and action audit logs within the PWA, ensuring full operational parity with the TUI on desktop and tablet devices.

## Requirements

### Requirement 1: Canonical Action Discovery & Execution Parity
The PWA MUST dynamically discover eligible actions for an orchestration run via `/api/v1/control-plane/actions/available?run_id={run_id}` and render appropriate buttons in the action toolbar.
- Enabled actions MUST be clickable.
- Disabled actions MUST display the disabled reason in a tooltip or disabled state.
- When clicked, the PWA MUST send a structured `OperatorActionRequest` payload containing `project_id`, `change_name`, `run_id`, `action_type`, `expected_stage`, `expected_generation`, `expected_candidate_sha`, and `parameters`.

#### Scenario: Discovering and rendering actions for active run
- **GIVEN** a run in state `NEEDS_HUMAN` at gate `HUMAN_APPROVAL`
- **WHEN** the operator views the run detail in the PWA
- **THEN** the action toolbar displays `Resolve Gate`, `Continue / Resume`, and `Cancel Run`
- **AND** disabled actions indicate their refusal reason.

### Requirement 2: Parameter Modals & Dangerous Action Confirmation
The PWA MUST provide interactive parameter input dialogs for actions requiring parameters and explicit confirmation for dangerous/high-impact actions.
- `REASSIGN`: Modal displays selectable target executors (`codex`, `antigravity`) and optional reason.
- `RESOLVE_GATE`: Modal displays decision options (`APPROVED`, `REJECTED`, `OVERRIDDEN`) and resolution notes.
- `RETRY`: Modal displays retry stage options.
- `CANCEL`, `RECOVER_LOCKS`, `RECONCILE_POST_MERGE`: Confirmation modal displays target change/run, impact warning, and requires confirmation.

#### Scenario: Operator cancels active run with confirmation
- **GIVEN** an active run in stage `IMPLEMENTING`
- **WHEN** the operator clicks `Cancel Run`
- **THEN** a modal appears with title "Confirm Action: Cancel Run", showing the change name and impact warning
- **WHEN** the operator confirms
- **THEN** `POST /api/v1/control-plane/actions/execute` is called with action `cancel`
- **AND** the PWA refreshes to reflect the cancelled state.

### Requirement 3: Action Audit History Tab
The PWA detail panel MUST include an `Action History` tab displaying all historical operator action records for the run fetched from `/api/v1/runs/{run_id}/actions/history`.
- Displays action type, actor identity, timestamp, result status (`SUCCESS`, `REJECTED`, `FAILED`), and error explanation if rejected.

#### Scenario: Viewing action audit trail
- **GIVEN** a run with past operator interactions
- **WHEN** the operator selects the `Action History` tab
- **THEN** the list of historical action records is rendered chronologically with operator identity and outcome.

### Requirement 4: Provider Efficiency & Telemetry Tab
The PWA detail panel MUST include a `Provider Efficiency` tab querying `/api/v1/efficiency/{project_id}/{change_name}`.
- Displays productive attempt ratio, total tokens / cost, model breakdown, reviewer independence verification, and anti-loop enforcement facts.

#### Scenario: Inspecting provider efficiency metrics
- **GIVEN** a completed or in-progress change
- **WHEN** the operator clicks the `Provider Efficiency` tab
- **THEN** aggregated metrics and attempt telemetry are clearly visualized in KPI cards and breakdowns.

### Requirement 5: Responsive Layout Across Devices
The PWA MUST support responsive rendering across Desktop (>= 1366px, 1920px, 2560px), Tablet (768px - 1024px), and Mobile (< 768px).
- Desktop: Master/detail 2-column layout with persistent action toolbar and progressive disclosure.
- Tablet: Fluid split view with touch targets >= 44px.
- Mobile: Vertical stack prioritizing overview, attention banner, human gates, and quick approval actions.
