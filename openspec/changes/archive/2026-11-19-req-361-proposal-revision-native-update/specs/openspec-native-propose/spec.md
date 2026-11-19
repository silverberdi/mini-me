# openspec-native-propose Delta Specification

## MODIFIED Requirements

### Requirement: Independent Proposal Review for High Complexity
For high-complexity changes, the system SHALL invoke the configured independent reviewer agent (`Project.agent_profiles['independent_review']`), who MUST be a distinct agent from the thinking agent author. The reviewer SHALL be invoked with a read-only review prompt, SHALL NOT have write permissions or OpenSpec authoring CLI access, and SHALL evaluate requirement completeness, architectural simplicity, security, and testability. An unconditional `return True` or static stub SHALL NOT be accepted as proposal review. If independent proposal review reaches its configured attempt limit without approval, the system SHALL expose the available structured findings in the current human-gate payload and explain in simple Spanish what was found, where, why it matters, the requested correction, and why review stopped. It SHALL preserve original reviewer wording as labeled evidence and make the operator's required decision explicit. When independent proposal review returns actionable findings or the operator authorizes proposal corrections through a human gate, the system SHALL dispatch the thinking agent using the official OpenSpec Update workflow (`openspec-update-change`), SHALL NOT dispatch `openspec-continue-change` when planning artifacts already exist, SHALL authorize stage re-entry in durable stage invocation guards (`_begin_stage_invocation`), and SHALL release distributed recovery claims cleanly without leaving unexpired leases.

#### Scenario: Independent reviewer approves high-complexity proposal
- **GIVEN** a high-complexity proposal awaiting review
- **WHEN** the independent reviewer agent process executes in read-only confinement
- **THEN** the reviewer evaluates the proposal artifacts, returns an affirmative verdict with structured rationale, and mini me transitions the stage to `READY TO APPLY`.

#### Scenario: Independent reviewer rejects with actionable findings
- **GIVEN** a high-complexity proposal awaiting review
- **WHEN** the independent reviewer identifies gaps, missing scenarios, or excessive complexity
- **THEN** the reviewer outputs concrete actionable findings, and mini me routes the report back to the thinking agent via native OpenSpec update, requiring re-validation and re-review.

#### Scenario: Attempt limit exposes actionable findings without approving the proposal
- **GIVEN** independent proposal review reaches its configured attempt limit with one or more structured findings
- **WHEN** the workflow escalates to the operator
- **THEN** the active gate includes the available finding details and an understandable Spanish decision request
- **AND** accepting the operator's response does not set an approved verdict or skip required independent review.

#### Scenario: Proposal review corrections dispatched via native Update workflow
- **GIVEN** a proposal has completed planning artifacts and pending reviewer findings (`pending_proposal_revision`)
- **WHEN** mini me re-enters the PROPOSING stage to apply the corrections
- **THEN** it resolves and dispatches the official `openspec-update-change` workflow with the operation `update`
- **AND** the prompt includes the reviewer findings and operator clarification
- **AND** it does NOT dispatch `openspec-continue-change`.

#### Scenario: Authorized revision permits stage re-entry on same candidate
- **GIVEN** a candidate worktree with an existing completed or failed propose invocation
- **WHEN** `_begin_stage_invocation` evaluates stage entry with authorized revision or retry
- **THEN** it permits the invocation without blocking fail-closed and returns a valid `StageInvocation` claim context.

#### Scenario: Ambiguous or rejected invocation releases dispatch claim cleanly
- **GIVEN** `_begin_stage_invocation` returns `None` during native dispatch
- **WHEN** `_run_native_dispatch` handles the refusal
- **THEN** it marks the action ambiguous and releases the distributed recovery claim
- **AND** does NOT leave an active 90-second lease blocking subsequent scheduling cycles.
