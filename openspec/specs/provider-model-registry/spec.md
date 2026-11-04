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
The system SHALL provide authenticated, non-secret diagnostic facts for configured model-provider credentials and harness availability, including permission, command-version, and last-observed facts where the configured provider exposes them. It SHALL expose `POST /api/v1/admin/providers/{provider}/test` for provider IDs represented in the administrative model catalog and configured at runtime. The endpoint SHALL use only an explicitly supported bounded check that does not invoke model inference or materially consume provider budget; it SHALL report an unavailable status when no such check exists. A diagnostic response SHALL include a status, latency in milliseconds when a check ran, and sanitized detail. A failed or unobservable diagnostic SHALL NOT authorize execution. Diagnostics SHALL NOT persist or return secret values, authorization headers, raw provider response bodies, or unsanitized exception text.

#### Scenario: Valid credential diagnostic
- **WHEN** an authenticated operator tests a configured catalog provider and its supported non-inference authentication check succeeds
- **THEN** the response reports success, the measured latency, and non-secret diagnostic detail for that provider

#### Scenario: Invalid credential diagnostic
- **WHEN** an authenticated operator tests a configured catalog provider and the provider rejects its credential
- **THEN** the response reports failure with sanitized actionable detail, does not expose credential material, and does not authorize execution

#### Scenario: Unsupported inexpensive check
- **WHEN** an authenticated operator tests a configured catalog provider for which no bounded non-inference check is supported
- **THEN** the response reports unavailable without attempting an inference or another costly operation

#### Scenario: Reject an unconfigured provider
- **WHEN** an authenticated operator tests a provider ID that is absent from the model catalog or runtime configuration
- **THEN** the endpoint rejects the request without dispatching a provider operation

#### Scenario: Require an authenticated operator
- **WHEN** a request to test a provider has no valid authorized operator session
- **THEN** the endpoint rejects the request and performs no diagnostic

#### Scenario: Sanitize provider failure data
- **WHEN** a provider response or exception contains a token, key, credential, authorization header, or raw body
- **THEN** the diagnostic response contains only a bounded sanitized status/detail and latency, with no secret-bearing source text

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
