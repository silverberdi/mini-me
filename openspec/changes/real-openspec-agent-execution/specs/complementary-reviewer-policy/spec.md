## MODIFIED Requirements

### Requirement: Strict complementary role pairing
The system SHALL require that the primary final-review agent differs from every substantive author whose contributions survive in the candidate, including the final implementer, according to configured complementary-review policy. The existing `_validate_review_authority` gate SHALL continue to deterministically enforce candidate-SHA, base-SHA, manifest, generation, and reviewer-identity binding. The integrity auditor SHALL detect and report stale or mismatched review evidence as part of the OpenSpec integrity audit. If an executor reassignment has occurred resulting in the assigned reviewer having authored contributions that survive in the CURRENT frozen candidate generation/SHA being reviewed, the Review record, reviewer prompt context payload, and review presentation SHALL explicitly disclose mixed authorship (`is_mixed_authorship = True`), the reviewer SHALL remain complementary but SHALL NOT be represented as fully independent. DeepSeek Direct MAY perform final authoritative code review only under the existing narrow fallback condition that no eligible primary reviewer can serve and only under a distinct explicitly authorized compatible read-only reviewer contract, with sufficient candidate input, structured response validation, and identity independence; it SHALL NOT use or convert an audit result as review approval. R01 CONTRACT REVIEW is a separate pre-APPLY read-only stage where DeepSeek Direct is preferred only with verified capability/fresh capacity and explicit provider/stage/budget authorization, with AGY as the alternative. Contract-review evidence SHALL NOT satisfy final review. Historical attempts whose contributions do not survive in the current candidate SHALL NOT trigger mixed authorship. Any accepted review SHALL NOT authorize human merge.

#### Scenario: Valid complementary pairing accepted
- **WHEN** a job is submitted for review with Codex as implementer and Antigravity as reviewer (or vice versa), no surviving reviewer contributions exist in the candidate, and current candidate-bound evidence is valid
- **THEN** the policy check passes, review execution proceeds, and `is_mixed_authorship = False` is recorded.

#### Scenario: Self-review rejected
- **WHEN** a review is attempted where the final implementer and reviewer share the same agent identity or provider/model identity that authored surviving candidate changes
- **THEN** the system SHALL reject the authoritative review, keep the candidate blocked from PR readiness, and record a `REVIEW_POLICY_VIOLATION` event.

#### Scenario: Review of mixed authorship candidate disclosed
- **WHEN** a candidate generation contains surviving code or artifact modifications authored by the assigned reviewer during a prior attempt on the active job
- **THEN** the assigned reviewer SHALL NOT be classified as fully independent, and the review record, reviewer prompt context, and presentation SHALL disclose `is_mixed_authorship = True` with the surviving contribution evidence
- **AND** an independent review may be satisfied only by another identity that is distinct from every surviving substantive author and has valid candidate-bound evidence.

#### Scenario: Discarded prior attempt does not trigger mixed authorship
- **WHEN** the reviewer previously executed an attempt whose modifications were completely rolled back, discarded, or overwritten in the current frozen candidate generation
- **THEN** the system SHALL classify the current candidate as single-authored by the active implementer and record `is_mixed_authorship = False`.

#### Scenario: DeepSeek Direct provides distinct read-only final code review
- **GIVEN** no eligible primary reviewer is available, DeepSeek review capability and sufficient review input are verified, the operator explicitly authorizes the provider and stage budget, and the reviewer identity is distinct from every surviving substantive author
- **WHEN** DeepSeek Direct returns a response through the separate review contract
- **THEN** deterministic validation SHALL bind and validate the structured review against repository, base/head SHA, generation, manifest, and reviewer identity before it can satisfy the review gate
- **AND** the existing audit runner or audit record SHALL NOT be converted into review evidence, and human merge remains a separate mandatory gate.

