# OpenSpec Task Tracking Specification

## Purpose

Parses and tracks task-level implementation progress from OpenSpec changes during execution without mutating OpenSpec files with runtime state.

## Requirements

### Requirement: Task context extraction for implementer
The system SHALL parse `tasks.md` from the active OpenSpec change directory and construct structured task prompt context for the primary implementer.

#### Scenario: OpenSpec tasks extracted and formatted
- **WHEN** preparing an execution job for a change
- **THEN** all tasks defined in `tasks.md` are extracted, preserving requirement sections and task IDs, and provided to the implementer execution payload.

### Requirement: Task completion verification
The system SHALL inspect task checkbox states in `tasks.md` upon implementer completion to evaluate implementation progress.

#### Scenario: All tasks marked complete by implementer
- **WHEN** the implementer finishes and all tasks in `tasks.md` are checked `- [x]`
- **THEN** the system marks the task execution phase as complete and proceeds to deterministic checks.

#### Scenario: Incomplete tasks remaining
- **WHEN** the implementer finishes but unchecked tasks `- [ ]` remain in `tasks.md`
- **THEN** the system records an `INCOMPLETE_TASKS` event detailing the remaining task IDs.

### Requirement: Runtime isolation of OpenSpec files
The system SHALL NOT write runtime ephemeral data, retry counters, or process IDs into OpenSpec files.

#### Scenario: OpenSpec files preserved from runtime mutations
- **WHEN** jobs execute, retry, or fail
- **THEN** all operational execution metadata is written exclusively to PostgreSQL, leaving OpenSpec repository files unchanged except for implementer source code edits and task checkbox updates.
