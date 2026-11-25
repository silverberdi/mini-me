## ADDED Requirements

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
