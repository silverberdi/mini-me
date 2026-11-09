## MODIFIED Requirements

### Requirement: Unified searchable model selection
Project creation and project editing SHALL share a single authoritative catalog source without displaying a temporary initial static list. The model selector in project configuration views SHALL expose exclusively models enabled by the operator (`is_enabled: true`) in the administrative registry across all active harnesses (Codex, Antigravity, OpenCode), be searchable by provider or model name, operable via keyboard, render a dropdown popup with at least 360px width without destructive truncation, and clearly display provider, model, and execution harness in both search results and active selection. Reasoning effort SHALL be selected via independent radio controls alongside each role selector without duplicating model entries in the dropdown. Project creation and editing forms SHALL validate reactively that all four required roles have valid resolved models before submission.

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
- **THEN** each model appears once in the dropdown, and a radio control alongside the dropdown allows choosing the reasoning effort (Bajo, Medio, Alto) for that role

#### Scenario: Project form blocks incomplete role configurations
- **WHEN** any of the four required roles lacks a resolved valid model
- **THEN** the form submission button is disabled and prevents sending incomplete role profiles to the backend
