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
Before dispatching any agent invocation, the system SHALL check provider health, quota availability, and budget limits using the existing capacity and budget services. A missing provider record, a status other than `AVAILABLE`, or an active failure/exhaustion signal SHALL be treated as unavailable or unobservable; the system SHALL then enter `WAITING_CAPACITY` and preserve the current checkpoint without burning quota or engaging unauthorized fallbacks. During normal `SchedulerMode.RUN`, an Apply's configured primary SHALL be eligible when its persisted `provider_health` status is `AVAILABLE` and no active provider failure or exhaustion is recorded, regardless of the age of `last_success_at`. The strict `last_success_at <= 60s` condition SHALL apply exclusively to the existing in-flight peer-outage recovery path in `SchedulerMode.DRAIN`; it SHALL NOT block normal Apply dispatch after idle time. No periodic or inference-consuming probe is required to make a normally available primary eligible.

#### Scenario: Invocations proceed only with confirmed capacity
- **GIVEN** an agent stage ready for dispatch
- **WHEN** capacity preflight confirms provider health, quota availability, and budget headroom under the applicable scheduler-mode rule
- **THEN** the agent runner launches the process in the confined worktree.

#### Scenario: Normal RUN dispatches an available primary after idle time
- **GIVEN** an active Run is ready to invoke Apply in `SchedulerMode.RUN`
- **AND** the configured primary's persisted health status is `AVAILABLE`, no active failure or exhaustion is recorded, and `last_success_at` is older than 60 seconds
- **WHEN** capacity preflight evaluates the Apply
- **THEN** Apply dispatches to the configured primary without requiring a recent successful execution or starting a periodic/inference-consuming probe.

#### Scenario: Active failure or exhaustion blocks normal RUN dispatch
- **GIVEN** an active Run is ready to invoke Apply in `SchedulerMode.RUN`
- **AND** the configured primary has an active failure or exhaustion recorded
- **WHEN** capacity preflight evaluates the Apply
- **THEN** the system does not dispatch that primary and preserves the checkpoint under the existing capacity and authorized-fallback rules.

#### Scenario: Peer-outage recovery retains the strict recent-success condition
- **GIVEN** an in-flight Apply is recovering in `SchedulerMode.DRAIN` because a peer provider is unavailable
- **AND** the selected primary has no successful execution within the previous 60 seconds
- **WHEN** the peer-outage recovery rule evaluates that Apply
- **THEN** that special recovery path does not qualify the primary through the recent-success exception and continues under existing capacity and fallback authorization rules.

#### Scenario: Capacity exhaustion preserves checkpoint and waits
- **GIVEN** an agent stage ready for dispatch
- **WHEN** provider capacity check reports exhaustion or rate limiting
- **THEN** the run transitions to `WAITING_CAPACITY`
- **AND** records the expected reset timestamp in PostgreSQL when known
- **AND** preserves worktree files and current stage without advancing or dispatching.

### Requirement: Human Intervention Protocol and Option Fidelity
When human intervention is required, the system SHALL persist and expose the exact original question and options for the currently blocking gate across all workflow stages (including Explore checkpoint, Propose clarification, review escalation, Apply recovery exhaustion, PR1 merge acknowledgement, and physical validation), preserving original wording emitted by OpenSpec or the agent and distinguishing native options from agent-generated recommendations. If the original question or an option is not in Spanish, the operator-facing gate SHALL also provide a faithful Spanish rendering alongside the exact original text; the original SHALL remain available in the gate view and durable payload as the source of truth. The system SHALL NOT invent, remove, reorder, or change the meaning or authorization effect of native options. Selecting a rendered Spanish label SHALL submit the stable original option response value, never the translated display text. The active payload SHALL be unified in PostgreSQL across stage checkpoints, `orchestration_runs.human_gate`, and `stop_details.human_payload`, and SHALL NOT be sourced from a resolved or superseded earlier gate. For exhausted Apply recovery, the active payload SHALL capture attempt counts for the current cycle, the hard ceiling, pending task lists, candidate SHA, and test outcomes, providing a concise, actionable Spanish explanation of what stopped the workflow and what decision is needed. When the operator submits an authorized response, the system SHALL accept it idempotently, record it atomically in PostgreSQL, clear the active gate immediately, and resume execution without rejecting the response with HTTP 409 or re-surfacing resolved gates. An accepted response that authorizes continuation from an Apply exhaustion gate SHALL start exactly one new Apply recovery cycle at 0/3; prior cycle attempts and outcomes SHALL remain durably auditable and SHALL NOT be rewritten.

#### Scenario: Verbatim options displayed to operator
- **GIVEN** OpenSpec Explore or Propose emits explicit options during clarification, in Spanish or another language
- **WHEN** mini me prepares a `HUMAN REQUIRED` operator prompt
- **THEN** it presents each exact native option and, when needed, a faithful Spanish rendering alongside it
- **AND** clearly separates native OpenSpec options from agent advice
- **AND** pauses execution cleanly until human input is received.