#### Scenario: DeepSeek final review cannot be proven or authorized
- **GIVEN** DeepSeek compatibility, complete review input, structured response validity, identity independence, or explicit provider/budget authorization is missing, stale, or ambiguous
- **WHEN** the system evaluates review eligibility
- **THEN** it SHALL reject the fallback, preserve the candidate, and wait or block without invoking an unauthorized paid call or treating audit output as review.

## ADDED Requirements

### Requirement: R01 contract review is a distinct read-only stage
For R01, CONTRACT REVIEW SHALL evaluate only the OpenSpec contract before APPLY. DeepSeek Direct SHALL be the preferred contract reviewer only when its exact configured model and read-only capability are compatible, fresh capacity is proven, and explicit provider/stage/budget authorization exists; otherwise AGY SHALL be the configured alternative. If neither is eligible, the work SHALL remain preserved and waiting. This preference SHALL NOT change the final code-review policy, authorize APPLY or product decisions, or satisfy human merge. Contract-review evidence SHALL be distinct from audit and final-review evidence.

#### Scenario: Authorized DeepSeek contract review is preferred
- **GIVEN** DeepSeek has a compatible read-only contract-review profile, current capacity, and explicit budget/provider/stage authorization
- **WHEN** the R01 workflow reaches CONTRACT REVIEW before APPLY
- **THEN** mini me dispatches the candidate-bound read-only contract review through the separate review contract
- **AND** records its result as contract-review evidence without granting APPLY, final-review, or merge authority.

#### Scenario: AGY is the contract-review alternative
- **GIVEN** DeepSeek is unavailable, incompatible, unknown/exhausted, or lacks explicit budget authorization and AGY has a compatible authorized profile with current capacity
- **WHEN** the R01 workflow reaches CONTRACT REVIEW
- **THEN** mini me uses AGY as the configured read-only alternative and records the actual model/effort and evidence identity.

#### Scenario: No contract reviewer is eligible
- **GIVEN** neither DeepSeek nor AGY has a compatible authorized read-only profile with current capacity
- **WHEN** the R01 workflow reaches CONTRACT REVIEW
- **THEN** mini me preserves the change and waits without inference or proceeding to APPLY.

#### Scenario: Contract review cannot be promoted into another authority
- **GIVEN** a contract-review result, regardless of PASS or findings
- **WHEN** a caller attempts to use it as APPLY authorization, final code review, product decision, or merge approval
- **THEN** mini me rejects the substitution and retains the separate stage gates.

### Requirement: Deterministic failure when complementary reviewer unavailable
The system SHALL preserve a candidate in a durable, observable waiting or blocked state when the configured complementary primary reviewer agent or binary is unavailable, unless no eligible primary reviewer can serve and the separately authorized compatible DeepSeek read-only reviewer contract is fully satisfied. It SHALL NOT report PR readiness when no eligible authoritative reviewer is available.

#### Scenario: Reviewer binary or environment missing
- **GIVEN** the complementary reviewer command or runtime cannot be resolved and no compatible explicitly authorized DeepSeek reviewer is available
- **WHEN** the system attempts the review stage
- **THEN** it preserves the candidate, records an explicit diagnostic in durable state, and leaves the run waiting or blocked rather than manufacturing a successful review or PR-ready state.

#### Scenario: Primary reviewer unavailable but DeepSeek contract is satisfied
- **GIVEN** no eligible primary reviewer can serve and DeepSeek compatibility, sufficient candidate-bound input, explicit stage/provider/budget authorization, identity independence, and structured response validation are proven
- **WHEN** the review stage dispatches DeepSeek Direct under the distinct read-only reviewer contract
- **THEN** a valid candidate-bound review may satisfy only the review gate
- **AND** audit evidence is not substituted and human merge remains mandatory.

#### Scenario: No eligible reviewer remains available
- **GIVEN** neither an eligible primary nor a qualifying authorized DeepSeek reviewer is available
- **WHEN** review eligibility is evaluated
- **THEN** the candidate remains preserved in a truthful waiting or blocked state and does not advance to PR-ready.
