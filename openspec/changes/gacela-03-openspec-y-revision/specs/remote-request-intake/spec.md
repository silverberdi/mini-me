## Purpose
Select and admit external work requests directly from the configured remote project management system (initially GitHub Issues) using strict FIFO ordering, exhaustive pagination, and dependency filtering without duplicate database backlogs.

## ADDED Requirements

### Requirement: Remote FIFO Issue Selection with Exhaustive Pagination
The system SHALL query open issues directly from the project's configured remote repository using exhaustive pagination, ordering candidates in ascending order by creation date (`created_at`) with deterministic tie-breaking by issue number, and SHALL NOT omit older issues across page boundaries.

#### Scenario: Oldest open eligible issue is selected first
- **WHEN** a project is activated or requests the next unit of work
- **AND** multiple open issues exist in the remote repository
- **THEN** the system selects the issue with the earliest `created_at` timestamp.

#### Scenario: Stable tie-breaking on identical timestamps
- **WHEN** two eligible open issues share the exact same `created_at` timestamp
- **THEN** the system selects the issue with the smaller numerical issue number.

#### Scenario: Exhaustive pagination over large issue counts
- **WHEN** the remote repository contains more open issues than a single page limit (e.g. > 50 issues)
- **THEN** the system iterates all pages until exhausted so that the true oldest issue is always evaluated.

### Requirement: Exclusion of Disabled Requests and Explicit Unresolved Dependencies
The system SHALL evaluate each remote issue in FIFO order and SHALL exclude from immediate admission any issue labeled with the exact tag `disabled` or containing explicit formal unresolved dependencies supported by the provider (such as explicit directives `depends on #<num>`, `blocked by #<num>` or explicit dependency task lists in the issue body), evaluating subsequent issues without altering the original priority of deferred items, and SHALL NOT classify casual issue mentions or informal citations as blocking dependencies.

#### Scenario: Issue labeled disabled is deferred
- **WHEN** the oldest open issue has the label `disabled`
- **THEN** the system skips that issue and evaluates the next oldest issue.

#### Scenario: Issue with explicit unresolved dependencies is deferred
- **WHEN** the oldest issue declares explicit dependencies on other issues (e.g. `depends on #42`) that remain open
- **THEN** the system skips that issue, marks it temporarily blocked, and evaluates the next issue.

#### Scenario: Casual issue reference is not treated as dependency
- **WHEN** an issue body mentions or links another issue casually without explicit dependency syntax (e.g. "similar to #12")
- **THEN** the system does not classify the mention as a dependency and admits the issue if otherwise eligible.

#### Scenario: Unblocked issue regains its original FIFO position
- **WHEN** a previously blocked issue has all its dependencies closed or its `disabled` label removed
- **THEN** on the next work selection cycle the system evaluates it according to its original `created_at` timestamp.

### Requirement: Strict Single Active Request per Project and Re-entry
The system SHALL enforce that at most one Request is active per project at any time (admitting zero active requests when no eligible work exists), SHALL NOT maintain a parallel queue or duplicate backlog in PostgreSQL, and SHALL recover and resume an active in-flight Request instead of duplicating execution or creating parallel branches.

#### Scenario: Second request is refused while one is in progress
- **WHEN** a project already has an active Request undergoing execution
- **THEN** any attempt to start or admit another Request for that project fails closed until the active Request completes closure.

#### Scenario: Project with no eligible issues remains idle
- **WHEN** a project has no open issues or all open issues are disabled or dependent
- **THEN** the system admits no request and leaves the project in an idle state without errors or phantom runs.

#### Scenario: Re-entry resumes existing active request
- **WHEN** execution is triggered for a project whose active Request was interrupted
- **THEN** the system recovers the existing run, associates the existing candidate branch and worktree, and continues from its last verified stage.