#### Scenario: Each scoped gate persists its active question and options
- **GIVEN** a Run has a prior gate payload or no gate payload
- **WHEN** Explore checkpoint, Propose clarification, review escalation, Apply recovery exhaustion, PR1 merge acknowledgement, or physical validation blocks that Run
- **THEN** the Run durably records the current gate's original question and options, Spanish presentation, and option source as its active human request in PostgreSQL
- **AND** the active payload identifies the current gate and does not retain the prior gate's question or options.

#### Scenario: Spanish display selection submits the original option value
- **GIVEN** an active gate has an original native option and its Spanish rendering
- **WHEN** the operator selects the Spanish rendering
- **THEN** the submitted response is the stable original option response value
- **AND** the translated text is not treated as authorization or as a replacement for that value.

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
The system SHALL detect an invocation whose worker lease expired and record it as abandoned/interrupted with its attempt identity and last observed candidate identity. A lease timeout alone SHALL NOT establish that the worker or workflow process terminated. The system MAY re-invoke the same native workflow at most once for the same run, stage, worktree, and candidate only when durable evidence proves that either (a) a previously started coordinator process is gone and its spawned workflow process group is absent, or (b) the invocation failed before a workflow process started and the candidate fingerprint is unchanged. In both cases the prior claim SHALL be fenced. It SHALL NOT inspect OpenSpec artifacts to infer workflow progress or choose a substitute next action. If process identity or candidate evidence is missing, unsupported, changed, live, or ambiguous, or the bounded retry is also interrupted, the system SHALL stop for operator intervention without inferring success.

#### Scenario: Expired coordinator and workflow process are recovered once
- **GIVEN** an invocation has no completion evidence and its worker lease has expired
- **WHEN** durable process identity proves the prior coordinator has exited, its spawned workflow process group is absent, the run/worktree/stage/candidate identity still matches, and recovery fences the prior claim
- **THEN** it records the prior attempt as abandoned and allows at most one automatic retry for that interrupted invocation
- **AND** the retry receives a distinct attempt identity linked to the abandoned attempt
- **AND** the retry invokes the existing native workflow and leaves workflow-state interpretation to OpenSpec

#### Scenario: Pre-process failure is recorded and retried once on the same candidate
- **GIVEN** a stage invocation has started but fails during preflight before any workflow process-start event is recorded
- **AND** evidence proves the coordinator invocation has ended and the candidate fingerprint is unchanged
- **WHEN** the coordinator records the terminal failure and releases/fences the claim
- **THEN** it records the failure as a distinct durable outcome and allows at most one automatic retry of the same stage on the same run, worktree, and candidate
- **AND** the retry uses a new attempt identity linked to the failed pre-process attempt
- **AND** a repeated pre-process failure pauses safely instead of retrying indefinitely.

#### Scenario: Repeated or ambiguous interruption fails closed
- **GIVEN** the bounded automatic recovery was already used or candidate/worktree identity cannot be verified
- **WHEN** recovery evaluates the invocation
- **THEN** it records the ambiguity and stops for operator intervention without dispatching another native workflow.

#### Scenario: Expired lease with live or unobservable process fails closed
- **GIVEN** an invocation lease expired but the prior coordinator process is live, the workflow process group is present, or either process identity cannot be verified
- **WHEN** recovery evaluates the invocation
- **THEN** it stops for operator intervention without invoking the native workflow again.

#### Scenario: Process identity was not persisted before interruption
- **GIVEN** an invocation has a start record but no durable identity for its spawned workflow process
- **WHEN** recovery evaluates the expired invocation
- **THEN** it records the attempt as ambiguous and stops for operator intervention without redispatch.

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

### Requirement: Human-authorized rebaseline recovers a lost Apply checkpoint
For a lost validated Apply disposition checkpoint whose evidence proves a single unchanged candidate, the system SHALL offer an explicit, single-use operator authorization to treat the current strictly validated Change task dispositions as a new recovery baseline. It SHALL record the authorization and baseline durably and atomically while retaining prior snapshots, decisions, and invocation results as immutable history. After rechecking candidate identity and confirming no stage invocation is active, it SHALL dispatch at most one native Apply continuation for the same Run, Change, branch, worktree, generation, and candidate SHA. Replaying the same action SHALL NOT duplicate the baseline or Apply dispatch. If recovery is ambiguous or unsafe, the current human gate SHALL remain and SHALL offer preserving or cancelling the Run through existing authorized behavior.

#### Scenario: Operator authorizes a safe rebaseline
- **GIVEN** the human gate presents consistent evidence for the same Run, Change, branch, worktree, generation, and candidate SHA
- **AND** no stage invocation is active
- **WHEN** the operator explicitly authorizes using the current Change state as the recovery baseline
- **THEN** the system atomically records the authorization and baseline without deleting or rewriting prior snapshots or invocation history
- **AND** dispatches exactly one Apply continuation using that same candidate identity
- **AND** a replay of the authorization observes the persisted transition and does not dispatch a second Apply.

