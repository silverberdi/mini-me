## MODIFIED Requirements

### Requirement: Minimal Durable State and Stage Tracking

The system SHALL persist minimal orchestration state in PostgreSQL comprising the project binding, remote issue reference, change name, current stage, resumable checkpoint, candidate commit SHAs, complexity assessment, and external action records, and SHALL NOT replicate remote tickets or maintain parallel backlog queues. Checkpoints that claim agent results SHALL be bound to the exact Run, stage, attempt, provider/profile, native workflow identity, normalized source/context and complete verified authoritative response; a syntactically valid digest alone SHALL NOT count as source evidence.

#### Scenario: Stage transitions recorded with checkpoint

- **GIVEN** an active orchestration Run executing a pipeline stage
- **WHEN** an orchestration stage (Explore, Propose, Validate, Apply, Verify, Review, PR1, DocClose, PR2) completes with verifiable evidence
- **THEN** the system SHALL update the Run state atomically in PostgreSQL with the new resumable stage and candidate SHA
- **AND** it SHALL record external action metadata idempotently

#### Scenario: Checkpoint hash not bound to origin

- **GIVEN** a checkpoint contains a plausible 64-character response SHA but lacks matching attempt/workflow/source evidence
- **WHEN** a restarted Run evaluates checkpoint reuse
- **THEN** it SHALL refuse silent reuse and stop without dispatching another model invocation automatically

### Requirement: Human Intervention Protocol and Option Fidelity

When human intervention is required, the system SHALL preserve the exact original prompt and options emitted by OpenSpec or the agent, SHALL present them clearly in plain Spanish distinguishing native options from agent-generated recommendations, and SHALL resume execution seamlessly upon receiving the operator's authorized response. The request and decision SHALL be durably bound to the exact Run/stage/gate; diagnostic mentions of `HUMAN REQUIRED` SHALL NOT create a human decision and technical transport faults SHALL NOT be represented as human business ambiguity.

#### Scenario: Verbatim options displayed to operator

- **GIVEN** OpenSpec Explore or Propose emits explicit options during clarification
- **WHEN** mini me prepares a `HUMAN REQUIRED` operator prompt
- **THEN** it SHALL present the exact verbatim options in Spanish
- **AND** it SHALL clearly separate native OpenSpec options from agent advice
- **AND** it SHALL pause execution cleanly until human input is received

#### Scenario: Resume preserves progress without duplicate execution

- **GIVEN** a Run paused in `HUMAN REQUIRED` status
- **WHEN** an operator submits a valid authorized response
- **THEN** mini me SHALL re-invoke the agent with that response as the new context when required, preserving completed work and the original attempt history
- **AND** it SHALL resume only from the previously verified stage without re-running completed steps

#### Scenario: Diagnostic mentions historical gate after clarification

- **GIVEN** a current final verdict of `READY TO PROPOSE` after operator clarification and historical mentions of `HUMAN REQUIRED` in diagnostics
- **WHEN** the gate is reconciled
- **THEN** the system SHALL NOT duplicate a resolved HUMAN_REQUIRED question or alter the authorized clarification

### Requirement: Crash Recovery and External Action Idempotency

Upon process restart or recovery after unexpected failure, the system SHALL inspect durable Run/attempt records, verified native final-response evidence, authorized workspace and remote Git/GitHub state before re-executing any action. It SHALL verify existing branches, candidate commits, and open pull requests; SHALL NOT duplicate agent inferences, PR creation, comments, merges or issue closure; and SHALL NOT synthesize checkpoints from abbreviated logs or replay a dispatched unknown attempt. A completed authoritative stage result SHALL be reusable only when its identity and evidence are current and complete.

#### Scenario: Interrupted run resumes from last verified checkpoint

- **GIVEN** a running daemon abruptly terminates during stage execution
- **WHEN** the mini me process restarts
- **THEN** it SHALL reload the Run record from PostgreSQL, inspect worktree and remote branch state, and resume execution from the exact verified stage without data loss

#### Scenario: Existing PR detected and not duplicated

- **GIVEN** a daemon recovers at the pull request creation stage
- **WHEN** `GitHubAdapter.find_open_pull_request` detects an existing PR for the candidate branch
- **THEN** mini me SHALL bind to that PR number and URL and avoid a duplicate GitHub PR

#### Scenario: Duplicate authenticated continuation does not duplicate inference

- **GIVEN** two authenticated API/CLI continuations target the same active Run and gate
- **WHEN** both attempt to proceed concurrently
- **THEN** only one SHALL hold the execution authority for that stage
- **AND** the other SHALL observe the same checkpoint or safe wait without dispatching another agent

#### Scenario: Completed native final response is recoverable

- **GIVEN** an attempt has a complete validated final response and verified matching Run/context/workflow/provider metadata
- **WHEN** the Run resumes after an interruption
- **THEN** it SHALL reuse the persisted accepted stage verdict without replaying that inference

#### Scenario: Previous Explore has no authentic checkpoint

- **GIVEN** the F5 Run predates final-response checkpoint persistence or its diagnostic stream was truncated
- **WHEN** the operator requests recovery
- **THEN** the system SHALL preserve original attempt history and distinguish evidence actually recoverable from a mere textual report
- **AND** it SHALL require explicit recovery authority before any new model invocation, not backfill a fabricated result by manual SQL