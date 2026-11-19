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
The system SHALL execute the complementary reviewer CLI/subprocess inside the candidate worktree with process group isolation, execution timeout enforcement, and secret redaction on all captured output streams. The reviewer invocation SHALL be proven read-only and non-interactive (no human approval interaction) and SHALL NOT mutate the candidate worktree.

#### Scenario: Reviewer process completes within timeout
- **WHEN** the reviewer process executes and exits within the configured timeout
- **THEN** stdout and stderr are captured, redacted of all sensitive patterns, and stored in the review log stream.

#### Scenario: Reviewer process exceeds timeout
- **WHEN** the reviewer process runs longer than the configured timeout duration
- **THEN** the system SHALL terminate the subprocess group (SIGTERM followed by SIGKILL), transition the review status to `REVIEW_TIMED_OUT`, and record a `REVIEW_TIMEOUT` event.

#### Scenario: Reviewer runs read-only without human approval interaction
- **WHEN** the configured reviewer invocation is executed
- **THEN** it SHALL run read-only and SHALL NOT require interactive human approval.

#### Scenario: Reviewer remains non-mutating
- **WHEN** the reviewer process completes
- **THEN** the candidate worktree SHALL remain unmodified (no new files, commits, or task checkbox changes) by the reviewer.

### Requirement: Verdict-first prompt formatting and diff hygiene
The system SHALL compose the reviewer prompt instructing that the structured review verdict JSON payload be emitted as the first line of output, and SHALL exclude dependency lockfiles and binary assets from the diff passed to the independent reviewer.

#### Scenario: Review prompt mandates JSON verdict first
- **WHEN** the orchestrator builds the prompt for independent proposal or code review
- **THEN** the prompt explicitly instructs the reviewer to output the single structured JSON verdict object immediately as its very first output line before any narrative remarks.

#### Scenario: Code review diff excludes non-code lockfiles
- **WHEN** the orchestrator extracts the git diff for a candidate change
- **THEN** package lockfiles (`package-lock.json`, `poetry.lock`, `pnpm-lock.yaml`, `yarn.lock`) are excluded from the review diff payload to preserve reviewer context budget.

#### Scenario: Code review diff resolves against remote merge base
- **WHEN** the orchestrator determines the base ancestor for the review diff
- **THEN** it resolves the diff against the remote tracking base commit (`merge-base`) rather than a potentially un-synchronized local branch reference.
