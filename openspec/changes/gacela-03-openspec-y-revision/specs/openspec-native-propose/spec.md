## Purpose
Coordinate the complete native OpenSpec Propose stage including Git workspace isolation, official OpenSpec Explore, official OpenSpec Propose, CLI strict validation, LLM-grounded complexity evaluation, and independent proposal review for high-complexity changes.

## ADDED Requirements

### Requirement: Git Branch and Worktree Preparation
The system SHALL retrieve the latest remote commit SHA of the configured base branch (`main`), SHALL create a dedicated branch named `request-<numero>-<slug-kebab>`, and SHALL prepare an isolated confined Worktree under the project's configured managed root using `WorktreeManager` before launching any workflow.

#### Scenario: Dedicated branch and worktree created from latest main
- **WHEN** an eligible Request is admitted for execution
- **THEN** the system updates the remote base branch reference, creates `request-<numero>-<slug-kebab>` from that remote HEAD, and mounts an isolated Worktree under the project's resolved managed worktree directory.

#### Scenario: Existing branch and worktree preserved on continuation
- **WHEN** a Request already has an existing valid branch and candidate worktree
- **THEN** the system verifies identity and commit SHA and reuses the existing branch and worktree without overwriting or duplicating them.

### Requirement: Native OpenSpec Explore with Autonomous Investigation
The system SHALL dynamically resolve the official OpenSpec Explore workflow for the configured thinking agent based on the workflows actually installed in the worktree (`.agent/workflows/opsx-explore.md` for Antigravity or `.agents/skills/openspec-explore/SKILL.md` for Codex) and provider prompt transport. If the workflow is missing or incompatible, the system SHALL block fail-closed, report the missing capability, and preserve the Request. The configured thinking agent SHALL invoke the resolved workflow within the isolated worktree, SHALL autonomously investigate the full issue text, comments, attachments, images, diagrams, design documents, and repository context, and SHALL emit `READY TO PROPOSE` or `HUMAN REQUIRED`.

#### Scenario: Autonomous resolution produces ready to propose
- **WHEN** the thinking agent finds sufficient context in the repository and issue assets to clarify requirements
- **THEN** the agent answers open technical questions autonomously, references the source of clarification, and returns `READY TO PROPOSE`.

#### Scenario: Truly irresoluble ambiguity produces human required
- **WHEN** a material ambiguity cannot be resolved from existing context and requires human authority
- **THEN** the agent pauses with `HUMAN REQUIRED`, formulating concise, actionable questions in plain Spanish, preserving verbatim OpenSpec prompts, distinguishing agent-elaborated recommendations, and resuming immediately upon human answer.

### Requirement: Native OpenSpec Propose Execution
Upon receiving `READY TO PROPOSE`, the system SHALL dynamically resolve the official OpenSpec Propose workflow for the thinking agent based on the workflows actually installed in the worktree (`.agent/workflows/opsx-propose.md` for Antigravity or `.agents/skills/openspec-propose/SKILL.md` for Codex) and provider prompt transport. If the workflow is not installed or incompatible, the system SHALL block fail-closed, record the missing capability, and preserve the Request. The thinking agent SHALL invoke the resolved workflow, SHALL generate the canonical change artifacts (`proposal.md`, `specs/`, `design.md`, `tasks.md`) under `openspec/changes/<change-name>/`, and SHALL emit `READY TO VALIDATE`.

#### Scenario: Canonical change artifacts generated natively
- **WHEN** `READY TO PROPOSE` is achieved
- **THEN** the thinking agent executes the resolved official OpenSpec Propose workflow, producing `proposal.md`, delta specifications, `design.md`, and `tasks.md` without python template generation by mini me.

### Requirement: Strict CLI Validation and Correction Loop
The system SHALL execute the installed official CLI command `openspec validate <change-name> --strict --no-interactive`, and if validation fails, SHALL return the CLI findings report to the thinking agent to correct artifacts via the native OpenSpec update workflow and re-validate up to the configured retry limit.

#### Scenario: Successful strict validation advances change
- **WHEN** the CLI validation returns exit code 0
- **THEN** the change is marked structurally valid and advances to complexity assessment.

#### Scenario: Validation failure triggers automatic correction
- **WHEN** CLI validation detects missing sections, invalid schemas, or formatting defects
- **THEN** mini me delivers the exact error output to the thinking agent, invokes native update/continuation, and repeats CLI validation without human interruption.

### Requirement: Grounded Complexity Evaluation
Following successful strict validation, the thinking agent SHALL evaluate the change complexity as `low`, `moderate`, or `high` based on scope, architectural impact, and risks, without using an artificial deterministic scoring algorithm or Python classifier.

#### Scenario: Low or moderate complexity proceeds to apply
- **WHEN** the thinking agent assesses complexity as `low` or `moderate`
- **THEN** the proposal emits `READY TO APPLY`, skipping independent proposal review.

#### Scenario: High complexity mandates independent proposal review
- **WHEN** the thinking agent assesses complexity as `high`
- **THEN** the proposal emits `READY FOR INDEPENDENT REVIEW`.

### Requirement: Independent Proposal Review for High Complexity
For high-complexity changes, the system SHALL invoke the configured independent reviewer agent with a read-only review prompt, SHALL NOT provide an OpenSpec CLI or write permissions, and SHALL require independent approval before transitioning to Apply.

#### Scenario: Independent reviewer approves high-complexity proposal
- **WHEN** the independent reviewer verifies requirement coverage, architectural alignment, security, and simplicity
- **THEN** the reviewer approves the proposal and the state transitions to `READY TO APPLY`.

#### Scenario: Independent reviewer reports actionable defects
- **WHEN** the independent reviewer identifies functional gaps, overengineering, or security concerns
- **THEN** the findings are returned to the thinking agent to adjust artifacts via native OpenSpec, re-validate with the CLI, and submit for re-review.
