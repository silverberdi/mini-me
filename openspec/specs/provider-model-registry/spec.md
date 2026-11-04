# provider-model-registry Specification

## Purpose
Proporciona un catálogo administrativo persistente y verificable de proveedores, harnesses y modelos disponibles, descubiertos o personalizados, para configurar roles sin depender de literales de código.

## Requirements

### Requirement: Persistent provider-model registry
The system SHALL persist provider, harness, model, canonical identifier, origin, maximum context, capabilities, discovery status, and diagnostic timestamp in `provider_model_registry`. It SHALL distinguish discovered, static-compatible, and operator-defined entries and SHALL NOT persist secret values.

#### Scenario: Persist a discovered model
- **WHEN** an authorized refresh observes a model from a configured harness
- **THEN** the registry upserts the canonical model identity and observable capabilities without creating duplicate entries

#### Scenario: Preserve direct and OpenCode namespaces
- **WHEN** the catalog contains a direct DeepSeek model and an OpenCode namespaced DeepSeek model
- **THEN** the entries remain distinct and their provider/harness routes are not conflated

### Requirement: Non-destructive catalog discovery
The system SHALL provide an authorized, bounded, idempotent refresh that introspects each configured supported CLI using read-only commands, records invocation outcome and diagnostics, and SHALL fail closed for timeout, unavailable CLI, malformed output, or unauthorized command.

#### Scenario: Refresh configured CLIs
- **WHEN** the operator requests a catalog refresh for a project with OpenCode and Ollama harnesses
- **THEN** the system invokes only the supported read-only introspection commands, persists successful observations, and reports each failure separately

#### Scenario: Discovery command is unavailable
- **WHEN** a configured CLI is missing or returns an ambiguous result
- **THEN** no model is marked available from that CLI and the diagnostic exposes the failure without substituting a hardcoded success

### Requirement: Administrative catalog and custom models API
The system SHALL expose authenticated `GET /api/v1/admin/providers/catalog` returning providers, harnesses, static, discovered, and custom models, and `POST /api/v1/admin/providers/models` to create or edit a custom model with canonical identifier, maximum context, origin provider, harness, and declared capabilities. The API SHALL validate identifiers and reject secret material.

#### Scenario: Read the live catalog
- **WHEN** an authorized operator requests the catalog
- **THEN** the response includes current registry entries and diagnostic state without project credentials or tokens

#### Scenario: Register a custom model
- **WHEN** an authorized operator submits `deepseek-chat`, `deepseek-reasoner`, or `openrouter/deepseek/deepseek-r1` with valid metadata
- **THEN** the model is created or updated idempotently under its canonical provider/harness route

#### Scenario: Reject secret-bearing model metadata
- **WHEN** a custom model payload contains a token, private key, or credential value
- **THEN** the request is rejected and no secret is written to PostgreSQL or logs

### Requirement: Credential and harness diagnostic
The system SHALL expose non-secret diagnostic facts for configured credentials, harness availability, permissions, command version, and last observed result. A failed or unobservable diagnostic SHALL be reported as unavailable or blocked and SHALL NOT be used to authorize execution.

#### Scenario: Valid credential diagnostic
- **WHEN** a configured harness credential and required read-only capability are verified
- **THEN** the catalog reports a successful non-secret diagnostic tied to that harness and provider

#### Scenario: Invalid credential diagnostic
- **WHEN** credential validation fails or required permissions cannot be observed
- **THEN** the catalog reports the actionable failure, does not try an unapproved substitute, and marks the related model unusable

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
