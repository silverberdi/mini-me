# openspec-orchestration-continuity Specification

## Purpose
Maintain minimal durable orchestration state in PostgreSQL, enforce capacity and budget checks prior to agent invocations, preserve authentic OpenSpec questions and options in Spanish, and guarantee crash recovery and external action idempotency.

## Requirements

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
When human intervention is required, the system SHALL persist and expose the exact question and options for the currently blocking gate across all workflow stages (including Explore checkpoint, Propose clarification, review escalation, Apply recovery exhaustion, PR1 merge acknowledgement, and physical validation), preserving original wording emitted by OpenSpec or the agent and distinguishing native options from agent-generated recommendations. The active payload SHALL be unified in PostgreSQL across stage checkpoints, `orchestration_runs.human_gate`, and `stop_details.human_payload`, and SHALL NOT be sourced from a resolved or superseded earlier gate. For exhausted Apply recovery, the active payload SHALL capture attempt counts for the current cycle, the hard ceiling, pending task lists, candidate SHA, and test outcomes, providing a concise, actionable Spanish explanation of what stopped the workflow and what decision is needed. When the operator submits an authorized response, the system SHALL accept it idempotently, record it atomically in PostgreSQL, clear the active gate immediately, and resume execution without rejecting the response with HTTP 409 or re-surfacing resolved gates. An accepted response that authorizes continuation from an Apply exhaustion gate SHALL start exactly one new Apply recovery cycle at 0/3; prior cycle attempts and outcomes SHALL remain durably auditable and SHALL NOT be rewritten.

#### Scenario: Verbatim options displayed to operator
- **GIVEN** OpenSpec Explore or Propose emitting explicit options during clarification
- **WHEN** mini me prepares a `HUMAN REQUIRED` operator prompt
- **THEN** it presents the exact verbatim options in Spanish
- **AND** clearly separates native OpenSpec options from agent advice
- **AND** pauses execution cleanly until human input is received.

#### Scenario: Each scoped gate persists its active question and options
- **GIVEN** a Run has a prior gate payload or no gate payload
- **WHEN** Explore checkpoint, Propose clarification, review escalation, Apply recovery exhaustion, PR1 merge acknowledgement, or physical validation blocks that Run
- **THEN** the Run durably records the current gate's question and options as its active human request in PostgreSQL
- **AND** the active payload identifies the current gate and does not retain the prior gate's question or options.

#### Scenario: Explore checkpoint response accepted without 409
- **GIVEN** an active Run paused at Explore with a verified `HUMAN_REQUIRED` checkpoint
- **WHEN** the operator submits a response to the active gate endpoint
- **THEN** the system matches the Explore checkpoint as the current human gate
- **AND** accepts the response without returning HTTP 409 Conflict
- **AND** persists the operator input atomically and transitions the gate to resolved.

#### Scenario: Resume preserves progress without duplicate execution
- **GIVEN** a paused run in `HUMAN REQUIRED` status
- **WHEN** the operator submits a valid response
- **THEN** mini me re-invokes the agent with the response as input context
- **AND** resumes execution directly from the paused stage without re-running completed steps.

#### Scenario: Exhausted proposal-review gate explains its finding and decision
- **GIVEN** independent proposal review reaches its attempt limit with structured findings
- **WHEN** the proposal-review escalation becomes the active human gate
- **THEN** the payload retains each available severity, location, affected requirement, and expected correction
- **AND** Trabajo actual presents a short Spanish explanation of what was found, where it applies, why it matters, and why the workflow stopped
- **AND** the operator sees native options when supplied, otherwise clearly labeled safe system-generated alternatives with consequences or a free-text response when no safe alternatives can be offered.

#### Scenario: Exhausted Apply recovery gate explains diagnostic context
- **GIVEN** Apply recovery halts due to reaching the attempt ceiling or lack of progress
- **WHEN** Apply escalation becomes the active human gate
- **THEN** the active payload retains current-cycle attempt count vs. ceiling, pending tasks, candidate SHA, and test results
- **AND** Trabajo actual presents an actionable Spanish explanation of why recovery stopped, what tasks remain, and what decision is required
- **AND** if execution logs are unavailable, explicitly indicates their absence instead of presenting a generic unformatted string.

#### Scenario: Accepted Apply response resets one cycle without losing history
- **GIVEN** an active Run is stopped at an exhausted Apply recovery gate
- **WHEN** the operator submits an accepted response that authorizes continuation
- **THEN** the resolved gate is cleared and exactly one new Apply recovery cycle starts at 0/3
- **AND** the current attempt count is zero before the first new Apply invocation
- **AND** historical attempts and their results remain auditable
- **AND** the same Run, candidate, branch, and worktree continue.

