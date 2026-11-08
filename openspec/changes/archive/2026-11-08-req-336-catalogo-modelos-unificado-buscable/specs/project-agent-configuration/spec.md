# project-agent-configuration Specification Delta

## MODIFIED Requirements

### Requirement: Agent catalog reflects executable installed capabilities
The agent catalog SHALL derive availability from configured adapters/CLIs and verifiable installed capabilities, including invocation transport, file-edit/read-only ability, compatible roles, discoverable model/effort choices, and the complete set of official OpenSpec skills/workflows available and compatible with the verified OpenSpec version. User input SHALL NOT be treated as an arbitrary agent, model, effort, command, workflow, or skill identifier. The agent catalog SHALL only expose models from execution harnesses (such as OpenCode) whose upstream provider credentials and access are actively configured and verified; it SHALL NOT expose unconfigured provider models, nor native OpenCode models when native service access is unconfigured. The catalog SHALL be cached in memory to prevent executing discovery CLI commands repeatedly upon opening configuration views.

#### Scenario: Discover a usable native coding agent
- **WHEN** an operator queries the catalog in a workspace with a configured agent CLI and installed native OpenSpec workflows
- **THEN** the catalog reports only the models, effort levels, transports, roles, and native workflow names actually verified there

#### Scenario: Text-only provider cannot perform file-editing role
- **WHEN** an operator selects an API that returns text only for a role requiring repository edits or native workflow execution
- **THEN** the selection is rejected as incompatible and no dispatch occurs

#### Scenario: Missing native workflow is not emulated
- **WHEN** a selected agent lacks a required official OpenSpec workflow or CLI prerequisite
- **THEN** the role/workflow is unavailable and mini me does not substitute a prompt, command alias, or Python workflow implementation

#### Scenario: Omit unconfigured provider models from catalog discovery
- **WHEN** an execution harness reports models for an upstream provider that lacks configured API keys or credentials
- **THEN** those models are omitted from the exposed catalog and cannot be selected

#### Scenario: Backend caches discovered agent catalog across view opens
- **WHEN** the operator opens project creation or edit views multiple times without configuration changes
- **THEN** the cached model catalog is returned without re-executing CLI discovery processes

### Requirement: UI model mappings use catalog routes
The UI-facing `resolveAgentForModel`, `buildProfile`, and `getRoleModel` behavior SHALL derive provider and role mappings from the live catalog and `model_routes`, and SHALL not select an agent through substring or legacy literal matching when a canonical catalog route exists. OpenRouter SHALL be presented as an upstream provider with its own models and credentials, and DeepSeek direct SHALL remain distinct from DeepSeek via OpenRouter without conflating prefixes.

#### Scenario: Resolve a custom routed model
- **WHEN** a custom model is selected from the catalog with a verified `model_routes` entry
- **THEN** all three UI mapping operations resolve the same canonical provider, harness, model, and role constraints

#### Scenario: Unknown route fails closed
- **WHEN** a UI model identifier has no live catalog or route entry
- **THEN** the mapping returns a visible validation error and does not silently infer a provider from a substring

#### Scenario: OpenRouter models preserve upstream identity
- **WHEN** an OpenRouter model such as Claude or Qwen is selected
- **THEN** the UI identifies the provider as OpenRouter, preserves the upstream model name, and does not prepend DeepSeek to the model label

## ADDED Requirements

### Requirement: Unified searchable model selection
Project creation and project editing SHALL share a single authoritative catalog source without displaying a temporary initial static list. The model selector in project configuration views SHALL be searchable by provider or model name, operable via keyboard, and clearly display provider, model, and execution harness in both search results and active selection.

#### Scenario: Single authoritative catalog on form open
- **WHEN** an operator opens the project creation or edit modal
- **THEN** the form renders the authoritative model catalog directly without flashing or substituting an initial static list

#### Scenario: Keyboard-operable model search
- **WHEN** the operator types into the model selector
- **THEN** the list filters instantly by provider or model name, allows arrow key navigation and Enter selection, and displays the chosen provider and model cleanly
