# openspec-native-propose Specification

## Purpose
Coordinate the complete native OpenSpec Propose stage including Git workspace isolation, official OpenSpec Explore, official OpenSpec Propose, CLI strict validation, LLM-grounded complexity evaluation, and independent proposal review for high-complexity changes.

## Requirements

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
Following successful strict validation and a passing task-executability assessment, the thinking agent SHALL evaluate the change complexity as `low`, `moderate`, or `high` based on architectural scope, risk, and touchpoints through an LLM evaluation prompt, recording its rationale in durable state. Complexity SHALL NOT be determined via deterministic keyword regex or static heuristic rules.

#### Scenario: Low or moderate complexity proceeds directly to Apply
- **GIVEN** a strictly validated OpenSpec change with every task assessed executable
- **WHEN** the thinking agent evaluates the change as `low` or `moderate`
- **THEN** the run records the complexity verdict and transitions directly to `READY TO APPLY`, skipping independent proposal review.

#### Scenario: High complexity mandates independent proposal review
- **GIVEN** a strictly validated OpenSpec change with every task assessed executable
- **WHEN** the thinking agent evaluates the change as `high`
- **THEN** the run transitions to `PROPOSAL_REVIEW`, mandating independent reviewer evaluation before Apply.

### Requirement: Independent Proposal Review for High Complexity
For high-complexity changes, the system SHALL invoke the configured independent reviewer agent (`Project.agent_profiles['independent_review']`), who MUST be a distinct agent from the thinking agent author. The reviewer SHALL be invoked with a read-only review prompt, SHALL NOT have write permissions or OpenSpec authoring CLI access, and SHALL evaluate requirement completeness, architectural simplicity, security, and testability. An unconditional `return True` or static stub SHALL NOT be accepted as proposal review. If independent proposal review reaches its configured attempt limit without approval, the system SHALL expose the available structured findings in the current human-gate payload and explain in simple Spanish what was found, where, why it matters, the requested correction, and why review stopped. It SHALL preserve original reviewer wording as labeled evidence and make the operator's required decision explicit. Native options, when present, SHALL be preserved; any system-generated alternatives SHALL be labeled as such and include consequences. If no safe discrete alternatives exist, the gate SHALL accept a free-text response. An operator response SHALL NOT by itself approve the proposal or bypass the required independent review.

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

### Requirement: Evidence-backed task executability before proposal acceptance
After native Propose and strict validation, the system SHALL assess every OpenSpec task required for delivery. Each assessment SHALL identify the task, the stage at which it is performed, its responsible actor, the capability and dependencies needed by that stage, and observable completion evidence, tied to repository or project evidence. Each acceptance scenario SHALL map to one or more tasks and the stage-specific evidence that will satisfy it. The proposal SHALL establish an authorized executable path for every mandatory task across its planned stages. A future-stage capability need not be available before Apply, but its responsible actor and authorized path SHALL be evidenced rather than assumed; the capability and result SHALL be verified before entering the stage that consumes them. The system SHALL evaluate a dependency at the transition that first requires it: a deliverable produced by Apply SHALL NOT be required before Apply, and an unmet dependency for Verify or a later stage SHALL NOT by itself prevent entry to Apply. Later-stage work SHALL remain explicitly pending and SHALL be checked before entering the stage that needs it. A task with no responsible actor or no authorized executable path in any planned stage SHALL keep the proposal unaccepted. Unknown task stage or dependency mapping SHALL keep the assessment incomplete and be reported as a gap, without claiming that a specific external capability is unavailable before Apply. The active gate SHALL identify the blocked transition, affected task, and evidence needed to re-evaluate it. A project CI/CD deployment that occurs only after PR merge SHALL NOT count as candidate preview capability before a stage that explicitly requires pre-merge candidate validation; Mini Me SHALL NOT add deployment capability, mark future tasks complete, or allow free-text authorization to override a real unmet dependency. After the Request, task plan, or project capability evidence changes, the system SHALL re-run native OpenSpec Update/strict validation as applicable and reassess the affected tasks against the resulting artifact and capability evidence.

When the operator selects the active feasibility gate option to update the proposal, the system SHALL invoke the installed native OpenSpec Update workflow for the same Run and Change, pass the gate's observed blockers and the complete persisted structured assessment (task feasibility, scenario coverage, candidate SHA, and artifact/context hashes) as corrective context, strictly validate the resulting artifacts, and reassess them against their new hashes. The Update context SHALL identify malformed task references and missing, extra, or duplicate scenario mappings from that assessment so native Update can reconcile them against the authoritative OpenSpec task/scenario inventory. That selection authorizes the revision but SHALL NOT itself satisfy or bypass any feasibility blocker. Selecting an evidence option SHALL NOT invoke Update and SHALL require the cited evidence to be independently observed.

