# Complementary Reviewer Policy Specification

## Purpose

Enforces strict complementary primary agent pairing between implementation and review, preventing self-review and disallowing mid-flight role alterations.

## Requirements

### Requirement: Strict complementary role pairing
The system SHALL require that the primary reviewer agent differs from the final primary implementer agent according to the project's configured complementary pair policy (Codex implements → Antigravity reviews, or Antigravity implements → Codex reviews). If an executor reassignment has occurred resulting in the assigned reviewer having authored contributions that survive in the CURRENT frozen candidate generation/SHA being reviewed, the Review record, reviewer prompt context payload, and review presentation SHALL explicitly disclose mixed authorship (`is_mixed_authorship = True`), the reviewer SHALL remain complementary but SHALL NOT be represented as fully independent, and DeepSeek Direct SHALL remain the independent final audit boundary. Historical attempts whose contributions do not survive in the current candidate SHALL NOT trigger mixed authorship.

#### Scenario: Valid complementary pairing accepted
- **WHEN** a job is submitted for review with Codex as implementer and Antigravity as reviewer (or vice versa) and no surviving reviewer contributions exist in the candidate
- **THEN** the policy check passes, review execution proceeds, and `is_mixed_authorship = False` is recorded.

#### Scenario: Self-review rejected
- **WHEN** a review is attempted where the final implementer and reviewer share the same agent identity or provider
- **THEN** the system SHALL reject the review execution, transition the job to `FAILED`, and record a `REVIEW_POLICY_VIOLATION` event.

#### Scenario: Review of mixed authorship candidate disclosed
- **WHEN** a candidate generation contains surviving code or artifact modifications authored by the assigned reviewer during a prior attempt on the active job
- **THEN** the assigned reviewer SHALL NOT be classified as fully independent, the review record and reviewer prompt payload SHALL include `is_mixed_authorship = True` alongside the surviving author contribution evidence, and DeepSeek Direct audit SHALL remain mandatory before advancing to human merge.

#### Scenario: Discarded prior attempt does not trigger mixed authorship
- **WHEN** the assigned reviewer previously executed an attempt whose modifications were completely rolled back, discarded, or overwritten in the current frozen candidate generation
- **THEN** the system SHALL classify the current candidate as single-authored by the active implementer and record `is_mixed_authorship = False`.

### Requirement: Immutable reviewer assignment during job lifecycle
The system SHALL NOT permit altering or switching the assigned reviewer agent or provider once an execution job is initiated.

#### Scenario: Attempted mid-flight reviewer change rejected
- **WHEN** a request attempts to change the reviewer role on an active or queued job
- **THEN** the system SHALL reject the modification and preserve the original durable project binding policy.

### Requirement: Deterministic failure when complementary reviewer unavailable
The system SHALL halt in a durable, observable state when the configured complementary reviewer agent or binary is unavailable.

#### Scenario: Reviewer binary or environment missing
- **WHEN** the system attempts to invoke a complementary reviewer whose command or runtime environment cannot be resolved
- **THEN** the system SHALL transition the review state to `REVIEW_FAILED` and record an explicit diagnostic failure reason in PostgreSQL.
