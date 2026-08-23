## Purpose

Defines the structured blocker contract, narrowed deterministic blocker validation, blocker fingerprinting, progress evaluation, and evidence-driven continuation decisions with configurable hard ceilings.

## ADDED Requirements

### Requirement: Structured blocker claim contract and fingerprinting
The system SHALL require any blocker claim emitted by an executor to include structured attributes: `blocker_type`, `affected_requirement`, `failing_invariant`, `evidence`, `attempted_remediation`, `rationale_why_continuation_impossible`, and `is_agent_solvable`. The system SHALL compute a deterministic blocker fingerprint string by hashing or canonically concatenating `blocker_type`, `affected_requirement`, `failing_invariant`, and normalized reason code to track repeated blocker assertions across attempts without relying on semantic similarity.

#### Scenario: Valid structured blocker payload ingested and fingerprinted
- **WHEN** an executor terminates claiming a blocker with a fully-populated structured blocker schema
- **THEN** the system SHALL ingest the claim, compute its deterministic blocker fingerprint, and submit it to the blocker validation service.

#### Scenario: Unstructured blocker claim rejected
- **WHEN** an executor asserts a blocker in unstructured free-form text without required schema fields
- **THEN** the system SHALL classify the attempt as `MALFORMED_RESULT` or `EVIDENCE_INSUFFICIENT` and reject unvalidated blocking.

### Requirement: Narrowed deterministic blocker validation
The system SHALL validate blocker claims using deterministic repository contracts, verifying:
1. Whether the claimed missing file or artifact is explicitly required by OpenSpec or a canonical contract;
2. Whether the repository already exposes the required capability through a registered/declared module integration point;
3. Whether creating the missing artifact is part of normal implementation scope for the active change;
4. Whether a concrete inaccessible dependency or invariant conflict exists.
If equivalence cannot be determined deterministically, the system SHALL fail closed to `NEEDS_HUMAN` rather than inferring architecture via an LLM.

#### Scenario: False blocker on missing non-contractual filename
- **WHEN** an executor claims a blocker because a non-contractual filename does not exist (e.g., `scheduler_service.py`) but OpenSpec does not require that name and an existing declared integration point exists (e.g., `capacity_lifecycle_service.py`) or creating the file is within scope
- **THEN** the system SHALL classify the claim as `FALSE_BLOCKER`, record the discovered integration point, and reject the blocking claim.

#### Scenario: Real blocker on external credential or missing dependency
- **WHEN** an executor encounters an inaccessible required external service, missing required host secret, or unresolvable invariant conflict requiring product guidance
- **THEN** the system SHALL validate the claim as `REAL_BLOCKER` and record the blocking invariant.

### Requirement: Deterministic progress evaluation
The system SHALL evaluate progress between consecutive attempts using deterministic hard-evidence signals: `completed_openspec_task_delta`, `remaining_openspec_task_count`, `candidate_file_delta_count`, `deterministic_checks_pass_delta`, `deterministic_checks_fail_delta`, `acceptance_evidence_delta`, `blocker_resolution_delta`, `regression_detected` (boolean), and `policy_violation` (boolean). Progress SHALL be classified into exactly one category:
- `GOOD_PROGRESS`: At least one positive hard-evidence delta (task completed or check passed) with `regression_detected = False` and `policy_violation = False`.
- `PARTIAL_PROGRESS`: Candidate files modified or partial tasks/checks advanced, but completion evidence is incomplete, with `regression_detected = False`.
- `NO_PROGRESS`: Zero positive hard-evidence deltas across the attempt.
- `REGRESSION`: Deterministic checks newly fail, previously completed tasks become unchecked, required artifacts are removed, or candidate integrity degrades.

#### Scenario: Good progress detected
- **WHEN** an attempt completes one or more pending OpenSpec tasks and increases passing deterministic checks without introducing regressions
- **THEN** the system SHALL classify progress as `GOOD_PROGRESS`.

#### Scenario: Regression detected across attempts
- **WHEN** an attempt causes previously passing deterministic checks to fail or deletes valid candidate code without advancing tasks
- **THEN** the system SHALL classify progress as `REGRESSION`.

