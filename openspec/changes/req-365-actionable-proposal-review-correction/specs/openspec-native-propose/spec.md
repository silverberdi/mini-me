## MODIFIED Requirements

### Requirement: Independent Proposal Review for High Complexity
For high-complexity changes, the system SHALL invoke the configured independent reviewer agent (`Project.agent_profiles['independent_review']`), who MUST be a distinct agent from the thinking agent author. The reviewer SHALL be invoked with a read-only review prompt, SHALL NOT have write permissions or OpenSpec authoring CLI access, and SHALL evaluate requirement completeness, architectural simplicity, security, and testability. An unconditional `return True` or static stub SHALL NOT be accepted as proposal review. If independent proposal review reaches its configured attempt limit without approval, the system SHALL expose the available structured findings in the current human-gate payload and explain in simple Spanish what was found, where, why it matters, the requested correction, and why review stopped. It SHALL preserve original reviewer wording as labeled evidence and make the operator's required decision explicit. Native options, when present, SHALL be preserved verbatim; any system-generated alternatives SHALL be labeled as such and include consequences. When actionable findings all contain a non-empty `expected_correction`, the gate SHALL provide a complete system-generated correction directive that includes every such correction in reviewer order and SHALL NOT use a generic-only correction instruction. Selecting that alternative SHALL place its complete directive in the operator clarification and the resumed native OpenSpec Propose invocation SHALL receive that accepted text. If a finding lacks a concrete expected correction or no safe complete directive can be composed, the system SHALL NOT invent missing instructions and SHALL allow free-text input. An operator response SHALL NOT by itself approve the proposal or bypass the required independent review.

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

#### Scenario: Generated correction directive covers every actionable finding
- **GIVEN** independent proposal review reaches its configured attempt limit
- **AND** every actionable finding includes a non-empty `expected_correction`
- **WHEN** the system prepares the current human gate
- **THEN** it offers a clearly labeled system-generated correction alternative whose displayed directive includes every finding's expected correction in the original reviewer order
- **AND** any native options remain available with their original wording
- **AND** the directive is not reduced to a generic instruction such as “Pedir corrección y nueva revisión”.

#### Scenario: Selecting the correction alternative resumes Propose with the full directive
- **GIVEN** the operator selects the system-generated correction alternative
- **WHEN** the existing response path accepts the response and resumes the same proposal revision
- **THEN** the clarification field and accepted operator response contain the complete displayed directive
- **AND** native OpenSpec Propose receives that exact accepted text on the same Run and Change
- **AND** the revised proposal remains subject to the configured independent review.

#### Scenario: Incomplete reviewer corrections do not produce invented instructions
- **GIVEN** at least one actionable finding is missing a concrete `expected_correction`
- **WHEN** the system prepares the current human gate
- **THEN** it preserves and displays the available reviewer evidence
- **AND** it does not fill the gap with guessed corrective text or present a generic correction option as complete
- **AND** it allows the operator to provide free-text direction.
