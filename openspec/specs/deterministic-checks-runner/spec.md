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
