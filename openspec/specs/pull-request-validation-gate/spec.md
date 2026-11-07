# pull-request-validation-gate Specification

## Purpose

Validar de forma continua, aislada y determinista cada Pull Request mediante GitHub Actions ejecutando pruebas backend con PostgreSQL efímero y pruebas/compilación frontend, bloqueando el merge a `main` ante fallos sin comprometer entornos productivos ni alterar el flujo de despliegue.

## Requirements

### Requirement: Automated CI workflow execution on Pull Requests
The CI system SHALL execute a dedicated Pull Request validation workflow (`pr-validation.yml`) upon `pull_request` events targeting the `main` branch, independent of the production release and deployment workflow.

#### Scenario: Pull request triggers validation workflow
- **WHEN** a pull request targeting `main` is opened, synchronized with new commits, or reopened
- **THEN** GitHub Actions SHALL trigger the PR validation workflow
- **AND** it SHALL NOT trigger the production release or deployment workflow (`release-and-deploy.yml`).

### Requirement: Ephemeral PostgreSQL and Backend Test Execution
The PR validation workflow SHALL provision an ephemeral, isolated PostgreSQL service container, apply database migrations using `alembic upgrade head`, and execute the active backend test suite with `pytest`.

#### Scenario: Backend tests pass against ephemeral database
- **WHEN** the backend validation job runs
- **THEN** an ephemeral PostgreSQL service container is initialized
- **AND** Alembic applies all migrations up to head against the ephemeral database
- **AND** `pytest` executes the active backend test suite and reports exit code 0 upon success.

#### Scenario: Backend test failure halts job
- **WHEN** any pytest test or Alembic migration fails
- **THEN** the backend validation job SHALL fail with a non-zero exit code
- **AND** the failure details and error logs SHALL be clearly visible in GitHub Actions run output.

### Requirement: Frontend Unit Testing and Build Validation
The PR validation workflow SHALL install Node dependencies, execute the preserved frontend test suite, and compile the Angular application.

#### Scenario: Frontend tests and Angular build succeed
- **WHEN** the frontend validation job runs
- **THEN** Node.js dependencies are installed
- **AND** frontend unit tests execute successfully
- **AND** `npm run build` (or `ng build`) completes with exit code 0.

#### Scenario: Frontend build or test failure halts job
- **WHEN** any frontend unit test fails or the Angular compilation produces a build error
- **THEN** the frontend validation job SHALL fail with a non-zero exit code.

### Requirement: Merge Gate and SHA Traceability
The PR validation workflow SHALL expose conclusive status checks tied to the candidate commit SHA that enable GitHub branch protection rules to block merging when checks fail or are pending.

#### Scenario: PR status check reflects candidate SHA
- **WHEN** the workflow completes execution
- **THEN** GitHub status checks SHALL reflect the pass or fail outcome against the exact tested candidate commit SHA
- **AND** any failed check SHALL block merge when configured as a required status check in repository branch protections.

### Requirement: Isolation from Production and Non-free Services
The PR validation workflow SHALL NOT access the production PostgreSQL database, SHALL NOT call external paid API providers, and SHALL NOT execute packaging for release or deployment.

#### Scenario: Enforcement of isolation boundary
- **WHEN** PR validation jobs execute
- **THEN** no production database credentials, secrets, or endpoints are injected into the test execution environment
- **AND** no external paid inference or third-party paid service endpoints are invoked.
