# project-registry Specification

## Purpose
Register projects with immutable identity and explicit execution policy so mini me can address repositories safely and consistently.

## Requirements

### Requirement: Immutable internal project identity
Each registered project SHALL have an immutable internal project identifier distinct from its display name.

#### Scenario: Project display name changes
- **GIVEN** a registered project with an internal project identifier
- **WHEN** its human-readable display name is changed
- **THEN** the internal project identifier remains unchanged.

### Requirement: Required project policy
Project registration SHALL capture project type, immutable canonical repository identity, main branch (defaulting to `main` when omitted), separate provider connections, four compatible agent-role profiles, applicable finite execution policy, and truthful onboarding/lifecycle status. Project creation for external repositories SHALL perform a multi-stage preflight validation before declaring creation complete: validating remote GitHub App read/write grants (`issues`, `contents`, `pull_requests`), initializing the managed base clone and its `ProjectManagedRepositoryBinding`, provisioning required canonical skills/workflows (`minime-request-normalizer`, `minime-pr-preparer`, `openspec-*`, `.agent/workflows/opsx-*`), and verifying workflow file readiness. All newly registered projects SHALL be initialized with status `PAUSED` and `effective_pause: true` by default. A Greenfield project SHALL also provide a valid context ZIP before any project row is committed.

#### Scenario: Required project configuration is incomplete
- **WHEN** a registration request omits type, repository, provider connection, or a required compatible role profile, or supplies an invalid branch name
- **THEN** validation rejects it structurally and the project is not executable or prepared

#### Scenario: Default the main branch when omitted
- **WHEN** an authenticated registration request omits the optional main-branch name
- **THEN** mini me uses `main` and continues normal repository identity and branch-existence validation

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

#### Scenario: GitHub App repository grants missing at registration
- **WHEN** an authenticated registration request specifies a remote repository where the GitHub App installation lacks necessary repository grants
- **THEN** registration fails closed before persistence and surfaces the exact grant deficiency to the operator

#### Scenario: Managed repository binding and canonical skills provisioned at creation
- **WHEN** project registration completes its multi-stage validation successfully
- **THEN** the managed repository root and valid `ProjectManagedRepositoryBinding` are established
- **AND** canonical OpenSpec and mini me skills for the assigned roles are verified present in the workspace
- **AND** the project is created in `PAUSED` status with `effective_pause: true`

### Requirement: Project type, repository configuration, and lifecycle
Every project SHALL have an immutable project id and canonical repository identity, an explicit `GREENFIELD` or `BROWNFIELD` type, and a main branch explicitly provided by the operator or defaulted to `main` when omitted. The project SHALL expose truthful onboarding status separately from active/paused lifecycle status. Newly registered projects SHALL start in `PAUSED` status to prevent unintended competition with currently active projects; pausing SHALL prevent new work, and activation SHALL NOT start F3 ticket processing or a scheduler.

#### Scenario: Register a Greenfield project with a valid context package
- **WHEN** an authenticated operator submits a valid project type, project id, repository URL, optional branch, provider/agent configurations, permissions, and ZIP package
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
