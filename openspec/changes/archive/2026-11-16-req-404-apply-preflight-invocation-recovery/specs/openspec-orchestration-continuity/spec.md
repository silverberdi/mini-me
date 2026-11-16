## MODIFIED Requirements

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
