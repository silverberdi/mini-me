## ADDED Requirements

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
