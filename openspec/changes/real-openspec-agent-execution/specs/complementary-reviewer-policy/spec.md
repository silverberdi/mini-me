## MODIFIED Requirements

### Requirement: Strict complementary role pairing
The system SHALL require DeepSeek Direct, acting through its own compatible read-only reviewer authority, to differ from every substantive author whose contributions survive in the contract under CONTRACT REVIEW or the frozen candidate under code REVIEW. The existing `_validate_review_authority` gate SHALL continue to deterministically enforce candidate-SHA, base-SHA, manifest, generation, and reviewer-identity binding for code review; contract review SHALL bind the exact OpenSpec contract revision. The integrity auditor SHALL detect and report stale or mismatched review evidence as part of the OpenSpec integrity audit. If an executor reassignment has occurred resulting in the assigned reviewer having authored contributions that survive in the CURRENT frozen candidate generation/SHA being reviewed, the Review record, reviewer prompt context payload, and review presentation SHALL explicitly disclose mixed authorship (`is_mixed_authorship = True`); that reviewer SHALL NOT be represented as independent. DeepSeek Direct SHALL perform separate read-only CONTRACT REVIEW and code REVIEW stages only with sufficient stage-specific input, structured response validation, identity independence, verified direct-account identity/capacity, and explicit per-stage budget authorization. It SHALL NOT use or convert an audit result as review approval. Contract-review evidence SHALL NOT satisfy code review, and code-review evidence SHALL NOT satisfy contract review. Historical attempts whose contributions do not survive in the current candidate SHALL NOT trigger mixed authorship. Neither review SHALL authorize APPLY, product decisions, or human merge.

#### Scenario: Valid complementary pairing accepted
- **WHEN** a job is submitted for code review with DeepSeek Direct, no surviving DeepSeek reviewer contributions exist in the candidate, direct-account and budget authority are valid, and current candidate-bound evidence is valid
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
- **GIVEN** DeepSeek review capability and sufficient review input are verified, the operator explicitly authorizes the provider and stage budget, and the reviewer identity is distinct from every surviving substantive author
- **WHEN** DeepSeek Direct returns a response through the separate review contract
- **THEN** deterministic validation SHALL bind and validate the structured review against repository, base/head SHA, generation, manifest, and reviewer identity before it can satisfy the review gate
- **AND** the existing audit runner or audit record SHALL NOT be converted into review evidence, and human merge remains a separate mandatory gate.

#### Scenario: DeepSeek final review cannot be proven or authorized
- **GIVEN** DeepSeek compatibility, complete review input, structured response validity, identity independence, or explicit provider/budget authorization is missing, stale, or ambiguous
- **WHEN** the system evaluates review eligibility
- **THEN** it SHALL reject the fallback, preserve the candidate, and wait or block without invoking an unauthorized paid call or treating audit output as review.

## ADDED Requirements

### Requirement: R01 contract review is a distinct read-only stage
For R01, CONTRACT REVIEW SHALL evaluate only the OpenSpec contract before APPLY. DeepSeek Direct SHALL be the contract reviewer only when its exact configured model and read-only capability are compatible, its own account identity and fresh capacity/balance are proven, and explicit provider/stage/budget authorization exists. If DeepSeek is not eligible, the work SHALL remain preserved and waiting; Codex, AGY, OpenRouter, or audit output SHALL NOT substitute. Contract-review evidence SHALL be distinct from audit and code-review evidence and SHALL NOT authorize APPLY, product decisions, or human merge.

#### Scenario: Authorized DeepSeek contract review is preferred
- **GIVEN** DeepSeek has a compatible read-only contract-review profile, current capacity, and explicit budget/provider/stage authorization
- **WHEN** the R01 workflow reaches CONTRACT REVIEW before APPLY
- **THEN** mini me dispatches the candidate-bound read-only contract review through the separate review contract
- **AND** records its result as contract-review evidence without granting APPLY, final-review, or merge authority.

#### Scenario: No contract reviewer is eligible
- **GIVEN** DeepSeek Direct has no compatible authorized read-only profile with current capacity/balance or explicit budget authority
- **WHEN** the R01 workflow reaches CONTRACT REVIEW
- **THEN** mini me preserves the change and waits without inference or proceeding to APPLY.

#### Scenario: Contract review cannot be promoted into another authority
- **GIVEN** a contract-review result, regardless of PASS or findings
- **WHEN** a caller attempts to use it as APPLY authorization, final code review, product decision, or merge approval
- **THEN** mini me rejects the substitution and retains the separate stage gates.

### Requirement: Deterministic failure when DeepSeek reviewer unavailable
The system SHALL preserve a candidate in a durable, observable waiting or blocked state when the required DeepSeek Direct read-only reviewer or its compatible authority is unavailable. It SHALL NOT substitute a substantive author, Codex, AGY, OpenRouter, or audit evidence for either review stage, and SHALL NOT report PR readiness without current authoritative code review.

#### Scenario: Reviewer binary or environment missing
- **GIVEN** the DeepSeek Direct review authority or runtime cannot be resolved
- **WHEN** the system attempts the review stage
- **THEN** it preserves the candidate, records an explicit diagnostic in durable state, and leaves the run waiting or blocked rather than manufacturing a successful review or PR-ready state.

#### Scenario: Required DeepSeek reviewer unavailable
- **GIVEN** DeepSeek compatibility, sufficient stage-specific input, explicit stage/provider/budget authorization, identity independence, or structured response validation is not proven
- **WHEN** review eligibility is evaluated
- **THEN** the candidate remains preserved in a truthful waiting or blocked state and does not advance to PR-ready.
