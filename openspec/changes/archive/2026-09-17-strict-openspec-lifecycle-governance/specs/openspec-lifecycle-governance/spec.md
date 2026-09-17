## Purpose

Enforces deterministic OpenSpec lifecycle governance across all mini me change workflows, provides an integrity auditor that evaluates the repository's OpenSpec state, defines strong CLOSED semantics integrating lifecycle and delivery completion, classifies legacy/non-canonical changes truthfully, and ensures all lifecycle gates fail closed with exact diagnostic reasons rather than silently repairing or fabricating state.

## ADDED Requirements

### Requirement: OpenSpec integrity audit

The system SHALL provide a service-backed integrity audit that evaluates the repository's entire OpenSpec state and returns a structured report of findings, and SHALL never silently mutate or repair detected problems.

#### Scenario: Audit reports healthy state

- **GIVEN** a repository where all active changes are strict-valid, no merged-but-unsynced changes exist, no closed-but-unarchived changes exist, all canonical specs are internally consistent, and no orphan or stale OpenSpec directories exist
- **WHEN** the integrity audit executes
- **THEN** the audit SHALL report overall status PASS with zero blocking findings.

#### Scenario: Audit detects invalid active change

- **GIVEN** a repository where an active change fails `openspec validate --strict --type change`
- **WHEN** the integrity audit executes
- **THEN** the audit SHALL report overall status FAIL
- **AND** the finding SHALL identify the change name, the validation failure reason, and the severity CRITICAL.

#### Scenario: Audit detects merged-but-unsynced change

- **GIVEN** a change whose candidate was merged to the base branch but whose delta specs have not been synchronized to canonical specs
- **WHEN** the integrity audit executes
- **THEN** the audit SHALL report a MERGED_BUT_UNSYNCED finding with the change name and the unsynchronized capability paths.

#### Scenario: Audit detects closed-but-unarchived change

- **GIVEN** an orchestration run in COMPLETED state whose change directory still exists under `openspec/changes/` as an active change
- **WHEN** the integrity audit executes
- **THEN** the audit SHALL report a CLOSED_BUT_UNARCHIVED finding with the change name and the archival target path.

#### Scenario: Audit detects orphan OpenSpec directory

- **GIVEN** a directory under `openspec/changes/` that has no corresponding `changes` database record, no discoverable OpenSpec artifacts (no `.openspec.yaml`, no `proposal.md`, no `specs/`), no active orchestration run references it, and is not under the archive path
- **WHEN** the integrity audit executes
- **THEN** the audit SHALL report an ORPHAN_DIRECTORY finding with the directory path and severity WARNING.

#### Scenario: OpenSpec directory without DB record is not automatically orphaned

- **GIVEN** a directory under `openspec/changes/` that has `proposal.md` and `specs/` but no `changes` database record because readiness has never been evaluated
- **WHEN** the integrity audit executes
- **THEN** the audit SHALL NOT classify the directory as ORPHAN
- **AND** SHALL note the absent DB record as a classification observation, not as a defect.

#### Scenario: Audit detects multiple archive locations

- **GIVEN** a repository where OpenSpec change archives exist in both `openspec/changes/archive/` and `openspec/archive/`
- **WHEN** the integrity audit evaluates archive layout
- **THEN** the audit SHALL report an ARCHIVE_LAYOUT_AMBIGUITY finding identifying the canonical archive location (`openspec/changes/archive/` per the installed `OpenSpecSyncService`) and the alternate location
- **AND** SHALL NOT classify entries in either location as invalid solely based on location.

#### Scenario: Audit detects task-state contradiction

- **GIVEN** an active change whose `tasks.md` has all checkboxes marked `- [x]` but whose orchestration run has never reached IMPLEMENTING stage
- **WHEN** the integrity audit executes
- **THEN** the audit SHALL report a TASK_STATE_CONTRADICTION finding identifying that tasks are marked complete without corresponding implementation evidence.

#### Scenario: Audit evidence is insufficient

- **GIVEN** the audit cannot establish enough facts to confirm integrity for a particular dimension due to missing database records, absent filesystem artifacts, or contradictory evidence
- **WHEN** the integrity audit executes
- **THEN** the audit SHALL report that dimension as UNKNOWN with the specific evidence gap described, rather than inferring PASS or FAIL.

### Requirement: CLOSED semantics

The system SHALL define CLOSED as the state where both OpenSpec lifecycle completion and project delivery completion are satisfied, SHALL require all applicable lifecycle gates to have been passed with verifiable evidence, and SHALL NOT declare CLOSED when any required gate evidence is missing, stale, or contradictory.

#### Scenario: OpenSpec lifecycle completion required for CLOSED

- **GIVEN** a change that has completed implementation, passed checks, passed review, passed audit, and been human-merged
- **WHEN** CLOSED evaluation executes
- **THEN** the system SHALL require evidence of completed sync and archive before OpenSpec lifecycle completion is satisfied
- **AND** the change SHALL NOT be CLOSED if sync or archive evidence is missing.

#### Scenario: Project delivery completion required for CLOSED

- **GIVEN** a change whose OpenSpec lifecycle is complete (verify, sync, archive all passed) but whose project-level deployment has not completed
- **WHEN** CLOSED evaluation executes
- **THEN** the system SHALL distinguish OpenSpec lifecycle completion from project delivery completion
- **AND** SHALL report CLOSED as NOT_SATISFIED with the missing delivery requirement identified
- **AND** SHALL NOT corrupt OpenSpec lifecycle state while awaiting deployment.

