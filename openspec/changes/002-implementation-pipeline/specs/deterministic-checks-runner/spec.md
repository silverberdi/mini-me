## Purpose

Runs configured deterministic project verification commands inside candidate worktrees and persists structured execution evidence.

## ADDED Requirements

### Requirement: Deterministic check suite execution
The system SHALL sequentially execute each deterministic check configured in the project definition (e.g. linter, unit test suite) inside the candidate worktree.

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
