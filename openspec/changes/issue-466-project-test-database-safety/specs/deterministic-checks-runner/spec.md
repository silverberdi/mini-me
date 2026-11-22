## MODIFIED Requirements

### Requirement: Deterministic check suite execution
The system SHALL sequentially execute each deterministic check configured in the project definition inside the candidate worktree, and SHALL sanitize the execution environment supplied to candidate check subprocesses to prevent accidental canonical operational database targeting.

#### Scenario: Normal candidate checks execute with sanitized environment
- **WHEN** deterministic checks execute for a candidate worktree
- **THEN** the check runner purges `MINIME_DATABASE_URL` and `MINIME_EXPECTED_DATABASE` from the subprocess environment by default
- **AND** normal candidate checks cannot inadvertently connect to or mutate the canonical database.

#### Scenario: Explicit disposable database check validated fail-closed
- **WHEN** a check configuration explicitly declares disposable PostgreSQL test intent with a declared expected database identity and a host environment-variable reference
- **AND** the referenced URL resolves to PostgreSQL and its host, port, and database name exactly match the configured test database identity
- **AND** the database name is not a configured production or Mini Me database identity
- **THEN** the check runner passes the resolved database URL only to that check subprocess and executes the check.

#### Scenario: Check targeting canonical database fails closed
- **WHEN** a check's database configuration is missing or invalid, its URL reference is unset, its resolved URL is not PostgreSQL, its host, port, or database name differs from the configured test identity, or its target is identified as production or Mini Me's operational database
- **THEN** the check runner SHALL fail closed with a non-zero diagnostic before spawning the database-writing check subprocess
- **AND** it SHALL NOT fall back to `MINIME_DATABASE_URL` or another ambient host database variable.

#### Scenario: Database secret is absent from project configuration and agent context
- **GIVEN** a project's test database is configured by a non-secret database identity and a reference to a host environment variable
- **WHEN** project configuration is persisted, rendered to an agent, or included in check evidence
- **THEN** the reference and logical identity MAY be present
- **AND** the resolved URL, username, password, and other secret material SHALL NOT be persisted, rendered to agents, or written to logs.

#### Scenario: All configured checks pass
- **WHEN** all project check commands exit with return code 0
- **THEN** individual check results are stored, and the job transitions to `CHECKS_PASSED`.

#### Scenario: A check command fails
- **WHEN** any configured check command exits with a non-zero return code
- **THEN** the failure stdout/stderr is captured, subsequent checks are halted, and the job transitions to `CHECKS_FAILED`.
