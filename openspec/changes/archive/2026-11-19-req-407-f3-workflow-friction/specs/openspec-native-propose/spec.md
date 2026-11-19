## ADDED Requirements

### Requirement: Execution feasibility accepts verified stage-workflow evidence
When evaluating an Apply task assigned to the configured execution role, the system SHALL treat verified evidence for the configured role's native Apply workflow as sufficient to establish the actor's execution capability. It SHALL NOT require a redundant task-level `profile:execution` evidence reference in addition to `workflow:execution:apply`. The configured execution profile and the native workflow capability MUST still be independently verified from project/worktree configuration, and unknown, missing, or failed workflow evidence SHALL remain a blocker.

#### Scenario: Native Apply workflow proves execution capability without a duplicate profile reference
- **GIVEN** a strictly validated Apply task assigned to `execution`
- **AND** the project's configured execution profile is verified
- **AND** the task cites verified `workflow:execution:apply` evidence but does not repeat `profile:execution`
- **WHEN** proposal feasibility is assessed
- **THEN** the execution capability is treated as satisfied
- **AND** the task is not blocked solely for omitting the redundant profile reference.

#### Scenario: Missing or invalid native workflow evidence remains fail-closed
- **GIVEN** an Apply task assigned to `execution`
- **AND** its configured execution profile is missing or `workflow:execution:apply` is absent, unknown, or failed
- **WHEN** proposal feasibility is assessed
- **THEN** the task remains blocked with the specific missing or unverified capability
- **AND** no report wording or operator text can substitute for that evidence.

### Requirement: Correctable feasibility reports receive bounded corrective reassessment
Before opening a proposal-feasibility human gate, the system SHALL allow at most two corrective reassessments when the existing feasibility validator identifies objective report-shape, task/scenario mapping, or stage-order errors that can be corrected by revising the report. Each reassessment SHALL receive the concrete validator diagnostics and the same observed candidate, task inventory, scenario inventory, and capability evidence. These retries SHALL NOT convert missing or unknown evidence, real capability blockers, provider/CLI execution failures, or security failures into executable results. After the limit, or for any non-correctable blocker, the system SHALL preserve the diagnostics and use the current human-gate path.

#### Scenario: Correctable task-stage inconsistency is reassessed before escalation
- **GIVEN** the feasibility report assigns a precondition to a stage later than the task that needs it
- **AND** no real missing capability or evidence blocker is present
- **WHEN** validation returns the concrete stage-order diagnostic and the corrective limit has not been reached
- **THEN** the configured thinking agent receives that diagnostic for a bounded reassessment
- **AND** a human gate is not opened solely for the first correctable report inconsistency.

#### Scenario: Corrected report passes while retaining evidence requirements
- **GIVEN** a corrective reassessment returns a structurally valid report with correct task stages and mappings
- **AND** every capability and precondition needed before Apply has independently verified evidence
- **WHEN** the report is revalidated
- **THEN** the assessment may proceed to the existing complexity decision
- **AND** no prior or later-stage evidence is marked complete without observation.

#### Scenario: Corrective limit or real blocker preserves fail-closed behavior
- **GIVEN** two corrective reassessments have been used or the report identifies missing, unknown, or failed evidence
- **WHEN** feasibility is evaluated
- **THEN** no further reassessment is dispatched for that blocker
- **AND** the current gate names the unresolved evidence or diagnostic and preserves the candidate and assessment history.

### Requirement: Proposal-feasibility gate always offers the canonical native Update action
A blocked proposal-feasibility gate SHALL include a selectable, clearly identified option that the existing response path recognizes as authorization to run the installed native OpenSpec Update workflow for the same Run and Change. Agent-generated resolution text MAY be preserved as additional guidance but SHALL NOT replace or make the canonical Update action unselectable. Selecting Update SHALL authorize only the native revision and strict revalidation; it SHALL NOT itself clear a feasibility blocker or authorize Apply.

#### Scenario: Canonical Update action remains selectable beside agent-generated options
- **GIVEN** a blocked feasibility report includes free-form resolution options that do not contain the recognized OpenSpec Update action
- **WHEN** the human gate is created
- **THEN** the gate retains the agent-generated options and also includes the canonical native OpenSpec Update action
- **AND** selecting that action resumes the same Run and Change through native Update with the persisted diagnostics and assessment.

#### Scenario: Update selection cannot waive an unresolved blocker
- **GIVEN** the operator selects the canonical native Update action
- **WHEN** Update completes or fails
- **THEN** the resulting artifacts are strictly validated and feasibility is reassessed against current evidence
- **AND** Apply remains blocked unless the reassessment establishes an executable path.
