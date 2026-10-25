## Purpose
Maintain minimal durable orchestration state in PostgreSQL, enforce capacity and budget checks prior to agent invocations, preserve authentic OpenSpec questions and options in Spanish, and guarantee crash recovery and external action idempotency.

## ADDED Requirements

### Requirement: Minimal Durable State and Stage Tracking
The system SHALL persist minimal orchestration state in PostgreSQL comprising the project binding, remote issue reference, change name, current stage, resumable checkpoint, candidate commit SHAs, complexity assessment, and external action records, and SHALL NOT replicate remote tickets or maintain parallel backlog queues.

#### Scenario: Stage transitions recorded with checkpoint
- **GIVEN** an active orchestration run executing a pipeline stage
- **WHEN** an orchestration stage (Explore, Propose, Validate, Apply, Verify, Review, PR1, DocClose, PR2) completes with verifiable evidence
- **THEN** the system updates the run state atomically in PostgreSQL with the new resumable stage and candidate SHA
- **AND** records external action metadata idempotently.

### Requirement: Strict Continuity Preservation and Lock Release Authority
The system SHALL preserve the active Request identity, worktree workspace, candidate branch, and PostgreSQL state across recoverable technical errors, correction limit pauses, and capacity exhaustion waits (`WAITING_CAPACITY`), SHALL NOT abandon the active Request to select another issue, SHALL NOT delete or clean up the active worktree upon technical failure, and SHALL release the active project lock and authorize worktree cleanup ONLY upon confirmed remote issue closure following the second merge or upon an explicit, operator-authorized cancellation (`CANCELLED`).

#### Scenario: Recoverable failure preserves worktree and request binding
- **GIVEN** an active request undergoing implementation or verification
- **WHEN** an execution attempt encounters a technical error, correction limit, or capacity exhaustion
- **THEN** the system preserves the worktree files, branch, and PostgreSQL run record
- **AND** leaves the project lock active
- **AND** does NOT select the next ticket from the queue.

#### Scenario: Missing workflow capability preserves worktree and pauses for remediation
- **GIVEN** an active request requiring a specific OpenSpec workflow (e.g. Verify)
- **WHEN** the stage cannot resolve the required workflow for the configured agent in the worktree
- **THEN** the system halts fail-closed with diagnostic details
- **AND** preserves the candidate worktree and run record in PostgreSQL
- **AND** retains the project active lock without selecting another ticket.

#### Scenario: Confirmed closure releases active project lock
- **GIVEN** an active request whose documentation PR2 has been confirmed merged
- **WHEN** `GitHubAdapter.close_issue` confirms remote issue closure
- **THEN** the run status is marked terminal in PostgreSQL
- **AND** the active project lock is released
- **AND** the candidate worktrees are scheduled for safe cleanup.

#### Scenario: Explicit authorized operator cancellation releases project lock
- **GIVEN** a stalled or blocked request holding the project lock
- **WHEN** an operator explicitly submits an authorized cancellation command (`CANCELLED`)
- **THEN** the run status transitions to `CANCELLED`
- **AND** the active project lock is released
- **AND** worktrees are cleaned up safely.

### Requirement: Provider Capacity and Quota Preflight
Before dispatching any agent invocation, the system SHALL check provider health, quota availability, and budget limits using the existing capacity and budget services; if capacity is exhausted or unobservable, the system SHALL enter `WAITING_CAPACITY` and preserve the current checkpoint without burning quota or engaging unauthorized fallbacks.

#### Scenario: Invocations proceed only with confirmed capacity
- **GIVEN** an agent stage ready for dispatch
- **WHEN** capacity preflight confirms provider health, quota availability, and budget headroom
- **THEN** the agent runner launches the process in the confined worktree.

#### Scenario: Capacity exhaustion preserves checkpoint and waits
- **GIVEN** an agent stage ready for dispatch
- **WHEN** provider capacity check reports exhaustion or rate limiting
- **THEN** the run transitions to `WAITING_CAPACITY`
- **AND** records the expected reset timestamp in PostgreSQL
- **AND** preserves worktree files and current stage without advancing or dispatching.

### Requirement: Human Intervention Protocol and Option Fidelity
When human intervention is required, the system SHALL preserve the exact original prompt and options emitted by OpenSpec or the agent, SHALL present them clearly in plain Spanish distinguishing native options from agent-generated recommendations, and SHALL resume execution seamlessly upon receiving the operator's response.

#### Scenario: Verbatim options displayed to operator
- **GIVEN** OpenSpec Explore or Propose emitting explicit options during clarification
- **WHEN** mini me prepares a `HUMAN REQUIRED` operator prompt
- **THEN** it presents the exact verbatim options in Spanish
- **AND** clearly separates native OpenSpec options from agent advice
- **AND** pauses execution cleanly until human input is received.

#### Scenario: Resume preserves progress without duplicate execution
- **GIVEN** a paused run in `HUMAN REQUIRED` status
- **WHEN** the operator submits a valid response
- **THEN** mini me re-invokes the agent with the response as input context
- **AND** resumes execution directly from the paused stage without re-running completed steps.

### Requirement: Crash Recovery and External Action Idempotency
Upon process restart or recovery after unexpected failure, the system SHALL inspect remote Git and GitHub state before re-executing any action, SHALL verify existing branches, candidate commits, and open pull requests, and SHALL NOT duplicate PR creation, comments, or merges.

#### Scenario: Interrupted run resumes from last verified checkpoint
- **GIVEN** a running daemon abruptly terminated during stage execution
- **WHEN** the mini me process restarts
- **THEN** it reloads the run record from PostgreSQL
- **AND** inspects the worktree and remote branch state
- **AND** resumes execution from the exact verified stage without data loss.

#### Scenario: Existing PR detected and not duplicated
- **GIVEN** a daemon recovering at the pull request creation stage
- **WHEN** `GitHubAdapter.find_open_pull_request` detects an existing PR for the candidate branch
- **THEN** mini me binds to the existing PR number and URL
- **AND** avoids creating a duplicate PR on GitHub.
