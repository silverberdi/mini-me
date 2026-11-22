## ADDED Requirements

### Requirement: Compact Active Change summary on Dashboard
The Dashboard SHALL replace its dense recent-run and open-request lists with one compact, responsive summary of the active Run for the selected project. The summary SHALL use the existing Run and Request data, show the Change name, linked Request number and title when available, current stage and execution status, the official illustration for a recognized current stage, a visual stage-progress indicator, and a direct link to Trabajo Actual. It SHALL show only progress supported by the current persisted stage; it SHALL NOT invent a numeric percentage or a separate orchestration state.

#### Scenario: Active Change is visible without a human gate
- **WHEN** the selected project has an active Run and no human gate is present
- **THEN** the Dashboard summary displays that Run's Change name, current stage, execution status, official stage illustration, and stage-progress indicator
- **AND** it provides a direct link to Trabajo Actual for that Run

#### Scenario: Linked Request is available
- **WHEN** the active Run refers to a Request present in the selected project's loaded Requests
- **THEN** the summary displays that Request's number and title alongside the Change

#### Scenario: Request details are unavailable
- **WHEN** the active Run has no linked Request or its Request is not present in the loaded data
- **THEN** the summary still displays the available Run and Change information
- **AND** it does not show a fabricated Request number or title

#### Scenario: No active Run
- **WHEN** the selected project has no active Run
- **THEN** the Dashboard displays “Sin ejecución activa en este momento”
- **AND** provides direct access to Backlog to start or review work

#### Scenario: Unknown stage
- **WHEN** the active Run reports a stage with no known presentation metadata
- **THEN** the summary displays the reported stage and execution status
- **AND** it does not display a guessed illustration or claim unsupported stage progress

#### Scenario: Responsive Dashboard presentation
- **WHEN** the operator views the Dashboard on mobile or desktop
- **THEN** the active Change name, stage, status, progress indicator, and navigation link remain legible and operable without horizontal page overflow

#### Scenario: Existing work views remain authoritative
- **WHEN** the Dashboard summary is rendered
- **THEN** it consumes the selected project's existing Run data and links to the existing Trabajo Actual and Backlog routes
- **AND** it does not change the behavior of Trabajo, Trabajo Actual, or Backlog
