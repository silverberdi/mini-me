# project-agent-configuration Specification

## Purpose
Let operators choose only verifiable agent capabilities and persist independent, project-scoped profiles for the four contract roles.

## Requirements

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

### Requirement: Four independently configured project roles
Each project SHALL configure `thinking`, `execution`, `independent_review`, and `fallback` profiles with verified agent/provider, compatible model, supported effort, applicable native workflows, and references to installed skills. Thinking and execution SHALL default to medium effort where supported; sync/archive in future profiles use the minimum compatible effort. Fallback SHALL require explicit project authorization and a compatible workflow plus permitted budget. The project SHALL NOT enforce fixed Codex/Antigravity/DeepSeek/OpenRouter role pairings.

#### Scenario: Persist compatible independent profiles
- **WHEN** an operator saves four role profiles whose providers, models, effort, stages, skills, and workflows are discoverably compatible
- **THEN** mini me persists those selections against the project and uses the configured thinking role for the Greenfield context-preparation operation

#### Scenario: Reject incompatible model or effort
- **WHEN** a selected model or effort is not present in the live/configured capability evidence for that agent
- **THEN** project validation fails and the invalid profile is not used or silently downgraded

#### Scenario: Reject same-author review
- **WHEN** the selected independent reviewer resolves to the substantive author of a candidate
- **THEN** the review role is not accepted for that candidate and no self-review is presented as independent

#### Scenario: Paid fallback requires authorization
- **WHEN** a primary profile is unavailable and fallback is not explicitly enabled or its spending policy disallows the operation
- **THEN** no fallback invocation or provider charge occurs

### Requirement: Resolve each native OpenSpec workflow according to the selected agent
Workflow resolution SHALL inspect the verified OpenSpec version and the selected agent's complete installed compatible official skill/workflow set and CLI capability; provider-specific syntax and transport SHALL remain distinct. The selected role profile controls which verified operation is dispatched, not which official integrations are installed. mini me SHALL NOT generate OpenSpec artifacts or emulate propose/apply/verify/sync/archive. F2 SHALL validate profiles for future compatible stages but SHALL NOT run the F3 ticket lifecycle.

#### Scenario: Codex and Antigravity use their installed native commands
- **WHEN** configured agents expose different native OpenSpec invocation forms (for example Codex skill `$openspec-propose` and Antigravity `/opsx-propose`)
- **THEN** dispatch resolves each exact installed workflow and transport independently without requiring a shared command spelling

#### Scenario: Profile requests an uninstalled stage
- **WHEN** a project profile requires a workflow not installed or not supported by the chosen agent
- **THEN** the profile is blocked with verified capability evidence and no emulated workflow is run

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

### Requirement: Unified searchable model selection
Project creation and project editing SHALL share a single authoritative catalog source without displaying a temporary initial static list. The model selector in project configuration views SHALL expose exclusively models enabled by the operator (`is_enabled: true`) in the administrative registry across all active harnesses (Codex, Antigravity, OpenCode), be searchable by provider or model name, operable via keyboard, render a dropdown popup with at least 360px width without destructive truncation, and clearly display provider, model, and execution harness in both search results and active selection. Models that report distinct effort variants (such as Antigravity models with `-low`, `-medium`, `-high` suffixes) SHALL be deduplicated in the dropdown to present exactly one option per model family, while an independent radio control alongside the dropdown allows choosing the reasoning effort (Bajo, Medio, Alto). When saving, the system SHALL automatically map the base model selection and effort choice to the exact variant identifier required by the execution harness. Direct DeepSeek models executed through OpenCode SHALL be labeled explicitly as `DeepSeek — Flash (API directa vía OpenCode)` under the group `DeepSeek — API directa (vía OpenCode)`, making them searchable both by `deepseek` and by `opencode`. Project creation and editing forms SHALL validate reactively that all four required roles have valid resolved models before submission. When creation or edit submission fails due to validation or server errors, the actionable error feedback SHALL be rendered visibly inside the open modal above the action buttons, without requiring the operator to close the modal. Project creation SHALL construct autonomous canonical profiles for all four roles with explicit `provider_id` and `harness_id` properties without inheriting or reusing profiles from the currently focused project. Project editing SHALL only preserve an existing profile if it already contains valid canonical `provider_id` and `harness_id` definitions. The backend profile validation SHALL scope `CanonicalProfileResolver` verification exclusively to external provider models managed in the provider model registry without enforcing a 24-hour expiration on operator-enabled models, while installed local CLI harnesses (such as Codex and Antigravity) are validated authoritatively against verified installed capabilities via `ProjectCatalogService`.

#### Scenario: Single authoritative catalog on form open
- **WHEN** an operator opens the project creation or edit modal
- **THEN** the form renders the authoritative model catalog directly without flashing or substituting an initial static list

#### Scenario: Keyboard-operable model search
- **WHEN** the operator types into the model selector
- **THEN** the list filters instantly by provider or model name, allows arrow key navigation and Enter selection, and displays the chosen provider and model cleanly

#### Scenario: Only operator-enabled models appear in project selector
- **WHEN** an operator views the model selector in project configuration
- **THEN** only models marked as enabled in the administrative provider model registry appear, grouped by provider

#### Scenario: Independent reasoning effort selection without model duplication
- **WHEN** an operator configures a role in project creation or editing
- **THEN** each model family appears exactly once in the dropdown (deduplicating suffixed variants), and a radio control alongside the dropdown allows choosing the reasoning effort (Bajo, Medio, Alto) for that role

#### Scenario: Harness effort variant mapping upon profile submission
- **WHEN** an operator selects a model whose execution harness encodes effort into model slugs (such as Antigravity) and chooses an effort level
- **THEN** the persisted role profile receives the exact suffixed model identifier corresponding to that effort level and harness validation succeeds

#### Scenario: Project form blocks incomplete role configurations
- **WHEN** any of the four required roles lacks a resolved valid model
- **THEN** the form submission button is disabled and prevents sending incomplete role profiles to the backend

#### Scenario: Actionable error feedback visible inside open modal
- **WHEN** an operator submits a project creation or edit form that is rejected by the backend or fails validation
- **THEN** the error feedback is rendered visibly inside the open modal above the action buttons and the form remains open with user inputs preserved

#### Scenario: New project creation constructs complete canonical profiles
- **WHEN** an operator registers a new project
- **THEN** all four role profiles are generated with canonical `provider_id`, `harness_id`, and resolved `model_id` without inheriting legacy properties from the active project

#### Scenario: Edit project regenerates profiles lacking canonical attributes
- **WHEN** an operator edits a project whose existing profile lacks canonical `provider_id` or `harness_id`
- **THEN** the profile is regenerated with verified canonical provider and harness attributes before saving

#### Scenario: Backend validates local CLI harnesses and external registry models harmoniously
- **WHEN** a project is configured with a combination of local CLI harnesses (such as Codex or Antigravity) and external provider registry models (such as OpenCode/DeepSeek)
- **THEN** local CLI harnesses are validated against verified installed CLI capabilities while external provider models are validated against the provider model registry without false-positive catalog missing rejections

#### Scenario: Explicit OpenCode labeling for direct DeepSeek models
- **WHEN** an operator searches or inspects DeepSeek direct API models in the selector
- **THEN** the options and group explicitly include `(vía OpenCode)` and match searches for both `deepseek` and `opencode`

#### Scenario: Persistent validity of operator-enabled models without artificial stale expiration
- **WHEN** an operator configures a project using an enabled model from the provider model registry whose observation occurred more than 24 hours prior
- **THEN** profile resolution does not reject the model with a stale observation error and allows valid persistence
