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