#### Scenario: All tasks have confirmed executable paths
- **GIVEN** a strictly validated proposal whose tasks each identify an authorized actor, execution stage, stage dependencies, and observable evidence
- **AND** each acceptance scenario maps to task evidence at its required stage
- **AND** dependencies required before Apply are currently satisfied
- **WHEN** executability is assessed before complexity or review
- **THEN** the assessment is persisted against the exact proposal artifact hashes and project capability evidence
- **AND** the workflow proceeds to complexity evaluation.

#### Scenario: Apply creates an artifact required by a later task
- **GIVEN** a task creates a package manifest, build script, or other artifact during Apply
- **AND** a later task consumes that artifact
- **WHEN** executability is assessed before Apply
- **THEN** the created artifact is not treated as a precondition to enter Apply
- **AND** the later task remains pending until the artifact is produced and verified.

#### Scenario: Later-stage preview dependency does not block Apply
- **GIVEN** a task requires a candidate-SHA-matched preview before Verify or another explicitly later stage
- **AND** no such preview exists yet
- **AND** the task has an identified project-owned path for that later stage
- **WHEN** executability is assessed before Apply
- **THEN** the proposal may advance to Apply
- **AND** the preview task remains pending and is checked before entering the stage that requires it
- **AND** the system does not claim that the preview or validation is complete.

#### Scenario: Required dependency blocks the transition that needs it
- **GIVEN** a task requires a verified preview before the next transition into Verify
- **AND** the candidate-SHA-matched preview is unavailable
- **WHEN** the workflow is about to enter Verify
- **THEN** that transition is held at the existing human gate
- **AND** the gate identifies the exact task, missing preview evidence, and responsible actor
- **AND** no Verify attempt is started or consumed.

#### Scenario: Human-only evidence has no confirmed participant or available candidate
- **GIVEN** a proposed task requires physical-device testing or an observation session
- **AND** the task is assigned to a later human-validation stage
- **WHEN** executability is assessed before Apply
- **THEN** the task remains pending for that later stage and is not represented as automated Apply work
- **AND** Apply is not blocked solely because the candidate or participant is not yet available.

#### Scenario: Mandatory task has no authorized execution path
- **GIVEN** a mandatory task has no responsible actor or no authorized capability path in any planned stage
- **WHEN** task executability is assessed before proposal acceptance
- **THEN** the proposal remains unaccepted
- **AND** the gate names the task and the missing decision or capability needed to define a valid path.

#### Scenario: Missing or unverifiable current-stage evidence fails closed
- **GIVEN** an assessment omits a task or stage, names an unconfigured actor, cites an absent capability needed by the next transition, or cannot verify a dependency required before that transition
- **WHEN** the assessment is validated
- **THEN** the current transition is held with the exact task, stage, and evidence gap
- **AND** a free-text operator response alone cannot advance it.

#### Scenario: Acceptance scenarios have stage-specific task evidence
- **GIVEN** a strictly validated proposal with acceptance scenarios spanning multiple workflow stages
- **WHEN** task executability is assessed
- **THEN** each scenario maps to one or more tasks and evidence produced at the stage that satisfies it
- **AND** an unmapped scenario keeps the assessment incomplete without inventing an external dependency.

#### Scenario: Updated Request or capability evidence allows reassessment
- **GIVEN** a transition is held because a dependency required by that stage is unavailable
- **AND** the original Request or project capability evidence is updated and verified
- **WHEN** the native proposal artifacts are updated and strictly validated
- **THEN** the system re-assesses affected tasks against the new artifact and capability evidence hashes
- **AND** advances only if dependencies required by the next transition now have a confirmed path.

#### Scenario: Operator selects native Update from the feasibility gate
- **GIVEN** a proposal-feasibility gate offers an explicit option to revise the proposal through native OpenSpec Update
- **WHEN** the operator selects that exact option
- **THEN** the same Run and Change resume through the installed native OpenSpec Update workflow with the persisted blockers, structured task/scenario assessment, candidate SHA, and artifact/context hashes as corrective context
- **AND** invalid task references and missing, extra, or duplicate scenario mappings are identified for correction against the authoritative OpenSpec inventory
- **AND** the updated artifacts undergo strict CLI validation before feasibility is reassessed against their new hashes
- **AND** the operator's selection does not itself satisfy a blocker or dispatch Apply.

#### Scenario: Evidence option does not silently revise the Change
- **GIVEN** a proposal-feasibility gate offers an option to provide missing evidence
- **WHEN** the operator selects that option without new verifiable evidence
- **THEN** native OpenSpec Update is not dispatched
- **AND** the proposal remains unaccepted with the existing blocker and the evidence required to resolve it.
