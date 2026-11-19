## MODIFIED Requirements

### Requirement: Task completion verification
The system SHALL inspect task checkbox states in `tasks.md` upon implementer completion to evaluate implementation progress, SHALL verify that completed tasks correspond to actual implementation evidence, and SHALL detect and reject mass-checked tasks where checkboxes are marked complete without corresponding implementation evidence in the candidate diff. During Apply, an implementation task MAY be marked complete when its work is present in the active worktree and its relevant automated tests have passed with exit code 0; this marking SHALL NOT wait for the coordinator to consolidate the candidate or produce its immutable candidate SHA. A task that depends on an intentionally untracked or externally published immutable asset MAY use a deterministic SHA-256 check and passing local tests as Apply evidence without requiring a Git commit for that asset. Task checkboxes SHALL NOT by themselves certify that Apply, Verify, or the Change is complete. Candidate-specific published-version evidence SHALL retain its source identity and SHALL satisfy candidate-specific criteria only when its immutable SHA matches the candidate being verified.

#### Scenario: All tasks marked complete by implementer
- **WHEN** the implementer finishes and all tasks in `tasks.md` are checked `- [x]`
- **THEN** the system checks that completed tasks have corresponding candidate diff evidence and that relevant automated checks pass
- **AND** proceeds only through the existing deterministic checks and candidate-verification flow.

#### Scenario: Incomplete tasks remaining
- **WHEN** the implementer finishes but unchecked tasks `- [ ]` remain
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

#### Scenario: Apply task completion does not wait for candidate SHA
- **GIVEN** an implementation task's work is present in the active worktree
- **AND** its relevant automated tests have passed with exit code 0
- **AND** the coordinator has not yet consolidated or assigned the immutable candidate SHA
- **WHEN** the implementer updates `tasks.md` during Apply
- **THEN** the task MAY be marked `- [x]` based on the worktree diff and test result
- **AND** the absence of a final candidate SHA SHALL NOT be reported as a blocker for that checkbox.

#### Scenario: External immutable asset verified without Git commit
- **GIVEN** an immutable external asset or intentionally untracked fixture is required by an implementation task
- **AND** a deterministic check confirms its expected SHA-256 and relevant local tests pass
- **WHEN** the implementer records Apply progress
- **THEN** the task MAY be marked complete without requiring a Git commit for the excluded asset
- **AND** the coordinator continues to verify tracked candidate changes and tests through its existing checks.

#### Scenario: Candidate-specific evidence remains bound to candidate SHA
- **GIVEN** evidence claims that a published version satisfies a criterion for the current candidate
- **AND** the published version's immutable SHA is absent or differs from the candidate SHA
- **WHEN** the coordinator evaluates candidate verification
- **THEN** it SHALL retain the evidence's published-version source identity
- **AND** SHALL NOT treat the criterion as proven for the candidate.