#### Scenario: Recovery is rejected when identity or invocation safety is uncertain
- **GIVEN** the candidate identity differs from the recorded evidence, a stage invocation is active, or the evidence cannot establish the lost-checkpoint sequence
- **WHEN** the operator attempts rebaseline or the coordinator evaluates recovery
- **THEN** the system keeps the human gate active and explains the mismatched or missing evidence
- **AND** creates no baseline and dispatches no Apply
- **AND** allows the operator to preserve or cancel the Run using the existing authorized cancellation path.

#### Scenario: Rebaseline does not certify pending validation
- **GIVEN** the current Change contains pending or deferred tasks and any published-version evidence has an unknown or non-matching SHA
- **WHEN** the operator authorizes rebaseline
- **THEN** the baseline retains those tasks as pending or deferred
- **AND** no task is marked complete and no candidate-specific validation is claimed from that published evidence.

### Requirement: Scheduler is the sole DOC_CLOSING workflow dispatcher after a gate response
When an operator response makes a Run eligible to continue at `DOC_CLOSING`, the API SHALL persist the response and eligible transition through the existing durable, idempotent action path, but SHALL NOT launch the native DOC_CLOSING workflow. The API SHALL return its acceptance without waiting for the Scheduler or workflow process. After that acceptance, the PWA SHALL immediately show that the response was received and identify the pending stage; it SHALL update the displayed stage from observed Run/Scheduler state rather than implying that an agent has already started. The Scheduler SHALL be the sole authority that dispatches the workflow, and SHALL acquire the existing durable stage-invocation claim before dispatch. Concurrent or repeated API and Scheduler activity SHALL produce at most one native invocation for the same Run, stage, and candidate.

#### Scenario: Accepted DOC_CLOSING gate response awaits Scheduler dispatch
- **GIVEN** a Run is paused at a current `DOC_CLOSING` human gate
- **WHEN** the API accepts and durably records the operator's response
- **THEN** it returns `ACCEPTED` for the same Run and stage without waiting for or launching a workflow process
- **AND** the PWA immediately shows that the response was received and that `DOC_CLOSING` is pending, without claiming that the native workflow is already running
- **AND** the Scheduler later claims and dispatches the native workflow once
- **AND** the response remains idempotent if submitted again.

#### Scenario: API rejects the response
- **GIVEN** a gate response is rejected or cannot be durably accepted
- **WHEN** the API returns an error
- **THEN** the PWA shows the failure and retains the unresolved gate for correction
- **AND** it does not show a successful acceptance or clear the gate optimistically.

#### Scenario: Concurrent scheduler workers cannot duplicate DOC_CLOSING
- **GIVEN** multiple Scheduler workers observe the same eligible Run and candidate
- **WHEN** they attempt to dispatch `DOC_CLOSING`
- **THEN** only the worker holding the durable stage-invocation claim may launch the native workflow
- **AND** the other workers do not launch a second process.

### Requirement: Human gates explain affected evidence and the consequences of available actions
Every human-gate payload SHALL identify the condition that stopped the Run and the affected requirement, task, or other relevant evidence when applicable. When the gate is caused by changed proposal/task content, the payload SHALL include a readable before/after diff for the affected items. The payload fields `diff`, `affected_items`, and `option_explanations` SHALL be optional; existing and historical payloads without them SHALL remain valid. Every presented action option SHALL explain the concrete action and its consequence for the Run when an explanation is available. The system SHALL preserve native question/option values and their authorization meaning, distinguish native options from system-generated explanations, and SHALL NOT invent a diff or evidence that it cannot observe. When no artifact diff applies or one cannot be observed, the payload SHALL state that fact and include the available evidence or diagnostic instead of implying a diff exists.

#### Scenario: Drift gate identifies the changed tasks and shows their diff
- **GIVEN** a feasibility gate is raised because one or more OpenSpec task descriptions or scenarios changed after assessment
- **WHEN** the active gate payload is created
- **THEN** it identifies each affected task or scenario and presents the observed before/after diff
- **AND** its available options explain the action and operational consequence of each choice
- **AND** the exact native option response values and their authorization effects remain unchanged.

#### Scenario: Existing gate payload omits optional evidence fields
- **GIVEN** a current or historical gate payload has no `diff`, `affected_items`, or `option_explanations` field, or a field is null or empty
- **WHEN** the PWA renders the gate
- **THEN** the gate remains visible and usable without a null error
- **AND** existing question, options, and response behavior remain unchanged.

#### Scenario: Gate has no artifact diff or the diff is unavailable
- **GIVEN** a human gate is caused by a condition without changed proposal/task content, or its source diff cannot be observed
- **WHEN** the active gate payload is created
- **THEN** it identifies the actual blocking condition and relevant available evidence
- **AND** it explicitly says that no artifact diff applies or that the diff is unavailable
- **AND** it does not synthesize affected content or claim the gate is resolved.

#### Scenario: Operator selects an explained native option
- **GIVEN** a human gate presents native options with Spanish action/consequence explanations
- **WHEN** the operator selects an option
- **THEN** the system submits the original stable option response value
- **AND** the selected action has the same authorization and transition effect as the native option.
