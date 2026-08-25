## MODIFIED Requirements

### Requirement: Single-change admission
The system SHALL start an orchestration run only for one explicitly selected project/change pair whose durable repository binding and existing readiness authority both validate as READY, and SHALL verify all autonomous execution readiness prerequisites before admitting the run.

#### Scenario: READY change is admitted
- **WHEN** the operator starts orchestration for a durably bound READY project/change pair
- **AND** project registration is active, durable binding exists, remote Issue verification passes, physical schema preflight passes, deterministic checks are non-empty, primary capacity is available, and GitHub App authority is healthy
- **THEN** the system creates one immutable `orchestration_run_id`, records the bound project/change/base identity, and enters the first persisted orchestration stage.

#### Scenario: Ineligible change is refused
- **WHEN** the selected change is not READY, has ambiguous/missing binding, or fails repository/workspace/schema preflight
- **THEN** no executable orchestration run is created and the refusal contains a structured reason.

#### Scenario: Duplicate active run is refused
- **WHEN** an active orchestration already exists for the same project/change pair
- **THEN** the new start request fails closed and returns the existing run identity without starting another job, worktree, branch, or provider action.

#### Scenario: Historical run does not block a later run
- **WHEN** prior orchestration runs for the same project/change are terminal and no non-terminal run exists
- **THEN** a new explicitly admitted run may be created while historical run records remain queryable.

### Requirement: Durable deterministic orchestration lifecycle
The system SHALL persist a finite, ordered orchestration stage and checkpoint for every run, SHALL advance it only after the required authoritative evidence for that stage is committed, and SHALL use deterministic logical transition keys (`{run_id}:RESUME:{resumable_stage}:{current_generation}`) for resume operations and stage events to prevent duplicate event evidence upon repeated reconciliation or restart.

#### Scenario: Successful path reaches the human gate
- **WHEN** implementation/continuation completes, checks pass, the candidate is frozen, complementary review is authoritative, the final full DeepSeek Direct audit passes, and repository identity is valid
- **THEN** the system advances the operational stage to `PR_PREPARED` only after push/PR reconciliation proves the remote PR head equals the exact audited candidate, then records `READY_FOR_HUMAN_MERGE` as the separate human gate and stops.

#### Scenario: Stage advancement is not agent-controlled
- **WHEN** an implementer, reviewer, or auditor claims that a stage is complete without the required deterministic evidence
- **THEN** the orchestration stage does not advance and the claim is recorded only as attempt/review/audit evidence.

#### Scenario: Temporary capacity blocks progress
- **WHEN** an existing pipeline authority reports a safe temporary capacity wait
- **THEN** the operational job remains or becomes `WAITING_CAPACITY`, the orchestration checkpoint records the resumable stage and handoff, and the run stops without becoming `NEEDS_HUMAN` solely for capacity.

#### Scenario: Temporary external dependency blocks progress
- **WHEN** a transient non-provider dependency such as GitHub is unavailable, a transient provider error occurs, or an external action result cannot yet be observed
- **THEN** the orchestration run stops with `WAITING_EXTERNAL`, preserves its resumable checkpoint, and does not change the job to `WAITING_CAPACITY` or `NEEDS_HUMAN` solely for the transient outage.

#### Scenario: Unresolvable invariant blocks progress
- **WHEN** binding, worktree identity, candidate identity, evidence authority, provider/model independence, or external-action outcome cannot be proven uniquely
- **THEN** the run records a structured stop reason and enters `NEEDS_HUMAN` unless the existing capacity authority proves `WAITING_CAPACITY` or the external dependency is transiently unobservable and qualifies for `WAITING_EXTERNAL`, without speculative continuation.

#### Scenario: Deterministic resume event idempotency
- **WHEN** an orchestration run is resumed repeatedly across daemon restarts or recovery cycles without advancing stages
- **THEN** the system SHALL record resume transitions using logical transition keys bound to the run ID, stage, and generation (`{run_id}:RESUME:{resumable_stage}:{current_generation}`), preventing duplicate logical stage events.
