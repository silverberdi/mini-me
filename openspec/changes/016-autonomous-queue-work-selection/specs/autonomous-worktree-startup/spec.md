# Autonomous Worktree Startup Specification

## ADDED Requirements

### Requirement: Native Isolated Worktree Allocation
The system SHALL natively create and initialize an isolated candidate git worktree, dedicated branch ref `minime/<change-name>-<uuid>`, and verified baseline commit SHA upon admitting a work item, without requiring external manual worktree creation commands.

#### Scenario: Autonomous candidate worktree creation upon admission
Given an admitted work item for change `016-autonomous-queue-work-selection` in project `mini-me`
When the scheduler admits the change and triggers execution
Then the system SHALL create an isolated candidate worktree under the project's worktrees root
And checkout a dedicated branch `minime/016-autonomous-queue-work-selection-<uuid>` from the project's `base_branch`
And record the authoritative base SHA in the `OrchestrationRun` record.

### Requirement: Deterministic Primary Implementer Selection
The system SHALL select the primary implementer role based on configured project preferences, provider health status, and future reviewer independence rules, creating the execution job and initiating the implementation pipeline.

#### Scenario: Primary implementer selection
Given a project configured with `implementer="codex"` and `reviewer="antigravity"`
And both providers have status `AVAILABLE`
When the work item is admitted
Then the system SHALL assign `codex` as the implementer for the initial execution attempt
And create an execution `Job` in status `QUEUED` or `RUNNING`.

### Requirement: Startup Idempotency and Race Protection
The system SHALL verify that no active worktree or duplicate candidate branch exists before creating a new candidate worktree, ensuring that repeated scheduler ticks or retries reuse or safely re-bind existing candidate workspaces.

#### Scenario: Re-admitting existing change does not overwrite worktree
Given an active orchestration run already possessing an allocated worktree at path `wt_path`
When a scheduler tick processes the change
Then the system SHALL NOT create a secondary worktree or destroy the active working tree.
