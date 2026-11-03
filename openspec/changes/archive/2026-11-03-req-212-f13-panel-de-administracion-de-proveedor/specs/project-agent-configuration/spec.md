# Spec Delta

## ADDED Requirements

### Requirement: Role profiles resolve from the live model catalog

Project role profiles SHALL resolve provider, harness, model, effort, and route from the live provider-model registry when available, while retaining the existing four independent roles and all legacy symbols with live consumers. A profile SHALL be rejected when its model is absent, stale, or incompatible with the role capability.

#### Scenario: Configure compatible roles
- **WHEN** an operator selects catalog entries with file-edit capability for `implementer` and read-only capability for `reviewer`
- **THEN** the project profiles persist those exact provider-model-harness combinations and the next Run resolves the same combinations

#### Scenario: Reject an incompatible reviewer or implementer
- **WHEN** an operator assigns a model lacking read-only review or file-edit capability to the corresponding role
- **THEN** validation fails before persistence or dispatch and reports the missing capability

#### Scenario: Preserve legacy catalog consumers
- **WHEN** the live catalog is queried or a legacy resolver is called
- **THEN** `SUPPORTED_PROVIDER_MODELS`, `SUPPORTED_PROVIDER_EFFORTS`, `DEFAULT_R01_STAGE_PROFILES`, `resolve_stage_profile`, `resolve_cli_invocation`, `agy_model_effort_variant`, `ProjectCatalogService.provider_catalog`, `ProjectCatalogService.agent_catalog`, `ProjectCatalogService.validate_project_profiles`, `OPENCODE_DEEPSEEK_MODELS`, and their aliases remain available with compatible behavior

### Requirement: UI model mappings use catalog routes

The UI-facing `resolveAgentForModel`, `buildProfile`, and `getRoleModel` behavior SHALL derive provider and role mappings from the live catalog and `model_routes`, and SHALL not select an agent through substring or legacy literal matching when a canonical catalog route exists.

#### Scenario: Resolve a custom routed model
- **WHEN** a custom model is selected from the catalog with a verified `model_routes` entry
- **THEN** all three UI mapping operations resolve the same canonical provider, harness, model, and role constraints

#### Scenario: Unknown route fails closed
- **WHEN** a UI model identifier has no live catalog or route entry
- **THEN** the mapping returns a visible validation error and does not silently infer a provider from a substring