#### Scenario: Replayed Apply response does not create another cycle
- **GIVEN** an accepted response has already started the next Apply recovery cycle for a gate
- **WHEN** the same idempotent response is submitted again
- **THEN** the prior response result is returned
- **AND** no additional cycle or Apply invocation is created.

#### Scenario: Proposal-review response does not approve or bypass review
- **GIVEN** an operator responds to an exhausted proposal-review gate
- **WHEN** the existing response workflow accepts the response
- **THEN** the response is recorded as operator input
- **AND** it does not itself mark the proposal review approved or skip the required independent review.

#### Scenario: Resolved gate never resurfaces after stage progression or reload
- **GIVEN** an operator has responded to an active human gate and the stage has transitioned
- **WHEN** the operator reloads the page or the coordinator continues to a subsequent stage
- **THEN** the resolved gate is permanently inactive in the API projection
- **AND** does not reappear as a zombie prompt or generic intervention.

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

### Requirement: Durable Stage Invocation Lifecycle
The system SHALL durably record each coordinator stage invocation with a unique attempt identity, run identity, stage, candidate identity, start time, finish time, duration, and the native workflow's observed result. Candidate identity SHALL use the strongest observed identity available at dispatch (including the run's worktree/branch identity before a candidate SHA exists) and SHALL be bound to the candidate SHA when available. The coordinator SHALL claim the invocation before dispatch and SHALL NOT treat a human gate as an active invocation. It SHALL preserve a native workflow handoff as received and SHALL NOT synthesize workflow artifacts, outcomes, questions, or options.

#### Scenario: Invocation outcome is observable
- **WHEN** a stage invocation finishes successfully, fails, or returns `HUMAN_REQUIRED`
- **THEN** durable evidence links its start and finish, elapsed duration, observed native result/handoff, run, stage, candidate identity, and attempt identity
- **AND** a `HUMAN_REQUIRED` outcome closes the invocation while preserving the pending gate on the same run
- **AND** any native question and options are retained as received, without coordinator-generated substitutes

#### Scenario: Active invocation prevents scheduler redispatch
- **GIVEN** a stage invocation is active for a run and candidate
- **WHEN** another worker or scheduler re-enters that run and stage
- **THEN** it observes the active invocation and does not dispatch the native workflow again

#### Scenario: Human gate blocks dispatch until accepted response
- **GIVEN** a stage invocation ended with `HUMAN_REQUIRED` and its gate remains pending
- **WHEN** scheduler recovery or another worker re-enters without an accepted response
- **THEN** no new invocation starts and the same run, worktree, stage, candidate, and gate remain intact

#### Scenario: Accepted response resumes once
- **GIVEN** a pending human gate for a run and candidate
- **WHEN** the operator's response is accepted and the same response is submitted again
- **THEN** the accepted response is durably identified for that gate and only one subsequent stage invocation is dispatched
- **AND** the workflow continues on the same run, worktree, stage, and candidate
- **AND** the accepted response is supplied as context to the same native workflow invocation, without changing that workflow's semantics

### Requirement: Bounded Recovery of Abandoned Stage Invocation
The system SHALL detect an invocation whose worker lease expired and record it as abandoned/interrupted with its attempt identity and last observed candidate identity. A lease timeout alone SHALL NOT establish that the worker or workflow process terminated. The system MAY re-invoke the same native workflow at most once for the same run, stage, worktree, and candidate only when durable process identity proves that the prior coordinator process is gone, the spawned workflow process group is absent, the candidate identity is unchanged, and the prior claim is fenced. It SHALL NOT inspect OpenSpec artifacts to infer workflow progress or choose a substitute next action. If process identity is missing, unsupported, live, or ambiguous, or the bounded retry is also interrupted, the system SHALL stop for operator intervention without inferring success.

#### Scenario: Expired coordinator and workflow process are recovered once
- **GIVEN** an invocation has no completion evidence and its worker lease has expired
- **WHEN** durable process identity proves the prior coordinator process has exited, the spawned workflow process group is absent, the run/worktree/stage/candidate identity still matches, and recovery fences the prior claim
- **THEN** it records the prior attempt as abandoned and allows at most one automatic retry for that interrupted invocation
- **AND** the retry receives a distinct attempt identity linked to the abandoned attempt
- **AND** the retry invokes the existing native workflow and leaves workflow-state interpretation to OpenSpec

