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

### Requirement: Configure provider and model for project roles
The administration view SHALL let the operator select an existing project and assign a provider/model pair to the `thinker`, `implementer`, and `reviewer` roles, mapping them to the existing `thinking`, `execution`, and `independent_review` profile keys. It SHALL load and persist these assignments through the existing project configuration API and SHALL show the saved server response. It SHALL NOT create a separate persisted role store or modify the project's `fallback` profile.

#### Scenario: Save selected project role assignments
- **WHEN** the operator saves valid provider/model selections for the three roles on the selected project
- **THEN** the existing project endpoint persists the matching canonical profile keys and the view reflects the returned project configuration

#### Scenario: Reject unavailable model assignment
- **WHEN** the selected model is disabled, unavailable, or lacks the role capability
- **THEN** the save is rejected by the existing validation contract, the view retains the last server-confirmed assignment, and no success is shown

### Requirement: Defer credential testing to its owning issue
The administration view SHALL render a “Test Connection” control for provider entries, but SHALL NOT invoke credential testing or claim a test result as part of this capability. Credential diagnosis remains owned by Issue #254.

#### Scenario: Render connection test handoff
- **WHEN** the operator views a provider in the administration panel
- **THEN** the “Test Connection” control is visible and does not invoke a credential diagnostic operation
