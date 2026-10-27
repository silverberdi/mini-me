## MODIFIED Requirements

### Requirement: Native OpenSpec Explore with Autonomous Investigation

The system SHALL dynamically resolve the official OpenSpec Explore workflow for the thinking agent configured in the project profile (`Project.agent_profiles['thinking']`) based on workflows actually installed in the worktree (`.agent/workflows/opsx-explore.md` for Antigravity or `.agents/skills/openspec-explore/SKILL.md` for Codex) and provider prompt transport. If the workflow is missing, not a regular file, or contains symlinks, the system SHALL block fail-closed, record the missing capability, and preserve the Request. The configured thinking agent SHALL be invoked through `CliAgentRunner` within the confined worktree, SHALL autonomously investigate the full issue text, comments, attachments, images, diagrams, design documents, and repository context, and SHALL produce an **unambiguous authoritative final response** with either `READY TO PROPOSE` (also accepting the verified compatibility spelling `READY_TO_PROPOSE`) or `HUMAN REQUIRED` with concrete original options. The system SHALL parse this outcome from the verified final agent message and SHALL NOT treat incidental mentions in diagnostic/tool output, citations or context as current dispositions. The system SHALL distinguish truncated diagnostics from incomplete final answers; a positive transition SHALL require evidenced native execution and a complete final answer, never a static Python string or an exit code alone.

#### Scenario: Autonomous investigation by thinking agent emits READY TO PROPOSE

- **GIVEN** an admitted Request and an isolated worktree with verified official Explore workflow
- **WHEN** mini me executes the configured thinking agent via `CliAgentRunner`
- **THEN** the agent subprocess SHALL run with exit code zero, inspect repository context, answer open technical questions autonomously referencing existing assets, and emit a final `READY TO PROPOSE` (or `READY_TO_PROPOSE`) verdict in the verified response channel
- **AND** mini me SHALL advance toward Propose only when the outcome is unambiguous and response integrity is complete

#### Scenario: True material ambiguity emits verbatim HUMAN REQUIRED protocol

- **GIVEN** an admitted Request where a core technical requirement cannot be resolved from codebase context
- **WHEN** the thinking agent executes Explore
- **THEN** the agent subprocess SHALL pause and emit a final `HUMAN REQUIRED`, formulating concise, actionable questions in plain Spanish, preserving verbatim any OpenSpec prompts or options, distinguishing agent recommendations from native choices, and storing the prompt in durable Run state without inventing synthetic options

#### Scenario: Missing Explore workflow or failure to execute blocks fail-closed

- **GIVEN** a candidate worktree where the official Explore workflow is absent or the agent process fails
- **WHEN** Explore dispatch is attempted
- **THEN** mini me SHALL halt fail-closed, mark the stage PAUSED or BLOCKED, preserve the candidate worktree and PostgreSQL Run record, and NOT advance to Propose

#### Scenario: Operator clarification resolved despite historical HUMAN REQUIRED references

- **GIVEN** a response whose authoritative final disposition is `READY_TO_PROPOSE` and whose context/tool events mention a prior `HUMAN REQUIRED`
- **WHEN** the final verdict is evaluated
- **THEN** the historical mention SHALL NOT create a new human gate
- **AND** the native workflow SHALL progress to Propose without inventing authorization

#### Scenario: Multiple formal final dispositions are ambiguous

- **GIVEN** a purported final response contains competing standalone `READY TO PROPOSE` and `HUMAN REQUIRED` dispositions
- **WHEN** Explore evaluates the answer
- **THEN** it SHALL stop as ambiguous and SHALL NOT choose the last or first marker by convenience

#### Scenario: Long Codex diagnostic line does not invalidate final verdict

- **GIVEN** the operator clarification is 4,715 characters and Codex emits an NDJSON diagnostic event longer than 4,000 characters
- **WHEN** the completed final assistant message is separately verified
- **THEN** the diagnostic truncation SHALL NOT itself block a valid `READY TO PROPOSE` verdict
- **AND** a truncated, absent or unconfirmed final message SHALL still block progression
