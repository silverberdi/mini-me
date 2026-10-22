## MODIFIED Requirements

### Requirement: Required project policy
Project registration SHALL capture project type, immutable canonical repository identity, configured main branch, separate provider connections, four compatible agent-role profiles, applicable finite execution policy, and truthful onboarding/lifecycle status. A Greenfield project SHALL also provide a valid context ZIP before any project row is committed. A Brownfield project is configuration-only and SHALL NOT be reported prepared.

#### Scenario: Required project configuration is incomplete
- **WHEN** a registration request omits type, repository, branch, provider connection, or a required compatible role profile
- **THEN** validation rejects it structurally and the project is not executable or prepared

#### Scenario: Required project policy is incomplete
- **GIVEN** a project registration request missing a required configuration field
- **WHEN** registration is validated
- **THEN** the project is not considered executable or prepared
- **AND** the missing field is reported structurally

#### Scenario: Greenfield ZIP is missing or invalid
- **WHEN** Greenfield registration omits a valid ZIP
- **THEN** registration fails before project persistence or any external mutation

#### Scenario: Brownfield configuration is saved
- **WHEN** a Brownfield project has valid required configuration
- **THEN** it is saved as configured only, with no Greenfield bootstrap or adaptation

## REMOVED Requirements

### Requirement: Complementary primary roles

## ADDED Requirements

### Requirement: Project type, repository configuration, and lifecycle
Every project SHALL have an immutable project id and canonical repository identity, an explicit `GREENFIELD` or `BROWNFIELD` type, and an operator-configured main branch (defaulting to `main`). The project SHALL expose truthful onboarding status separately from active/paused lifecycle status. A Brownfield project SHALL remain merely configured until a separately authorized phase defines its adaptation; pausing SHALL prevent new work, and activation SHALL NOT start F3 ticket processing or a scheduler.

#### Scenario: Register a Greenfield project with a valid context package
- **WHEN** an authenticated operator submits a valid project type, project id, repository URL, branch, provider/agent configurations, permissions, and ZIP package
- **THEN** mini me validates them before persisting one project and begins the durable onboarding operation without changing the main branch

#### Scenario: Reject Greenfield creation without a valid ZIP
- **WHEN** a Greenfield create request has no ZIP or an invalid/unsafe ZIP
- **THEN** the request is rejected before a project or onboarding record is committed and before Git, agent, or GitHub mutation

#### Scenario: Configure Brownfield without adapting it
- **WHEN** an authenticated operator registers a Brownfield project with valid repository and configuration but no ZIP
- **THEN** the project is saved as `CONFIGURED`, is not reported `PREPARED`, and no clone/import/bootstrap/adaptation is run

#### Scenario: Edit configuration without changing bound identity
- **WHEN** an operator edits a project's display/configuration/profile or authorized base-branch setting
- **THEN** the immutable project id and canonical repository identity remain bound, and any branch/binding change is validated before it becomes effective

#### Scenario: Pause and reactivate a project
- **WHEN** an operator pauses then activates an existing project through API or CLI
- **THEN** the lifecycle state changes observably, paused projects reject new work, and activation does not dispatch an agent, process a ticket, or enable a scheduler

#### Scenario: List or retrieve projects
- **WHEN** an authenticated operator lists projects or retrieves one by id
- **THEN** the same canonical project configuration and truthful onboarding/lifecycle states are returned without secret values
