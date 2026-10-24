## Purpose
Coordinate the complete native OpenSpec Propose stage including Git workspace isolation, official OpenSpec Explore, official OpenSpec Propose, CLI strict validation, LLM-grounded complexity evaluation, and independent proposal review for high-complexity changes.

## ADDED Requirements

### Requirement: Git Branch and Worktree Preparation
The system SHALL retrieve the latest remote commit SHA of the configured base branch (`main`) from the remote repository via verified Git network fetch, SHALL create a dedicated branch named `request-<numero>-<slug-kebab>`, and SHALL prepare an isolated confined Worktree under the project's configured managed root using `WorktreeManager` before launching any workflow.

#### Scenario: Dedicated branch and worktree created from latest remote main
- **GIVEN** an eligible remote Request is admitted for execution
- **WHEN** mini me prepares the workspace
- **THEN** it executes a Git fetch for the configured remote base branch, resolves the remote commit SHA without fallback to unverified local branches, creates `request-<numero>-<slug-kebab>` pointing to that remote commit SHA, and mounts an isolated Worktree under the project's configured managed root.

#### Scenario: Existing branch and worktree preserved on continuation
- **GIVEN** a Request already has an existing valid branch and candidate worktree registered in durable state
- **WHEN** execution resumes for that Request
- **THEN** mini me verifies candidate branch identity and commit SHA against durable storage and reuses the existing worktree without overwriting or recreating it.

### Requirement: Native OpenSpec Explore with Autonomous Investigation
The system SHALL dynamically resolve the official OpenSpec Explore workflow for the thinking agent configured in the project profile (`Project.agent_profiles['thinking']`) based on workflows actually installed in the worktree (`.agent/workflows/opsx-explore.md` for Antigravity or `.agents/skills/openspec-explore/SKILL.md` for Codex) and provider prompt transport. If the workflow is missing, not a regular file, or contains symlinks, the system SHALL block fail-closed, record the missing capability, and preserve the Request. The configured thinking agent SHALL be invoked through `CliAgentRunner` within the confined worktree, SHALL autonomously investigate the full issue text, comments, attachments, images, diagrams, design documents, and repository context, and SHALL produce observable execution output containing either `READY TO PROPOSE` or a structured `HUMAN REQUIRED` payload. A completion status of Explore SHALL NOT be declared by returning a static Python string without agent process execution.

#### Scenario: Autonomous investigation by thinking agent emits READY TO PROPOSE
- **GIVEN** an admitted Request and an isolated worktree with verified official Explore workflow
- **WHEN** mini me executes the configured thinking agent via `CliAgentRunner`
- **THEN** the agent subprocess runs with exit code 0, inspects repository context, answers open technical questions autonomously referencing existing assets, and emits `READY TO PROPOSE` in its observable stdout/traces.

#### Scenario: True material ambiguity emits verbatim HUMAN REQUIRED protocol
- **GIVEN** an admitted Request where a core technical requirement cannot be resolved from codebase context
- **WHEN** the thinking agent executes Explore
- **THEN** the agent subprocess pauses and emits `HUMAN REQUIRED`, formulating concise, actionable questions in plain Spanish, preserving verbatim any OpenSpec prompts or options, distinguishing agent recommendations from native choices, and storing the prompt in durable run state without inventing synthetic options.

#### Scenario: Missing Explore workflow or failure to execute blocks fail-closed
- **GIVEN** a candidate worktree where the official Explore workflow is absent or the agent process fails
- **WHEN** Explore dispatch is attempted
- **THEN** mini me halts fail-closed, marks the stage PAUSED or BLOCKED, preserves the candidate worktree and PostgreSQL run record, and does NOT advance to Propose.

### Requirement: Native OpenSpec Propose Execution
Upon receiving `READY TO PROPOSE`, the system SHALL dynamically resolve the official OpenSpec Propose workflow for the configured thinking agent (`.agent/workflows/opsx-propose.md` for Antigravity or `.agents/skills/openspec-propose/SKILL.md` for Codex). If the workflow is not installed or incompatible, the system SHALL block fail-closed, record the missing capability, and preserve the Request. The thinking agent SHALL be invoked through `CliAgentRunner` and SHALL execute the official OpenSpec Propose workflow, producing the canonical change artifacts (`proposal.md`, `specs/`, `design.md`, `tasks.md`) under `openspec/changes/<change-name>/`. mini me SHALL NOT generate these artifacts using Python template mergers or file writers.

