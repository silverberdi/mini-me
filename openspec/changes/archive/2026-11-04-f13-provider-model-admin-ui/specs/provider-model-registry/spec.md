## ADDED Requirements

### Requirement: Operator-controlled model enablement
Each provider-model registry entry SHALL persist an operator-controlled `is_enabled` state independently from `discovery_status`. Existing entries SHALL default to enabled during migration to preserve their prior operator availability. The administrative catalog SHALL expose the persisted state, and an authenticated version-checked operation SHALL enable or disable an entry and return its persisted state and version. Changing this state SHALL NOT alter discovery status or diagnostic evidence. Disabled models SHALL remain visible in the catalog but SHALL NOT be accepted for new role assignments or resolved for execution.

#### Scenario: Disable a catalog model
- **WHEN** an authorized operator disables an enabled model using its current version
- **THEN** the registry persists `is_enabled=false`, increments the version, and returns the disabled model in the catalog with its discovery status unchanged

#### Scenario: Reject a stale toggle
- **WHEN** an operator submits an enablement change with a stale registry version
- **THEN** the operation returns a conflict and preserves the current enabled state and version

#### Scenario: Keep disabled model out of role resolution
- **WHEN** a project role references a model whose operator state is disabled
- **THEN** profile validation or runtime resolution rejects the model while preserving the project profile and discovery diagnostic

#### Scenario: Re-enable a model without rewriting discovery
- **WHEN** an authorized operator enables a disabled model using its current version
- **THEN** the registry persists `is_enabled=true` while retaining the existing `discovery_status` and diagnostic evidence