#### Scenario: Fully closed change satisfies both lifecycle and delivery

- **GIVEN** a change with OpenSpec lifecycle complete (verify, sync, archived) and project delivery complete (merge confirmed, deployed, production verified)
- **WHEN** CLOSED evaluation executes
- **THEN** the system SHALL report CLOSED as SATISFIED.

#### Scenario: CLOSED evidence survives repository clone

- **GIVEN** a change that is CLOSED
- **WHEN** the repository is cloned to a new environment with an empty PostgreSQL instance
- **THEN** the canonical specs and archive directory SHALL reconstruct the lifecycle evidence coherently
- **AND** the integrity audit SHALL classify database-only evidence gaps as UNKNOWN rather than FAIL.

### Requirement: Legacy and non-canonical classification

The system SHALL classify historical changes truthfully based on available OpenSpec evidence, SHALL consider the schema version and artifact requirements applicable at each change's apparent creation context where evidence exists, SHALL designate changes lacking canonical OpenSpec history as LEGACY, and SHALL NEVER fabricate retrospective proposal, spec, design, or task history for changes that lack it.

#### Scenario: Change without .openspec.yaml is classified by artifact content

- **GIVEN** an active change directory that lacks `.openspec.yaml` but has a complete `proposal.md`, `tasks.md`, `design.md`, and delta specs that pass `openspec validate`
- **WHEN** the system evaluates the change
- **THEN** the system SHALL classify the change as CANONICAL based on artifact completeness and validity
- **AND** SHALL NOT mark it invalid solely due to the missing `.openspec.yaml` metadata file.

#### Scenario: Change predating current schema is truthfully classified

- **GIVEN** a change whose artifacts were authored before the current spec-driven schema was adopted and lack artifacts the current schema requires
- **WHEN** the system evaluates the change
- **THEN** the system SHALL classify it as LEGACY_STRUCTURAL with the specific gaps enumerated
- **AND** SHALL NOT manufacture missing artifacts to retroactively satisfy current schema.

#### Scenario: Archived change with no OpenSpec evidence is classified as legacy debt

- **GIVEN** a directory under `openspec/changes/archive/` that contains implementation artifacts but no OpenSpec artifacts (no proposal, specs, tasks, or design)
- **WHEN** the integrity audit evaluates it
- **THEN** the audit SHALL classify it as LEGACY_ARCHIVE_DEBT
- **AND** SHALL NOT fabricate retrospective OpenSpec history for it.

### Requirement: Truthful failure contract

The system SHALL fail closed when any lifecycle gate condition is unmet, SHALL report the exact missing or broken condition with sufficient detail to diagnose and correct it, and SHALL NEVER silently repair state, infer progress that did not occur, or mark gates as satisfied without deterministic evidence.

#### Scenario: Gate fails closed with exact diagnostic

- **GIVEN** a lifecycle gate that evaluates to FAIL because a required artifact is missing
- **WHEN** the gate evaluates
- **THEN** the system SHALL return a result containing the gate name, the specific failure reason, the artifact or evidence that is missing, and a severity level
- **AND** SHALL NOT proceed past the gate.

#### Scenario: Gate cannot be evaluated truthfully

- **GIVEN** a lifecycle gate whose evaluation requires evidence that is unavailable due to missing database records or inaccessible filesystem state
- **WHEN** the gate evaluates
- **THEN** the system SHALL report UNKNOWN with the evidence gap described
- **AND** SHALL fail closed, treating UNKNOWN as blocking unless policy explicitly allows degraded evaluation.

#### Scenario: Agent claim does not satisfy a gate

- **GIVEN** an agent or process asserts that a lifecycle gate condition is satisfied without providing the deterministic evidence the gate requires
- **WHEN** the gate evaluates
- **THEN** the system SHALL reject the unsubstantiated claim
- **AND** SHALL NOT mark the gate as satisfied based solely on the assertion.

### Requirement: Lifecycle gate composition

The system SHALL define lifecycle gates as composable, independently evaluable conditions that operate on existing PostgreSQL state, OpenSpec filesystem state, Git state, and orchestration evidence, and SHALL NOT introduce a new monolithic lifecycle state machine that duplicates or overrides existing domain enums.

#### Scenario: Gate evaluation uses existing truths

- **GIVEN** a gate that checks whether a change's delta specs have been synchronized
- **WHEN** the gate evaluates
- **THEN** the system SHALL consult the existing `orchestration_stage_events` for sync evidence, check the canonical spec filesystem for the expected requirements, and the `changes` table for the change's status
- **AND** SHALL NOT require a dedicated gate-status table unless no existing evidence source can answer the question.

#### Scenario: Gate operates independently

- **GIVEN** multiple lifecycle gates defined for different lifecycle phases
- **WHEN** any single gate evaluates
- **THEN** the system SHALL evaluate it independently using only the evidence sources it declares, without requiring all other gates to have passed first.

#### Scenario: Gate policy is configurable

- **GIVEN** a project configuration specifying which lifecycle gates are required for admission and which are advisory
- **WHEN** the gate framework evaluates a change
- **THEN** the system SHALL enforce required gates as blocking and SHALL report advisory gate failures as warnings without blocking.