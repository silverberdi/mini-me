## MODIFIED Requirements

### Requirement: Task completion verification
The system SHALL inspect task checkbox states in `tasks.md` upon implementer completion to evaluate implementation progress, SHALL verify that completed tasks correspond to actual implementation evidence, and SHALL detect and reject mass-checked tasks where checkboxes are marked complete without corresponding implementation evidence in the candidate diff.

#### Scenario: All tasks marked complete by implementer
- **WHEN** the implementer finishes and all tasks in `tasks.md` are checked `- [x]`
- **THEN** the system marks the task execution phase as complete and proceeds to deterministic checks.

#### Scenario: Incomplete tasks remaining
- **WHEN** the implementer finishes but unchecked tasks `- [ ]` remain in `tasks.md`
- **THEN** the system records an `INCOMPLETE_TASKS` event detailing the remaining task IDs.

#### Scenario: Mass-checked tasks without implementation evidence

- **GIVEN** all tasks in `tasks.md` are marked `- [x]` but the candidate diff contains zero file modifications or modifications that do not correspond to the claimed task completions
- **WHEN** task completion verification executes
- **THEN** the system SHALL detect the evidence gap
- **AND** SHALL classify the outcome as `EVIDENCE_INSUFFICIENT` or `NO_PROGRESS`
- **AND** SHALL NOT mark the task execution phase as complete.

#### Scenario: Partial task completion with corresponding evidence

- **GIVEN** some tasks are marked `- [x]` and the candidate diff contains modifications matching those task descriptions, while other tasks remain `- [ ]`
- **WHEN** task completion verification executes
- **THEN** the system SHALL record completed tasks with their corresponding evidence references
- **AND** SHALL record remaining tasks as incomplete
- **AND** SHALL NOT penalize the completed tasks due to other tasks remaining incomplete.