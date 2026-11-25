# provider-model-administration-ui Specification

## Purpose

Give operators one Angular administration view for observing provider harnesses and models and configuring role assignments for a selected project through the existing project APIs.

## Requirements

### Requirement: Provider and model administration view
The Angular application SHALL expose an administration view that reads the authenticated administrative provider-model catalog and harness refresh results from the existing APIs. It SHALL show each observed harness with its returned status and summary, and show catalog models with provider, harness, discovery status, and persisted operator-enabled state. Refresh and toggle outcomes SHALL be rendered from API responses; the UI SHALL NOT simulate or locally invent persisted state.

#### Scenario: Show harness diagnostics and model state
- **WHEN** the operator opens the administration view and the catalog and refresh result are available
- **THEN** the view displays each harness status and its models with both discovery status and operator-enabled state clearly distinguished

#### Scenario: Persist a model toggle
- **WHEN** the operator toggles a model and the enablement operation succeeds
- **THEN** the view reflects the returned persisted enabled state and version

#### Scenario: Keep model state after toggle failure
- **WHEN** the enablement operation fails or returns a version conflict
- **THEN** the view retains the last server-confirmed state and shows the failure without reporting success

### Requirement: Global Watchdog settings in provider administration
The existing provider/model administration view SHALL expose the persisted global Watchdog provider/model, inactivity threshold, and operating mode from the Watchdog configuration API. The Watchdog model selector SHALL be transversal and independent of the focused project. Its choices SHALL be the union of (a) models enabled and available in the administration provider/model registry and (b) Codex and Antigravity models currently exposed as selectable stage models by the global agent catalog. The API SHALL accept and validate selections against those same sources and SHALL NOT accept an arbitrary model merely because its provider name is Codex or Antigravity.

#### Scenario: Load and save Watchdog settings
- **WHEN** an authorized operator opens provider administration and saves valid Watchdog settings
- **THEN** the view displays the server-confirmed provider/model, threshold, and mode
- **AND** refresh preserves the persisted values

#### Scenario: Show the transversal stage-capable model choices
- **WHEN** the operator opens the global Watchdog selector, regardless of the currently focused project
- **THEN** it includes enabled and available models from the administration registry
- **AND** it includes the Codex and Antigravity models currently exposed by the global agent catalog for stage assignment
- **AND** it does not depend on a particular project's profiles or include models absent from both sources

#### Scenario: Save a stage-capable Codex or Antigravity model
- **WHEN** the operator selects a Codex or Antigravity model exposed by the global agent catalog
- **THEN** the API validates the exact provider, harness, and canonical model identity against that catalog and persists the selection
- **AND** the selection remains global and is shown after refresh

#### Scenario: Save is rejected
- **WHEN** the API rejects an unavailable model or invalid threshold
- **THEN** the view retains the last server-confirmed settings and displays the returned error
- **AND** it does not claim the rejected settings were saved
