# remote-request-intake Specification

## Purpose
Select and admit external work requests directly from the configured remote project management system (initially GitHub Issues) using strict FIFO ordering, exhaustive pagination, and dependency filtering without duplicate database backlogs.

## Requirements

### Requirement: Remote FIFO Issue Selection with Exhaustive Pagination
The system SHALL query open issues directly from the project's configured remote repository using exhaustive pagination, ordering candidates in ascending order by creation date (`created_at`) with deterministic tie-breaking by issue number, and SHALL NOT omit older issues across page boundaries.

#### Scenario: Oldest open eligible issue is selected first
- **GIVEN** a configured project connected to a remote GitHub repository
- **AND** multiple open issues present in the remote tracker with differing `created_at` timestamps
- **WHEN** mini me requests the next eligible unit of work
- **THEN** intake returns the issue with the earliest `created_at` timestamp
- **AND** records the issue selection without replicating backlog entries into PostgreSQL.

#### Scenario: Stable tie-breaking on identical timestamps
- **GIVEN** two open eligible issues sharing the exact same `created_at` timestamp
- **WHEN** intake sorts the eligible candidates
- **THEN** the issue with the lower numerical issue number is selected deterministically.

#### Scenario: Exhaustive pagination over large issue counts
- **GIVEN** a remote repository with open issues spanning multiple API pages
- **WHEN** `GitHubAdapter.list_open_issues` executes
- **THEN** it pages through the complete API response until exhausted
- **AND** evaluates all candidate issues to select the genuine oldest item.

### Requirement: Exclusion of Disabled Requests and Explicit Unresolved Dependencies
The system SHALL evaluate each remote issue in FIFO order and SHALL exclude from immediate admission any issue labeled with the exact tag `disabled` or containing explicit formal unresolved dependencies supported by the provider (such as explicit directives `depends on #<num>`, `blocked by #<num>` or explicit dependency task lists in the issue body), evaluating subsequent issues without altering the original priority of deferred items, and SHALL NOT classify casual issue mentions or informal citations as blocking dependencies.

#### Scenario: Issue labeled disabled is deferred
- **GIVEN** the oldest open issue possessing the label `disabled`
- **WHEN** intake evaluates eligible candidates
- **THEN** the disabled issue is skipped
- **AND** the next oldest candidate is evaluated for eligibility.

#### Scenario: Issue with explicit unresolved dependencies is deferred
- **GIVEN** an open issue declaring an explicit dependency directive (e.g. `depends on #42`)
- **AND** issue #42 is currently open in GitHub
- **WHEN** intake checks issue eligibility
- **THEN** the candidate issue is deferred as blocked
- **AND** the next oldest candidate is evaluated.

#### Scenario: Casual issue reference is not treated as dependency
- **GIVEN** an open issue containing informal mentions (e.g. "relates to #10") without formal dependency directives
- **WHEN** intake checks issue eligibility
- **THEN** the mention is not treated as a blocking dependency
- **AND** the issue is admitted if otherwise eligible.

#### Scenario: Unblocked issue regains its original FIFO position
- **GIVEN** a previously blocked issue whose dependency has been closed on GitHub
- **WHEN** intake runs the next selection cycle
- **THEN** the issue is admitted based on its original `created_at` timestamp ahead of newer issues.

### Requirement: Strict Single Active Request per Project and Re-entry
The system SHALL enforce that at most one Request is active per project at any time (admitting zero active requests when no eligible work exists), SHALL NOT maintain a parallel queue or duplicate backlog in PostgreSQL, and SHALL recover and resume an active in-flight Request instead of duplicating execution or creating parallel branches.

#### Scenario: Second request is refused while one is in progress
- **GIVEN** a project holding an active run lock in PostgreSQL
- **WHEN** an attempt is made to admit or start another Request
- **THEN** the intake service rejects the request fail-closed
- **AND** preserves the existing active run without creating concurrent branches or worktrees.

#### Scenario: Project with no eligible issues remains idle
- **GIVEN** a project repository with no open eligible issues
- **WHEN** intake executes a selection cycle
- **THEN** it returns no active request
- **AND** logs an idle state cleanly without errors or phantom run records.

#### Scenario: Re-entry resumes existing active request
- **GIVEN** an interrupted active run for a project
- **WHEN** execution is triggered again for that project
- **THEN** the coordinator detects the existing run record and associated candidate worktree
- **AND** resumes from the recorded stage instead of creating a new run or worktree.
