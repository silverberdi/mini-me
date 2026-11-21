## ADDED Requirements

### Requirement: Feasibility comparison ignores only cosmetic task metadata
When comparing an assessed OpenSpec task inventory with the current task inventory at a stage transition, the system SHALL identify tasks by their canonical `X.Y` task IDs and SHALL compare task descriptions after trimming surrounding whitespace, collapsing redundant whitespace, and removing only recognized status tags `[DIFERIDA]`, `[DEFERRED]`, and `[OPTIONAL]` that appear immediately after the task ID. The system SHALL preserve strict blocking for missing, extra, renamed, or substantively changed tasks and SHALL NOT relax checkbox completion, scenario coverage, dependency, or evidence checks. Assessment records SHALL retain enough source information to perform this comparison against the exact assessed task text; for a legacy record without that information, the system SHALL recover the source from its recorded candidate revision when possible and SHALL otherwise retain the existing fail-closed behavior.

#### Scenario: Status tag and redundant whitespace do not invalidate an assessed task
- **GIVEN** a task was assessed with a canonical task ID and description
- **AND** its current description differs only by surrounding or redundant whitespace or one recognized status tag immediately after the task ID
- **WHEN** stage feasibility compares the task inventories
- **THEN** it treats the task description as unchanged
- **AND** continues to evaluate its completion status and evidence normally.

#### Scenario: Substantive task edits and inventory changes remain blockers
- **GIVEN** an assessed task is removed, added, renamed, or its substantive description is changed
- **WHEN** stage feasibility compares the task inventories
- **THEN** it reports the task inventory or description change
- **AND** holds the transition for native OpenSpec Update and strict validation.

#### Scenario: Legacy task assessment uses its exact recorded revision
- **GIVEN** a persisted assessment predates canonical task-text metadata
- **AND** it includes a candidate revision from which the assessed task text can be recovered
- **WHEN** a status tag or cosmetic whitespace is added to the current task description
- **THEN** the system compares normalized current text with the description recovered from that exact revision
- **AND** does not treat the annotation as a substantive task edit.

#### Scenario: Missing legacy source remains fail-closed
- **GIVEN** a legacy assessment has only a task hash and its assessed task text cannot be recovered from the recorded candidate revision
- **WHEN** the current task text no longer matches the stored hash
- **THEN** the system reports that the assessed task source is unavailable
- **AND** does not infer that the change is cosmetic or advance the transition.
