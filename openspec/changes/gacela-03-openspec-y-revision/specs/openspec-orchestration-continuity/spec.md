## Purpose
Maintain minimal durable orchestration state in PostgreSQL, enforce capacity and budget checks prior to agent invocations, preserve authentic OpenSpec questions and options in Spanish, and guarantee crash recovery and external action idempotency.

## ADDED Requirements

### Requirement: Minimal Durable State and Stage Tracking
The system SHALL persist minimal orchestration state in PostgreSQL comprising the project binding, remote issue reference, change name, current stage, resumable checkpoint, candidate commit SHAs, complexity assessment, and external action records, and SHALL NOT replicate remote tickets or maintain parallel backlog queues.

#### Scenario: Stage transitions recorded with checkpoint
- **WHEN** an orchestration stage (Explore, Propose, Validate, Apply, Verify, Review, PR1, DocClose, PR2) completes
- **THEN** the system updates the run state atomically in PostgreSQL with the new resumable stage and candidate SHA.

#### Scenario: Clean completion frees project active lock
- **WHEN** the full cycle terminates (upon remote issue closure or terminal failure)
- **THEN** the run status is marked terminal and the active project lock is released.

### Requirement: Provider Capacity and Quota Preflight
Before dispatching any agent invocation, the system SHALL check provider health, quota availability, and budget limits using the existing capacity and budget services; if capacity is exhausted or unobservable, the system SHALL enter `WAITING_CAPACITY` and preserve the current checkpoint without burning quota or engaging unauthorized fallbacks.

#### Scenario: Invocations proceed only with confirmed capacity
- **WHEN** capacity preflight verifies active provider health and budget headroom
- **THEN** the agent process is launched in the confined worktree.

#### Scenario: Capacity exhaustion preserves checkpoint and waits
- **WHEN** provider capacity is exhausted or rate-limited
- **THEN** the run transitions to `WAITING_CAPACITY`, records the expected reset time, and waits without losing worktree state or advancing stages.

### Requirement: Human Intervention Protocol and Option Fidelity
When human intervention is required, the system SHALL preserve the exact original prompt and options emitted by OpenSpec or the agent, SHALL present them clearly in plain Spanish distinguishing native options from agent-generated recommendations, and SHALL resume execution seamlessly upon receiving the operator's response.

#### Scenario: Verbatim options displayed to operator
- **WHEN** OpenSpec Explore or Propose emits explicit options during clarification
- **THEN** mini me presents those exact options in the intervention payload without omitting or inventing alternatives.

#### Scenario: Resume preserves progress without duplicate execution
- **WHEN** the operator submits a response to a `HUMAN REQUIRED` prompt
- **THEN** the agent is re-invoked with the provided response and resumes directly from the paused operation.

### Requirement: Crash Recovery and External Action Idempotency
Upon process restart or recovery after unexpected failure, the system SHALL inspect remote Git and GitHub state before re-executing any action, SHALL verify existing branches, candidate commits, and open pull requests, and SHALL NOT duplicate PR creation, comments, or merges.

#### Scenario: Interrupted run resumes from last verified checkpoint
- **WHEN** the mini me daemon restarts while an orchestration run is active
- **THEN** the system reloads the run from PostgreSQL, inspects the associated worktree and remote branch, and resumes from the exact resumable stage.

#### Scenario: Existing PR detected and not duplicated
- **WHEN** a run resumes at the PR creation stage and a PR already exists for the request branch
- **THEN** the system reuses the existing PR number and details rather than opening a duplicate PR.
