# Delta Specification: Spanish Independent Proposal Review & Fresh Review Re-entry

## MODIFIED Requirements

### Requirement: Independent Proposal Review for High Complexity
For high-complexity changes, the system SHALL invoke the configured independent reviewer agent (`Project.agent_profiles['independent_review']`), who MUST be a distinct agent from the thinking agent author. The reviewer SHALL be invoked with a read-only review prompt that mandates all findings, summaries, and expected corrections to be emitted in clear, simple Spanish. The reviewer SHALL NOT have write permissions or OpenSpec authoring CLI access, and SHALL evaluate requirement completeness, architectural simplicity, security, and testability. An unconditional `return True` or static stub SHALL NOT be accepted as proposal review. When entering or resuming `PROPOSAL_REVIEW` without a prior recorded review result (or following an authorized proposal revision), the system SHALL classify the stage state as ready for fresh dispatch without treating the absence of review evidence as ambiguous. If independent proposal review reaches its configured attempt limit without approval, the system SHALL expose the available structured findings in the current human-gate payload and explain in simple Spanish what was found, where, why it matters, the requested correction, and why review stopped. It SHALL preserve original reviewer wording as labeled evidence and make the operator's required decision explicit. Native options, when present, SHALL be preserved; any system-generated alternatives SHALL be labeled as such and include consequences. If no safe discrete alternatives exist, the gate SHALL accept a free-text response. An operator response SHALL NOT by itself approve the proposal or bypass the required independent review.

#### Scenario: Independent reviewer approves high-complexity proposal
- **GIVEN** a high-complexity proposal awaiting review
- **WHEN** the independent reviewer agent process executes in read-only confinement
- **THEN** the reviewer evaluates the proposal artifacts, returns an affirmative verdict with structured rationale in simple Spanish, and mini me transitions the stage to `READY TO APPLY`.

#### Scenario: Independent reviewer rejects with actionable findings
- **GIVEN** a high-complexity proposal awaiting review
- **WHEN** the independent reviewer identifies gaps, missing scenarios, or excessive complexity
- **THEN** the reviewer outputs concrete actionable findings in simple Spanish, and mini me routes the report back to the thinking agent via native OpenSpec update, requiring re-validation and re-review.

#### Scenario: Attempt limit exposes actionable findings without approving the proposal
- **GIVEN** independent proposal review reaches its configured attempt limit with one or more structured findings
- **WHEN** the workflow escalates to the operator
- **THEN** the active gate includes the available finding details and an understandable Spanish decision request
- **AND** accepting the operator's response does not set an approved verdict or skip required independent review.

#### Scenario: Fresh proposal review dispatches without ambiguous pause on re-entry
- **GIVEN** a Run entering or resuming `PROPOSAL_REVIEW` after a proposal creation or authorized revision
- **WHEN** the coordinator checks durable review state and finds no recorded review result for the current candidate
- **THEN** it classifies the stage as ready for fresh review dispatch
- **AND** it does not pause the run for ambiguous recovery authorization.
