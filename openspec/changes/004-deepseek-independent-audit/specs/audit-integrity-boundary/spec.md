## Purpose

Enforces strict read-only boundary verification for DeepSeek Direct audit execution, guaranteeing candidate SHA binding pre-audit, providing OS-level read-only snapshot isolation with symlink fail-closed security, and ensuring candidate code and worktrees remain completely unmodified post-audit.

## ADDED Requirements

### Requirement: Pre-audit candidate integrity and gating verification
The system SHALL verify candidate worktree state, HEAD SHA, base SHA, and prior authoritative review verdict before launching DeepSeek Direct audit.

#### Scenario: Pre-audit integrity check succeeds only after READY_TO_MERGE
- **WHEN** preparing to launch an audit for a candidate job
- **THEN** the system verifies the worktree exists, HEAD commit matches the recorded `candidate_sha`, base commit matches `base_sha`, and the job has reached an authoritative complementary review verdict of `READY_TO_MERGE`.

#### Scenario: Pre-audit gating prevents audit on non-approved review states
- **WHEN** the candidate job has a review status of `CHANGES_REQUIRED`, `REVIEW_FAILED`, `REVIEW_TIMED_OUT`, malformed review output, or failed deterministic checks
- **THEN** the system SHALL NOT launch DeepSeek Direct audit and preserves the candidate in its review/check terminal state.

#### Scenario: Pre-audit SHA mismatch halts execution
- **WHEN** the candidate worktree HEAD SHA differs from the recorded candidate SHA or has uncommitted modifications before audit
- **THEN** the system halts pipeline advancement, logs a `CANDIDATE_SHA_MISMATCH` integrity event, and marks the job as `FAILED`.

### Requirement: Read-only workspace snapshot isolation
The system SHALL execute audit inspection against an isolated, OS-level read-only snapshot derived from the candidate worktree, failing closed if prohibited symlinks are detected.

#### Scenario: Dedicated read-only snapshot established
- **WHEN** creating the audit context and inspection workspace
- **THEN** the system scans the candidate worktree for symlinks (failing closed if any are detected), copies the directory tree to a dedicated snapshot path, strips all write permissions (`0o444`/`0o555`), and verifies write denial via probe write before auditor invocation.

#### Scenario: Authoritative worktree remains non-writable to auditor
- **WHEN** DeepSeek Direct audit is performed
- **THEN** the auditor is never provided writable filesystem access to the authoritative candidate worktree.

### Requirement: Post-audit read-only boundary enforcement
The system SHALL verify that the candidate worktree, Git history, and OpenSpec task files remain 100% untouched following auditor execution.

#### Scenario: Candidate remains unmodified after audit
- **WHEN** DeepSeek Direct audit execution completes
- **THEN** the system inspects git status and commit SHA of the candidate worktree to confirm zero file modifications or added commits occurred during audit.

#### Scenario: Auditor mutation detected and rejected
- **WHEN** git status reveals modified, untracked, or committed files in the worktree after auditor execution
- **THEN** the system rejects the audit result, marks the job as `FAILED` with an unauthorized mutation violation error, and records an `UNAUTHORIZED_AUDITOR_MUTATION` event.
