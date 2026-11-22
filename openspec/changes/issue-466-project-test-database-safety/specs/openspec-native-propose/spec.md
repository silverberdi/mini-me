## ADDED Requirements

### Requirement: Test tasks declare a safe, stage-appropriate execution path
After native Propose and strict validation, the system SHALL assess database-backed test tasks against the project's explicit test-database configuration and available execution stages. The proposal SHALL identify the responsible stage, safe database identity and host environment-variable reference (without secret material), executable test command, and observable completion evidence. A required test with an available authorized path SHALL NOT be converted into a human gate merely because the agent did not inspect or use that path. A test that requires external infrastructure unavailable before PR MAY be assigned to the matching project CI check as a later-stage task only when that check runs the same test against an isolated test database and is bound to the candidate SHA. Missing or unsafe database configuration, an absent CI path, or an unmapped test SHALL remain a concrete feasibility blocker rather than being labeled automatable or passed.

#### Scenario: Configured test database makes integration task executable
- **GIVEN** a project has a configured test database identity and host environment-variable reference
- **AND** the relevant command can execute in Apply or Verify
- **WHEN** proposal task feasibility is assessed
- **THEN** the task is assigned to that stage with evidence from the configured check and its observed result
- **AND** feasibility does not request a human to run the check.

#### Scenario: Apply-created database artifacts are not preconditions
- **GIVEN** the Change creates or updates a migration, schema, or test command during Apply
- **WHEN** feasibility is assessed before Apply
- **THEN** those planned deliverables are recorded as Apply tasks and are not treated as already-existing preconditions
- **AND** any required test database access is evaluated only at the stage that needs to execute it.

#### Scenario: Brownfield database has no isolated test target
- **GIVEN** the project uses PostgreSQL but has no configured isolated test database or safe host reference
- **WHEN** a mandatory database-backed task is assessed
- **THEN** feasibility reports the missing project configuration or provisioning evidence as the specific blocker
- **AND** it does not silently use Mini Me's database, production, an ambient URL, or a human gate as a substitute.

#### Scenario: External integration check has a matching CI path
- **GIVEN** a required integration test cannot execute in Apply or Verify because its external infrastructure is unavailable there
- **AND** the project CI runs the same test on the implementation PR using an isolated test database
- **WHEN** feasibility is assessed
- **THEN** the task is assigned to that CI check and its result is required before merge
- **AND** proposal acceptance does not require the not-yet-created PR check result.
