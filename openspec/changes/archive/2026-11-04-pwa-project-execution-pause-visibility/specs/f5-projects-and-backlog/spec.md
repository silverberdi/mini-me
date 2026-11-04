## ADDED Requirements

### Requirement: Proyectos displays execution pause state
The Proyectos view SHALL display a project's `effective_pause` state separately from its administrative project status. It SHALL display a system-level paused indicator when any project payload reports `global_pause` as true. The view SHALL use the existing `execution_policy` data and SHALL reflect changes after the existing project refresh. It SHALL NOT infer execution pause from `projects.status` or introduce a separate persisted pause state.

#### Scenario: Project execution is paused
- **WHEN** a project's `execution_policy.effective_pause` is true
- **THEN** Proyectos clearly identifies that project as paused regardless of its administrative status

#### Scenario: System execution is globally paused
- **WHEN** a project payload reports `execution_policy.global_pause` as true
- **THEN** Proyectos clearly identifies the system as globally paused

#### Scenario: Project pause changes after refresh
- **WHEN** `effective_pause` changes in the project payload and the existing project refresh completes
- **THEN** Proyectos displays the updated pause state for that project

#### Scenario: Execution is not paused
- **WHEN** no project has `effective_pause` true and no project payload has `global_pause` true
- **THEN** Proyectos does not display an execution-paused indicator for the project or system