#### Scenario: Canonical change artifacts produced by agent executing Propose workflow
- **GIVEN** successful Explore completion with `READY TO PROPOSE`
- **WHEN** mini me invokes the thinking agent to execute the resolved official Propose workflow
- **THEN** the agent process runs in the confined worktree, executes the OpenSpec Propose command natively, produces `proposal.md`, delta specifications under `specs/`, `design.md`, and `tasks.md`, and records observable tool execution evidence.

#### Scenario: Simulation of Propose artifacts via Python string templates is prohibited
- **GIVEN** the Propose stage is active
- **WHEN** artifact generation is evaluated
- **THEN** mini me verifies that artifacts originated from the executed agent workflow, and rejects any execution that writes synthetic Markdown files via Python string formatting.

### Requirement: Strict CLI Validation and Correction Loop
Following Propose execution, the system SHALL execute the official CLI command `openspec validate <change-name> --strict --no-interactive` in the worktree. If validation returns exit code 0, the change advances to complexity evaluation. If validation fails (exit code != 0), the system SHALL capture the exact CLI stdout/stderr report, deliver it to the thinking agent in an OpenSpec update correction prompt, and re-execute CLI validation up to the project's configured correction retry limit.

#### Scenario: Successful strict validation advances change
- **GIVEN** canonical change artifacts generated in `openspec/changes/<change-name>/`
- **WHEN** mini me runs `openspec validate <change-name> --strict --no-interactive`
- **THEN** the CLI process terminates with exit code 0 and empty error report, marking the stage VALIDATING as PASS.

#### Scenario: Validation failure triggers authentic agent correction pass
- **GIVEN** `openspec validate` returns a non-zero exit code with defect diagnostics
- **WHEN** the correction loop runs within the configured retry limit
- **THEN** mini me delivers the raw CLI diagnostics to the thinking agent, invokes the native update workflow, re-runs strict validation, and pauses preserving the worktree if retries are exhausted without achieving exit code 0.

### Requirement: Grounded Complexity Evaluation
Following successful strict validation, the thinking agent SHALL evaluate the change complexity as `low`, `moderate`, or `high` based on architectural scope, risk, and touchpoints through an LLM evaluation prompt, recording its rationale in durable state. Complexity SHALL NOT be determined via deterministic keyword regex or static heuristic rules.

#### Scenario: Low or moderate complexity proceeds directly to Apply
- **GIVEN** a strictly validated OpenSpec change
- **WHEN** the thinking agent evaluates complexity as `low` or `moderate`
- **THEN** the run records the complexity verdict and transitions directly to `READY TO APPLY`, skipping independent proposal review.

#### Scenario: High complexity mandates independent proposal review
- **GIVEN** a strictly validated OpenSpec change
- **WHEN** the thinking agent evaluates complexity as `high`
- **THEN** the run transitions to `PROPOSAL_REVIEW`, mandating independent reviewer evaluation before Apply.

### Requirement: Independent Proposal Review for High Complexity
For high-complexity changes, the system SHALL invoke the configured independent reviewer agent (`Project.agent_profiles['independent_review']`), who MUST be a distinct agent from the thinking agent author. The reviewer SHALL be invoked with a read-only review prompt, SHALL NOT have write permissions or OpenSpec authoring CLI access, and SHALL evaluate requirement completeness, architectural simplicity, security, and testability. An unconditional `return True` or static stub SHALL NOT be accepted as proposal review.

#### Scenario: Independent reviewer approves high-complexity proposal
- **GIVEN** a high-complexity proposal awaiting review
- **WHEN** the independent reviewer agent process executes in read-only confinement
- **THEN** the reviewer evaluates the proposal artifacts, returns an affirmative verdict with structured rationale, and mini me transitions the stage to `READY TO APPLY`.

#### Scenario: Independent reviewer rejects with actionable findings
- **GIVEN** a high-complexity proposal awaiting review
- **WHEN** the independent reviewer identifies gaps, missing scenarios, or excessive complexity
- **THEN** the reviewer outputs concrete actionable findings, and mini me routes the report back to the thinking agent via native OpenSpec update, requiring re-validation and re-review.
