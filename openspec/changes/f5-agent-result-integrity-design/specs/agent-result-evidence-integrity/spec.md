## ADDED Requirements

### Requirement: Authoritative final answer is separate from diagnostic output

The existing agent execution transport SHALL expose the provider's **complete authoritative final answer** separately from diagnostic/tool output, with explicit provenance and integrity state. The system SHALL NOT treat truncation of diagnostic output as truncation of the final answer, and SHALL NOT treat an arbitrary substring in diagnostics, stderr, quoted history, issue text, or tool logs as a stage verdict. A final answer that is absent, partial, malformed, ambiguous, untrusted or over its verified safe size SHALL NOT authorize any stage transition.

#### Scenario: Long diagnostic event with complete final answer

- **GIVEN** a confined Codex NDJSON execution includes a 4,715-character tool event and a valid final assistant message with a confirmed successful turn
- **WHEN** the runner bounds diagnostic output to its configured retention policy
- **THEN** the diagnostic truncation SHALL be reported separately
- **AND** the complete final message SHALL remain available to its validating stage
- **AND** the system SHALL NOT fail only because the diagnostic exceeded 4,000 characters

#### Scenario: Truncated final answer is not silently accepted

- **GIVEN** a final agent message is truncated, oversized, undecodable or not completely delimited
- **WHEN** a consumer requests the authoritative result
- **THEN** the integrity status SHALL be incomplete or unknown
- **AND** the current Run SHALL remain at its last verified checkpoint with no automatic retry
- **AND** no positive stage outcome SHALL be inferred from exit code zero or a partial token

#### Scenario: Tool or stderr claims success but final answer is missing

- **GIVEN** stdout/stderr or a tool event contains an apparent `READY_TO_PROPOSE` or approval while the final assistant message is absent
- **WHEN** a stage evaluator examines the execution
- **THEN** it SHALL refuse to advance and report missing authoritative evidence

### Requirement: Provider-aware response extraction without emulating native workflows

The existing `CliAgentRunner` SHALL select a verified native response channel compatible with each configured provider/CLI/workflow and SHALL preserve exact final-message semantics without reimplementing OpenSpec reasoning. Codex and Antigravity SHALL NOT be assumed to have identical event grammars. Unknown provider capabilities or unobservable termination SHALL block the affected operation, not guess an alternate provider or workflow.

#### Scenario: Codex NDJSON has complete final turn

- **GIVEN** a Codex CLI invocation returns NDJSON with tool events, `item.completed` agent messages and `turn.completed`
- **WHEN** the result is extracted
- **THEN** only the verified final assistant message of the completed turn SHALL be eligible as authoritative
- **AND** command/tool events, previous agent messages and diagnostic event content SHALL NOT supersede it

#### Scenario: Codex execution ended unsuccessfully or ambiguously

- **GIVEN** a Codex stream contains `turn.failed`, no terminal turn event, contradictory terminal events or malformed event frames
- **WHEN** final-answer evidence is evaluated
- **THEN** the result SHALL be classified failed or ambiguous and no positive transition SHALL occur
- **AND** a previously dispatched attempt SHALL NOT be automatically replayed

#### Scenario: Antigravity response contract is not verified

- **GIVEN** a configured Antigravity CLI or model emits text/events not mapped to an observed supported final-response format
- **WHEN** a workflow requires an authoritative response
- **THEN** mini me SHALL preserve the Run and stop without inventing Codex-style event metadata
- **AND** it SHALL NOT substitute another provider, model or paid fallback without authorization

#### Scenario: Existing structured last-message response is intact

- **GIVEN** a provider natively supports the verified last-message channel and a schema-bound 4,500-character JSON result fits within the final-answer byte limit
- **WHEN** diagnostics exceed their line-length limit
- **THEN** the JSON response SHALL remain intact and independently validated
- **AND** only its verified structure and provenance may control the stage

### Requirement: Safe output bounds, redaction and transport provenance

Agent output capture SHALL apply independent, finite limits to diagnostic retention and complete final-answer bytes, preserve evidence of truncation and terminal state, and sanitize sensitive information before persistence or publication. It SHALL retain the established confinement, authorization, symlink, credential-rotation, timeout and workflow integrity guards. It SHALL NOT persist raw secrets or full user prompts as routine operational metadata.

#### Scenario: Oversized response fails closed without exhausting memory

- **GIVEN** a provider emits a final response larger than the configured verified limit
- **WHEN** the response channel is read
- **THEN** the result SHALL be marked incomplete or oversized before an unsafe allocation or parse
- **AND** only redacted bounded diagnostics SHALL be retained

#### Scenario: Credential or prompt echoed in tool output

- **GIVEN** diagnostics include credentials or the complete original operator clarification
- **WHEN** the runner saves/logs an attempt
- **THEN** secrets and unnecessary prompt bodies SHALL NOT appear in GitHub, database summaries, API responses or persistent logs
- **AND** only authenticated, scope-bound and sanitized provenance SHALL remain

#### Scenario: Timeout during final event

- **GIVEN** a subprocess times out after emitting a partial final assistant event
- **WHEN** the confined process terminates
- **THEN** timeout SHALL override any apparently affirmative fragment
- **AND** the Run SHALL preserve ownership and prevent automatic retry

### Requirement: Stage-specific evidence cannot be replaced by generic runner success

All stage consumers SHALL use the shared transport's authoritative channel for **decisions** and retain their specific independent acceptance gates (native OpenSpec artifacts and strict validation, candidate SHA, tests, independent reviews, provider quota and authorized human actions). The runner SHALL NOT decide business semantics, approvals or stage transitions. Unchanged sources such as GitHub remain authoritative for their own effects.

#### Scenario: Propose agent exit zero without canonical files

- **GIVEN** Propose returns exit code zero and an affirmative text answer without canonical change artifacts
- **WHEN** the coordinator evaluates READY_TO_VALIDATE
- **THEN** it SHALL block until genuine native-generated artifacts exist and strict CLI validation succeeds

#### Scenario: Reviewer logs contain an affirmative JSON object but final answer does not

- **GIVEN** a reviewer's stderr or tool log includes a syntactically valid approval JSON while the final answer has no valid review payload
- **WHEN** proposal or code review is evaluated
- **THEN** the review SHALL NOT authorize a positive transition or merge
- **AND** reviewer independence and candidate-bound evidence SHALL remain mandatory

#### Scenario: Verify result and tests disagree

- **GIVEN** a valid Verify final verdict claims success but required tests or native verification fail
- **WHEN** the coordinator evaluates READY_FOR_PR
- **THEN** it SHALL stop and retain the candidate until both independent sources agree

#### Scenario: Sync and Archive only appear in agent narrative

- **GIVEN** an agent states that Sync or Archive completed but the canonical files or CLI observations do not confirm it
- **WHEN** PR2 or Issue closure is evaluated
- **THEN** the coordinator SHALL refuse documentary closure and preserve the current Change