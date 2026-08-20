# Worktree Lifecycle Specification

## Purpose

Manages the lifecycle of isolated Git worktrees for registered projects to ensure clean candidate workspace execution without mutating the primary repository worktree.

## Requirements

### Requirement: Isolated worktree creation
The system SHALL create a dedicated, isolated Git worktree for an execution job, based on the registered project's configured base branch.

#### Scenario: Worktree created for candidate branch
- **WHEN** an execution job is initiated for a validated project and change
- **THEN** a dedicated worktree directory is created under `.minime/worktrees/<job_id>` checking out a fresh candidate branch `minime/<change_id>-<job_id>` from the project's base branch.

### Requirement: Worktree safety and path isolation
The system SHALL ensure the worktree path is strictly within the project's configured boundary and does not collide with existing active worktrees.

#### Scenario: Existing or dirty worktree path prevented
- **WHEN** a job attempts to initialize a worktree path that already exists and is non-empty
- **THEN** the system SHALL reject reusing the dirty directory, log an error event, and fail the job initialization cleanly.

### Requirement: Candidate SHA capture
The system SHALL extract and record the candidate head commit SHA from the worktree upon completion of changes.

#### Scenario: Candidate head commit recorded
- **WHEN** the primary implementer completes execution in the worktree
- **THEN** the system SHALL query `git rev-parse HEAD` within the worktree and record the candidate head SHA in the job record.

### Requirement: Safe worktree cleanup
The system SHALL provide deterministic worktree pruning and directory cleanup upon job completion or cancellation.

#### Scenario: Worktree cleaned up after final state
- **WHEN** a job reaches a terminal state (or cleanup is explicitly requested)
- **THEN** the system SHALL run `git worktree remove` and delete temporary workspace artifacts while preserving recorded candidate commit SHAs in the Git object database.
