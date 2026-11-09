## MODIFIED Requirements

### Requirement: Unified searchable model selection
Project creation and project editing SHALL share a single authoritative catalog source without displaying a temporary initial static list. The model selector in project configuration views SHALL expose exclusively models enabled by the operator (`is_enabled: true`) in the administrative registry across all active harnesses (Codex, Antigravity, OpenCode), be searchable by provider or model name, operable via keyboard, render a dropdown popup with at least 360px width without destructive truncation, and clearly display provider, model, and execution harness in both search results and active selection. Models that report distinct effort variants (such as Antigravity models with `-low`, `-medium`, `-high` suffixes) SHALL be deduplicated in the dropdown to present exactly one option per model family, while an independent radio control alongside the dropdown allows choosing the reasoning effort (Bajo, Medio, Alto). When saving, the system SHALL automatically map the base model selection and effort choice to the exact variant identifier required by the execution harness. Project creation and editing forms SHALL validate reactively that all four required roles have valid resolved models before submission. When creation or edit submission fails due to validation or server errors, the actionable error feedback SHALL be rendered visibly inside the open modal above the action buttons, without requiring the operator to close the modal. Project creation SHALL construct autonomous canonical profiles for all four roles with explicit `provider_id` and `harness_id` properties without inheriting or reusing profiles from the currently focused project. Project editing SHALL only preserve an existing profile if it already contains valid canonical `provider_id` and `harness_id` definitions. The backend profile validation SHALL scope `CanonicalProfileResolver` verification exclusively to external provider models managed in the provider model registry, while installed local CLI harnesses (such as Codex and Antigravity) are validated authoritatively against verified installed capabilities via `ProjectCatalogService`.

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