#### Scenario: Repeated or ambiguous interruption fails closed
- **GIVEN** the bounded automatic recovery was already used or candidate/worktree identity cannot be verified
- **WHEN** recovery evaluates the invocation
- **THEN** it records the ambiguity and stops for an operator decision without dispatching another native workflow

#### Scenario: Expired lease with live or unobservable process fails closed
- **GIVEN** an invocation lease expired but the prior coordinator process is live, the workflow process group is present, or either process identity cannot be verified
- **WHEN** recovery evaluates the invocation
- **THEN** it stops for operator intervention without invoking the native workflow again

#### Scenario: Process identity was not persisted before interruption
- **GIVEN** an invocation has a start record but no durable identity for its spawned workflow process
- **WHEN** recovery evaluates the expired invocation
- **THEN** it records the attempt as ambiguous and stops for operator intervention without redispatch

### Requirement: Authorized Apply-gate decisions update the active Change before continuation
When an operator's accepted response to an Apply human gate explicitly changes the disposition of an existing Change criterion, the system SHALL preserve the original response and gate identity and SHALL coordinate the configured thinking agent to apply that decision through the native OpenSpec `update` workflow before dispatching another Apply invocation. mini me SHALL NOT author or directly edit the semantic OpenSpec artifacts. The update and its validation result SHALL be durably associated with the same Run, Change, branch, and worktree. A response that does not authorize a material criterion change SHALL continue through the existing gate-resolution behavior. The validated Update checkpoint SHALL also identify the task dispositions it changed and the candidate identity against which those changes were validated, so Apply recovery can reconcile only those dispositions without weakening unrelated regression checks. A later continuation-only Apply response SHALL reuse this validated checkpoint and SHALL NOT dispatch a no-op Update that overwrites it.

#### Scenario: Explicit deferral is applied through native OpenSpec Update
- **GIVEN** a Run is blocked at an Apply gate and the operator explicitly directs that an existing validation criterion be deferred or reclassified
- **WHEN** the accepted gate response is processed
- **THEN** the configured thinking agent receives the original decision and current Change context through the native OpenSpec `update` workflow
- **AND** no Apply invocation is dispatched until the updated artifacts pass strict OpenSpec validation
- **AND** the response, Update invocation, result, and validation evidence are linked to the same Run, Change, branch, and worktree.

#### Scenario: Ambiguous or unauthorized disposition remains at the human gate
- **GIVEN** an operator response could materially change a criterion but is ambiguous, conflicts with the rector contract, or does not authorize the needed change
- **WHEN** the system evaluates the response
- **THEN** it asks one current, concrete human question with the valid options and their effects
- **AND** it dispatches neither OpenSpec Update nor Apply until the decision is resolved
- **AND** it does not consume an Apply attempt for this unresolved decision.

#### Scenario: Interrupted or repeated response does not duplicate Update or Apply
- **GIVEN** the operator response has a durable action identity and its OpenSpec Update invocation may have started or completed
- **WHEN** the same response is replayed or the coordinator recovers after interruption
- **THEN** the system observes the existing action, invocation, and updated-artifact validation before deciding the next step
- **AND** it does not apply the same decision twice or create duplicate Apply invocations
- **AND** it resumes from the validated checkpoint while preserving prior evidence.

#### Scenario: Native Update is unavailable or validation fails
- **GIVEN** the configured thinking agent cannot resolve the native OpenSpec Update workflow or the updated Change fails strict validation
- **WHEN** the system processes an authorized disposition
- **THEN** it preserves the Run, worktree, response, and invocation evidence
- **AND** reports the concrete missing capability or validation error and the next valid operator choices
- **AND** does not fall through to a generic Apply retry.

#### Scenario: Validated Update binds reclassified tasks to the same candidate
- **GIVEN** a native OpenSpec Update completes and passes strict validation
- **WHEN** the coordinator records the Update checkpoint
- **THEN** it records the explicit task disposition changes and the Run, Change, branch, worktree, and candidate identity
- **AND** Apply recovery can use that checkpoint only for the changed task dispositions
- **AND** replaying the same operator action does not broaden the set of reconciled tasks.

#### Scenario: Continuation-only Apply response preserves the validated checkpoint
- **GIVEN** a validated Update checkpoint from an earlier accepted operator action remains bound to the current Run, Change, branch, worktree, and candidate
- **AND** the current Apply gate response authorizes continuation without changing criteria
- **WHEN** the coordinator processes the response
- **THEN** it reuses the existing validated checkpoint and retains its original operator-action identity
- **AND** it dispatches no no-op Update and does not replace the checkpoint with an empty disposition set.
