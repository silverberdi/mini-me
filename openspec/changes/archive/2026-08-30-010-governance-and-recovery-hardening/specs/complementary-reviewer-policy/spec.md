## MODIFIED Requirements

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