#### Scenario: No progress detected across attempts
- **WHEN** an attempt produces zero task completions, zero check improvements, and zero valid candidate diffs
- **THEN** the system SHALL classify progress as `NO_PROGRESS`.

### Requirement: Deterministic continuation decision engine with configurable hard limits
The system SHALL decide the next operational action after each executor attempt by evaluating deterministic counters and hard ceilings: `max_corrective_retries_per_executor` (default: 2), `max_reassignments_per_job` (default: 2), `max_same_outcome_streak` (default: 2), and `max_same_false_blocker_streak` (default: 2). The engine SHALL select exactly one continuation action: `CONTINUE_SAME_AGENT`, `CORRECT_AND_RETRY`, `REASSIGN_AGENT`, `WAIT_EXTERNAL`, or `NEEDS_HUMAN` based on the following deterministic rules:

1. `COMPLETED` outcome → advance to checks / candidate manifest preparation.
2. `PREMATURE_STOP` with `PARTIAL_PROGRESS` and `corrective_retries < max_corrective_retries` → `CORRECT_AND_RETRY`.
3. `PREMATURE_STOP` with `NO_PROGRESS` or `corrective_retries >= max_corrective_retries` → `REASSIGN_AGENT` if alternative eligible executor exists; else `NEEDS_HUMAN`.
4. `FALSE_BLOCKER` on first occurrence (`streak < max_same_false_blocker_streak`) → `CORRECT_AND_RETRY` with targeted corrective prompt.
5. `FALSE_BLOCKER` with `same_blocker_fingerprint_streak >= max_same_false_blocker_streak` → `REASSIGN_AGENT` if alternative eligible executor exists; else `NEEDS_HUMAN`.
6. `CHANGES_REQUIRED` (failing checks) with `corrective_retries < max_corrective_retries` and `regression_detected = False` → `CORRECT_AND_RETRY`.
7. `CHANGES_REQUIRED` with `corrective_retries >= max_corrective_retries` or `REGRESSION` → `REASSIGN_AGENT` if alternative eligible executor exists; else `NEEDS_HUMAN`.
8. `REAL_BLOCKER` with external root cause → `WAIT_EXTERNAL` if transient/externally recoverable, or `NEEDS_HUMAN` if human intervention is required; NOT automated reassignment.
9. `PROVIDER_EXHAUSTED` → `WAIT_EXTERNAL` (invoking provider capacity lifecycle / DRAIN fallback per 005/006); NOT behavioral failure.
10. `reassignment_count >= max_reassignments_per_job` without reaching completion → `NEEDS_HUMAN`.
11. Alternative executor unavailable or ineligible when reassignment is indicated → `NEEDS_HUMAN` (or `WAIT_EXTERNAL` if capacity-bound).

#### Scenario: Corrective retry decided on first premature stop
- **WHEN** an executor produces `PREMATURE_STOP` with `PARTIAL_PROGRESS` and `corrective_retries = 0`
- **THEN** the continuation engine SHALL decide `CORRECT_AND_RETRY` and increment `corrective_retry_count_for_current_executor`.

#### Scenario: Reassignment decided when false blocker repeats
- **WHEN** an executor produces a `FALSE_BLOCKER` with the same fingerprint for the 2nd time (`streak = 2`) and an eligible alternative primary executor exists
- **THEN** the continuation engine SHALL decide `REASSIGN_AGENT`.

#### Scenario: Escalation to NEEDS_HUMAN on anti-ping-pong limit
- **WHEN** a job reaches `reassignment_count = 2` and fails completion verification
- **THEN** the continuation engine SHALL decide `NEEDS_HUMAN` and record the full escalation rationale.

### Requirement: Targeted corrective instruction generation
The system SHALL generate a concise, structured corrective prompt when `CORRECT_AND_RETRY` is decided, referencing the rejected outcome, specific failing checks or invalidated blocker points, and exact required actions without resending redundant full-context history.

#### Scenario: Corrective instruction generated for false blocker
- **WHEN** a `FALSE_BLOCKER` is invalidated
- **THEN** the system SHALL construct a corrective prompt explaining that the requested capability does not require the imagined missing file, identifying existing integration points, and instructing continuation within the active change.
