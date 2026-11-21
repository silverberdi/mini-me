# Deterministic Checks Runner Specification

## Purpose

Runs configured deterministic project verification commands inside candidate worktrees and persists structured execution evidence.

## Requirements

### Requirement: Deterministic check suite execution
The system SHALL sequentially execute each deterministic check configured in the project definition inside the candidate worktree, and SHALL sanitize the execution environment supplied to candidate check subprocesses to prevent accidental canonical operational database targeting.

#### Scenario: Normal candidate checks execute with sanitized environment
- **WHEN** deterministic checks execute for a candidate worktree
- **THEN** the check runner purges `MINIME_DATABASE_URL` and `MINIME_EXPECTED_DATABASE` from the subprocess environment by default
- **AND** normal candidate checks cannot inadvertently connect to or mutate the canonical database.

#### Scenario: Explicit disposable database check validated fail-closed
- **WHEN** a check configuration explicitly declares disposable PostgreSQL test intent with a declared expected database identity
- **AND** the configured database URL points to a non-canonical disposable database whose name exactly matches the expected database identity
- **THEN** the check runner passes the verified database environment and executes the check.

#### Scenario: Check targeting canonical database fails closed
- **WHEN** a check attempts to run with a database URL pointing to the canonical operational database (`minime`), or lacks expected database identity, or has a mismatched database name
- **THEN** the check runner SHALL fail closed immediately with a non-zero exit code and diagnostic failure before spawning the subprocess.

#### Scenario: All configured checks pass
- **WHEN** all project check commands exit with return code 0
- **THEN** individual check results are stored, and the job transitions to `CHECKS_PASSED`.

#### Scenario: A check command fails
- **WHEN** any configured check command exits with a non-zero return code
- **THEN** the failure stdout/stderr is captured, subsequent checks are halted, and the job transitions to `CHECKS_FAILED`.

### Requirement: Check evidence retention
The system SHALL persist check names, commands, exit codes, execution duration, and output snippets as verifiable evidence records in PostgreSQL.

#### Scenario: Check evidence recorded in database
- **WHEN** a check command completes
- **THEN** a `check_results` record is inserted linked to the job ID, storing `check_name`, `command`, `exit_code`, `duration_ms`, and `output_snippet`.

### Requirement: Candidate test subprocesses do not inherit host AI-provider credentials
Every subprocess used to build or run tests for a managed candidate SHALL receive an environment composed only of an explicit baseline allowlist of operating-system and toolchain runtime variables plus values explicitly supported and configured for that candidate's project checks. The baseline SHALL include the runtime values needed by supported toolchains, including `PATH`, `HOME`, locale variables, temporary-directory variables, `DOTNET_ROOT`, `NODE_PATH`, and `PYTHONPATH`. Values added from project-check configuration SHALL be added only through their existing supported and validated settings. All other inherited host variables SHALL be absent, including `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `COHERE_API_KEY`, `GROQ_API_KEY`, variables ending in `_API_KEY` or `_SECRET`, and other non-allowlisted values such as `AWS_ACCESS_KEY_ID`, `POSTGRES_PASSWORD`, `GITHUB_TOKEN`, or `ANTHROPIC_AUTH_TOKEN`. This requirement SHALL apply to automatically resolved test commands and configured project checks, but SHALL NOT alter credentials supplied to authorized mini me agent invocations.

#### Scenario: Host provider credentials are absent from candidate test execution
- **GIVEN** the mini me host environment contains provider credential variables, including the named provider keys or other infrastructure variables ending in `_API_KEY` or `_SECRET`
- **WHEN** an automatically resolved or configured candidate test command is started
- **THEN** the child process receives only allowlisted runtime variables and explicitly configured project-check settings
- **AND** all other inherited host variables, including provider keys and unrelated credentials, are absent.

#### Scenario: Non-allowlisted host variables are not inherited
- **GIVEN** the mini me host environment contains variables such as `AWS_ACCESS_KEY_ID`, `POSTGRES_PASSWORD`, `GITHUB_TOKEN`, or `ANTHROPIC_AUTH_TOKEN`
- **WHEN** an automatically resolved or configured candidate test command is started
- **THEN** none of those non-allowlisted host variables are present in the child process environment.

#### Scenario: Explicit project-check settings remain available
- **GIVEN** a candidate test command has project-check settings explicitly configured through an existing supported project configuration
- **WHEN** the candidate test environment is prepared
- **THEN** those authorized settings remain available after host credentials are filtered
- **AND** they do not cause unrelated host provider credentials to be restored.

#### Scenario: Authorized agent invocation retains its configured provider credentials
- **GIVEN** mini me is invoking a configured thinking, execution, or review agent
- **WHEN** that authorized agent process is prepared
- **THEN** this candidate-test-only filtering does not remove the provider credentials required by the agent invocation.
