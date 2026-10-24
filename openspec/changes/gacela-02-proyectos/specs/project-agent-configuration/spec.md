## Purpose
Let operators choose only verifiable agent capabilities and persist independent, project-scoped profiles for the four contract roles.

## ADDED Requirements

### Requirement: Agent catalog reflects executable installed capabilities
The agent catalog SHALL derive availability from configured adapters/CLIs and verifiable installed capabilities, including invocation transport, file-edit/read-only ability, compatible roles, discoverable model/effort choices, and the complete set of official OpenSpec skills/workflows available and compatible with the verified OpenSpec version. User input SHALL NOT be treated as an arbitrary agent, model, effort, command, workflow, or skill identifier.

#### Scenario: Discover a usable native coding agent
- **WHEN** an operator queries the catalog in a workspace with a configured agent CLI and installed native OpenSpec workflows
- **THEN** the catalog reports only the models, effort levels, transports, roles, and native workflow names actually verified there

#### Scenario: Text-only provider cannot perform file-editing role
- **WHEN** an operator selects an API that returns text only for a role requiring repository edits or native workflow execution
- **THEN** the selection is rejected as incompatible and no dispatch occurs

#### Scenario: Missing native workflow is not emulated
- **WHEN** a selected agent lacks a required official OpenSpec workflow or CLI prerequisite
- **THEN** the role/workflow is unavailable and mini me does not substitute a prompt, command alias, or Python workflow implementation

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
