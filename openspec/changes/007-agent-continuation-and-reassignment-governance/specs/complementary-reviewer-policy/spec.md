## MODIFIED Requirements

### Requirement: Strict complementary role pairing
The system SHALL require that the primary reviewer agent differs from the final primary implementer agent according to the project's configured complementary pair policy (Codex implements → Antigravity reviews, or Antigravity implements → Codex reviews). If an executor reassignment has occurred resulting in mixed authorship, the candidate review report SHALL explicitly disclose mixed authorship and the system SHALL enforce mandatory DeepSeek Direct independent audit and mandatory human merge.

#### Scenario: Valid complementary pairing accepted
- **WHEN** a job is submitted for review with Codex as implementer and Antigravity as reviewer (or vice versa)
- **THEN** the policy check passes and review execution proceeds.

#### Scenario: Self-review rejected
- **WHEN** a review is attempted where the final implementer and reviewer share the same agent identity or provider
- **THEN** the system SHALL reject the review execution, transition the job to `FAILED`, and record a `REVIEW_POLICY_VIOLATION` event.

#### Scenario: Review of mixed authorship candidate disclosed
- **WHEN** a candidate has partial authorship by both configured executors due to mid-job reassignment
- **THEN** the assigned reviewer SHALL NOT be classified as fully independent, the review outcome record SHALL include `is_mixed_authorship: true` alongside the full author contribution history, and DeepSeek Direct audit SHALL remain mandatory before advancing to human merge.
