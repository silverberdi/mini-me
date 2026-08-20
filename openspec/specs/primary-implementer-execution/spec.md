# Primary Implementer Execution Specification

## Purpose

Executes the configured primary implementer agent (Codex or Antigravity) in an isolated process with strict timeouts, environment controls, and secret redaction.

## Requirements

### Requirement: Primary implementer invocation
The system SHALL invoke the project's configured primary implementer agent as a child process inside the dedicated candidate worktree directory.

#### Scenario: Configured implementer started
- **WHEN** an execution job enters the `RUNNING` status
- **THEN** the system SHALL launch the configured implementer agent CLI/subprocess within the candidate worktree root with appropriate prompt and task context.

### Requirement: Execution timeout and process control
The system SHALL enforce a configurable execution timeout for the implementer process, terminating any stalled process cleanly.

#### Scenario: Implementer execution exceeds timeout
- **WHEN** the implementer subprocess runs longer than the configured timeout duration
- **THEN** the system SHALL terminate the subprocess group (SIGTERM followed by SIGKILL), update the job status to `FAILED`, and record a `JOB_TIMEOUT` event.

### Requirement: Implementer log capture and secret redaction
The system SHALL capture stdout and stderr from the implementer process, redact all sensitive patterns, and persist them in the job execution log.

#### Scenario: Redacted output persisted to job logs
- **WHEN** the implementer produces console output containing API keys or database connection passwords
- **THEN** all secret patterns are replaced with `[REDACTED]` before lines are saved to `job_logs` or emitted via API/CLI.
