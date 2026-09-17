## MODIFIED Requirements

### Requirement: Single-change admission
The system SHALL start an orchestration run only for one explicitly selected project/change pair whose durable repository binding and existing readiness authority both validate as READY, SHALL verify all autonomous execution readiness prerequisites before admitting the run, and SHALL verify that the change is attributable to an active OpenSpec APPLY lifecycle by checking that no implementation artifacts predate the admission event.

#### Scenario: READY change is admitted
- **WHEN** the operator starts orchestration for a durably bound READY project/change pair
- **AND** project registration is active, durable binding exists, remote Issue verification passes, physical schema preflight passes, deterministic checks are non-empty, primary capacity is available, and GitHub App authority is healthy
- **THEN** the system creates one immutable `orchestration_run_id`, records the bound project/change/base identity, and enters the first persisted orchestration stage.

#### Scenario: Ineligible change is refused
- **WHEN** the selected change is not READY, has ambiguous/missing binding, or fails repository/workspace/schema preflight
- **THEN** no executable orchestration run is created and the refusal contains a structured reason.

#### Scenario: Duplicate active run is refused
- **WHEN** an active orchestration already exists for the same project/change pair
- **THEN** the new start request fails closed and returns the existing run identity without starting another job, worktree, branch, or provider action.

#### Scenario: Historical run does not block a later run
- **WHEN** prior orchestration runs for the same project/change are terminal and no non-terminal run exists
- **THEN** a new explicitly admitted run may be created while historical run records remain queryable.

#### Scenario: Implementation artifacts predate admission

- **GIVEN** a change whose worktree or branch contains implementation commits predating the OrchestrationRun creation timestamp
- **WHEN** admission is requested
- **THEN** the system SHALL detect the lifecycle drift
- **AND** SHALL refuse admission with a structured reason identifying the predating artifacts
- **AND** SHALL NOT create an orchestration run for the change.

#### Scenario: No OpenSpec change exists for requested admission

- **GIVEN** a project without any OpenSpec change matching the requested admission target
- **WHEN** admission is requested
- **THEN** the system SHALL refuse admission with a structured reason
- **AND** SHALL NOT fabricate an OpenSpec change to satisfy the request.

### Requirement: Human-gate contract
The system SHALL stop at exactly one of `READY_FOR_HUMAN_MERGE`, `WAITING_CAPACITY`, `WAITING_EXTERNAL`, or `NEEDS_HUMAN` for the run's MVP lifecycle, SHALL not merge, deploy, archive, or close the change automatically, and SHALL require verification evidence (OpenSpec validate, implementation/task coherence, scope integrity) before transitioning to `READY_FOR_HUMAN_MERGE`. `READY_FOR_HUMAN_MERGE` is only a human-gate outcome, not an orchestration stage.

#### Scenario: Operator resumes a waiting run
- **WHEN** provider capacity or a recoverable external condition is independently verified as restored/observable
- **THEN** `orchestrate resume` continues the same run from its durable checkpoint without repeating completed authoritative work.

#### Scenario: External wait is not capacity wait
- **WHEN** GitHub or another non-provider dependency is temporarily unavailable
- **THEN** the run uses `WAITING_EXTERNAL`, while `WAITING_CAPACITY` remains reserved for canonical 005/006 capacity evidence.

#### Scenario: Human merge remains mandatory
- **WHEN** a run is `READY_FOR_HUMAN_MERGE`
- **THEN** mini me exposes the exact PR, base SHA, candidate SHA, manifest/audit evidence, and stop reason while taking no merge action.

#### Scenario: Verification evidence required before READY_FOR_HUMAN_MERGE

- **GIVEN** a candidate that has passed checks, review, and audit
- **WHEN** the orchestration pipeline evaluates transition to `READY_FOR_HUMAN_MERGE`
- **THEN** the system SHALL require verification evidence including OpenSpec validation PASS, implementation/task coherence, and scope integrity
- **AND** SHALL NOT transition to `READY_FOR_HUMAN_MERGE` if any verification requirement is unmet.

#### Scenario: Verification failure blocks READY_FOR_HUMAN_MERGE

- **GIVEN** a candidate whose OpenSpec validation fails or whose task state contradicts implementation evidence
- **WHEN** the orchestration pipeline evaluates the human gate
- **THEN** the system SHALL stop with `Needs_Human` and a structured reason identifying the verification failure
- **AND** SHALL NOT fabricate a passing verification to proceed.