# Reviewer Execution Contract Specification

## Purpose

Defines a provider-neutral reviewer execution contract providing immutable change identity, candidate SHA, base SHA, worktree context, and check evidence to the complementary reviewer agent.

## Requirements

### Requirement: Explicit change identity and SHA propagation
The system SHALL invoke the complementary reviewer with explicit immutable execution identity, including `project_id`, exact `change_id`, candidate HEAD SHA, base SHA, candidate worktree path, OpenSpec artifact locations, and deterministic check evidence.

#### Scenario: Reviewer receives explicit change identity and candidate SHA
- **WHEN** a review execution is launched for a candidate
- **THEN** the reviewer execution payload contains the exact change ID, candidate SHA, base SHA, worktree directory, and preceding check results
- **AND** the system SHALL NOT allow the reviewer to infer or select an active or newest change implicitly.

### Requirement: Reviewer process execution with timeout and redaction
The system SHALL execute the complementary reviewer CLI/subprocess inside the candidate worktree with process group isolation, execution timeout enforcement, and secret redaction on all captured output streams.

#### Scenario: Reviewer process completes within timeout
- **WHEN** the reviewer process executes and exits within the configured timeout
- **THEN** stdout and stderr are captured, redacted of all sensitive patterns, and stored in the review log stream.

#### Scenario: Reviewer process exceeds timeout
- **WHEN** the reviewer process runs longer than the configured timeout duration
- **THEN** the system SHALL terminate the subprocess group (SIGTERM followed by SIGKILL), transition the review status to `REVIEW_TIMED_OUT`, and record a `REVIEW_TIMEOUT` event.
