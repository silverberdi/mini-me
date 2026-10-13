## MODIFIED Requirements

### Requirement: Durable deterministic orchestration lifecycle
The system SHALL persist a finite, ordered orchestration stage and checkpoint for every run, SHALL advance it only after the required authoritative evidence for that stage is committed, and SHALL use deterministic logical transition keys (`{run_id}:RESUME:{resumable_stage}:{current_generation}`) for resume operations and stage events to prevent duplicate event evidence upon repeated reconciliation or restart. The normal human-gate path SHALL require deterministic checks and authoritative independent complementary review; an additional audit SHALL be required only when an applicable policy or explicit human authorization requires it, and any such audit SHALL use a compatible, explicitly authorized provider and budget.

#### Scenario: Successful path reaches the human gate
- **WHEN** implementation/continuation completes, checks pass, the candidate is frozen, complementary review is authoritative, and repository identity is valid
- **THEN** the system advances to `PR_PREPARED` only after push/PR reconciliation proves the remote PR head equals the exact candidate
- **AND** records `READY_FOR_HUMAN_MERGE` as the separate human gate and stops
- **AND** requires audit evidence only if an applicable policy or explicit human authorization requires an audit for that candidate.

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

### Requirement: Existing pipeline coordination
The system SHALL invoke existing implementation, continuation, deterministic-check, and complementary-review authorities in their defined order and SHALL preserve their decisions and diagnostics. It SHALL invoke an independent audit only when explicitly required by applicable policy or human authorization, and SHALL preserve that audit's decision and diagnostics without treating DeepSeek Direct as a mandatory routine stage.

#### Scenario: Corrective implementation is governed by 007
- **WHEN** an implementation attempt is premature, falsely blocked, structurally blocked, or otherwise incomplete
- **THEN** the run delegates correction, reassignment, waiting, and escalation to the existing continuation governance and resumes from its persisted result.

#### Scenario: Review changes require remediation
- **WHEN** the authoritative complementary review returns `CHANGES_REQUIRED`
- **THEN** the run delegates remediation through continuation governance, freezes the resulting candidate as a new generation, and requires fresh authoritative review for that generation.

#### Scenario: Audit failure requires a full fresh audit
- **GIVEN** an audit is required by applicable policy or explicit human authorization
- **WHEN** the authorized audit returns a blocking result
- **THEN** the run delegates remediation, records the old audit as historical evidence, freezes the new candidate, and requires fresh evidence for the new candidate before any human-gate transition.

#### Scenario: Medium audit finding blocks advancement
- **GIVEN** an audit is required by applicable policy or explicit human authorization
- **WHEN** the current candidate's authorized audit contains one or more MEDIUM findings, regardless of any LOW findings or overall textual PASS claim
- **THEN** the audit cannot authorize progression to `PR_PREPARED` or `READY_FOR_HUMAN_MERGE` and remediation follows existing continuation governance.

#### Scenario: No routine audit is invoked without authority
- **GIVEN** the required checks and independent complementary review pass and no applicable policy or explicit human authorization requires an additional audit
- **WHEN** the pipeline evaluates advancement
- **THEN** it does not invoke DeepSeek Direct or another paid fallback audit
- **AND** the ordinary human gate remains governed by the independent review, required checks, and exact candidate evidence.

### Requirement: Candidate-bound evidence authority
The system SHALL bind each candidate generation to the registered base SHA, actual managed-worktree candidate SHA, manifest identity/hash, authorship history, and the review records that evaluated it. Any audit evidence that is required and obtained SHALL also be bound to that candidate generation and identity.

#### Scenario: Stale review cannot authorize a changed candidate
- **WHEN** remediation changes the candidate HEAD SHA or manifest
- **THEN** review authority for the prior generation is historical only and the run cannot advance until a new authoritative review is recorded for the current generation.

#### Scenario: Stale audit cannot authorize a changed candidate
- **GIVEN** an audit is required by applicable policy or explicit human authorization
- **WHEN** remediation occurs after an audit result
- **THEN** the prior audit is historical only and cannot authorize the changed candidate
- **AND** fresh required audit evidence for the exact new candidate is obtained before any human-gate transition.
