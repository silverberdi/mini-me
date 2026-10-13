## MODIFIED Requirements

### Requirement: Strict complementary role pairing
The system SHALL require that the primary reviewer agent differs from every substantive implementer identity whose work survives in the frozen candidate according to the project's configured reviewer policy. If reassignment results in surviving contributions by the assigned reviewer, the Review record, reviewer context, and presentation SHALL disclose mixed authorship and SHALL NOT represent that reviewer as fully independent. Historical attempts whose contributions do not survive in the current candidate SHALL NOT trigger mixed authorship. An independent audit SHALL be required only when applicable policy or explicit human authorization requires it; DeepSeek Direct is not a universal mandatory final audit boundary.

#### Scenario: Valid complementary pairing accepted
- **WHEN** a job is submitted for review by an eligible identity distinct from surviving substantive authors and no surviving reviewer contributions exist in the candidate
- **THEN** the policy check passes, review execution proceeds, and `is_mixed_authorship = False` is recorded.

#### Scenario: Self-review rejected
- **WHEN** a review is attempted where the final implementer and reviewer share an agent or model identity that authored surviving candidate changes
- **THEN** the system SHALL reject the authoritative review, keep the candidate blocked from PR readiness, and record a `REVIEW_POLICY_VIOLATION` event.

#### Scenario: Review of mixed authorship candidate disclosed
- **WHEN** a candidate generation contains surviving code or artifact modifications authored by the assigned reviewer during a prior attempt on the active job
- **THEN** the assigned reviewer SHALL NOT be classified as fully independent, and the review record, reviewer context, and presentation SHALL disclose `is_mixed_authorship = True` with the surviving contribution evidence
- **AND** any additional audit is required only if applicable policy or explicit human authorization requires it.

#### Scenario: Discarded prior attempt does not trigger mixed authorship
- **WHEN** the reviewer previously executed an attempt whose modifications were completely rolled back, discarded, or overwritten in the current frozen candidate generation
- **THEN** the system SHALL classify the current candidate as single-authored by the active implementer and record `is_mixed_authorship = False`.

#### Scenario: Audit is not silently substituted for independent review
- **GIVEN** no eligible complementary reviewer is available
- **WHEN** the pipeline evaluates candidate acceptance
- **THEN** a DeepSeek Direct audit or other analyst report SHALL NOT substitute for the required independent complementary review
- **AND** the candidate remains preserved in an appropriate waiting or blocked state.
