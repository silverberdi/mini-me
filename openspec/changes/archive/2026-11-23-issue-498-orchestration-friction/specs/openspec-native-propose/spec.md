## MODIFIED Requirements

### Requirement: Native OpenSpec Explore with Autonomous Investigation
The system SHALL dynamically resolve the official OpenSpec Explore workflow for the thinking agent configured in the project profile (`Project.agent_profiles['thinking']`) based on workflows actually installed in the worktree and provider prompt transport. If the workflow is missing, not a regular file, or contains symlinks, the system SHALL block fail-closed, record the missing capability, and preserve the Request. The configured thinking agent SHALL be invoked through `CliAgentRunner` within the confined worktree and SHALL autonomously investigate the full issue text, comments, attachments, images, diagrams, design documents, and repository context. Explore completion SHALL be determined from the native workflow result and observable output/artifacts, not a required exact prose sentinel. A genuine structured `HUMAN REQUIRED` result SHALL preserve the original question and options. Missing, failed, or ambiguous execution evidence SHALL remain blocked with a concrete reason and an actionable existing recovery path; it SHALL NOT be converted into an opaque `PAUSED` state.

#### Scenario: Autonomous investigation by thinking agent emits READY TO PROPOSE
- **GIVEN** an admitted Request and an isolated worktree with the verified official Explore workflow
- **WHEN** the configured thinking agent completes Explore successfully and its native result and required outputs are observable, even if stdout omits a specific `READY TO PROPOSE` line
- **THEN** mini me records Explore as complete and proceeds through the existing OpenSpec Propose workflow
- **AND** it records the invocation evidence rather than inferring success from prose alone.

#### Scenario: True material ambiguity emits verbatim HUMAN REQUIRED protocol
- **GIVEN** an admitted Request where a core technical requirement cannot be resolved from repository and project context
- **WHEN** the native Explore workflow returns a genuine human-required question
- **THEN** mini me preserves the original question and options, presents them through the current human gate, and resumes only after an operator response
- **AND** it does not invent options or auto-authorize a human decision.

#### Scenario: Missing Explore workflow or failure to execute blocks fail-closed
- **GIVEN** a candidate worktree where the official Explore workflow is absent or the agent process fails
- **WHEN** Explore dispatch or result verification is attempted
- **THEN** mini me blocks advancement, preserves the candidate and run record, and reports the observed missing capability or execution failure with the recovery action available through the existing workflow.

### Requirement: Native OpenSpec Propose Execution
The system SHALL dynamically resolve the official OpenSpec Propose workflow for the configured thinking agent based on the workflow actually installed in the worktree and provider prompt transport. If the workflow is not installed or incompatible, the system SHALL block fail-closed, record the missing capability, and preserve the Request. After successful Explore, the thinking agent SHALL be invoked through `CliAgentRunner` and SHALL execute the official OpenSpec Propose workflow, producing canonical change artifacts (`proposal.md`, `specs/`, `design.md`, `tasks.md`) under `openspec/changes/<change-name>/`. Completion SHALL be based on the subprocess result, native OpenSpec validation, and observable artifacts; a required agent-authored `MINIME_WORKFLOW_RESULT` token or exact Explore sentinel SHALL NOT be the sole completion authority. mini me SHALL NOT generate these artifacts using Python template mergers or file writers.

#### Scenario: Canonical change artifacts produced by agent executing Propose workflow
- **GIVEN** successful Explore completion with observable execution evidence
- **WHEN** mini me invokes the resolved official Propose workflow
- **THEN** the agent process runs in the confined worktree, executes the native OpenSpec Propose workflow, produces the canonical change artifacts, and records observable tool execution evidence
- **AND** strict OpenSpec CLI validation remains required before the change advances.

#### Scenario: Missing or invalid Propose artifacts block advancement
- **GIVEN** a Propose invocation exits successfully but required artifacts are absent, inconsistent, or fail native OpenSpec validation
- **WHEN** mini me evaluates stage completion
- **THEN** it does not infer completion from narrative or a model-authored token
- **AND** it reports the actual missing/invalid evidence and routes correction through the existing native OpenSpec workflow.

#### Scenario: Simulation of Propose artifacts via Python string templates is prohibited
- **GIVEN** the Propose stage is active
- **WHEN** artifact generation is evaluated
- **THEN** mini me accepts only artifacts produced by the configured agent executing the official OpenSpec workflow and does not synthesize them with Python templates or file writers.
