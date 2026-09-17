## MODIFIED Requirements

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
