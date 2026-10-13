## MODIFIED Requirements

### Requirement: Durable deterministic orchestration lifecycle
The system SHALL persist a finite, ordered orchestration stage and checkpoint for every run, SHALL advance it only after the required authoritative evidence for that stage is committed, and SHALL use deterministic logical transition keys (`{run_id}:RESUME:{resumable_stage}:{current_generation}`) for resume operations and stage events to prevent duplicate event evidence upon repeated reconciliation or restart. The normal human-gate path SHALL require deterministic checks and authoritative independent review from an eligible complementary primary or, only when no eligible primary reviewer can serve, an explicitly authorized, compatible, candidate-bound DeepSeek Direct read-only reviewer. An additional audit SHALL be required only when applicable policy or explicit human authorization requires it; audit evidence SHALL NOT substitute for review evidence.

#### Scenario: Successful path reaches the human gate
- **WHEN** implementation/continuation completes, checks pass, the candidate is frozen, authoritative independent review is valid, and repository identity is valid
- **THEN** the system advances to `PR_PREPARED` only after push/PR reconciliation proves the remote PR head equals the exact reviewed candidate
- **AND** records `READY_FOR_HUMAN_MERGE` as the separate human gate and stops
- **AND** requires audit evidence only if applicable policy or explicit human authorization requires an audit for that candidate.

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

#### Scenario: Review evidence is absent or unauthorized
- **GIVEN** no eligible primary reviewer is available and DeepSeek reviewer compatibility, explicit provider/budget authorization, or candidate-bound evidence is absent or uncertain
- **WHEN** the run evaluates advancement
- **THEN** it preserves the candidate in a truthful waiting/blocked state and does not treat audit or self-authored evidence as review.

### Requirement: Existing pipeline coordination
The system SHALL invoke existing implementation, 007 continuation, deterministic-check, and independent-review authorities in their defined order and SHALL preserve their decisions and diagnostics. An eligible complementary primary SHALL be the normal reviewer. If no eligible primary reviewer can serve, a separately defined DeepSeek Direct read-only reviewer MAY satisfy the review gate only when compatibility, sufficient review input, identity independence, structured-output validation, exact candidate binding, and explicit per-stage provider/budget authorization are all proven. The existing DeepSeek audit authority SHALL remain distinct and its result SHALL NOT be converted into review evidence. An independent audit SHALL be invoked only when explicitly required by applicable policy or human authorization.

#### Scenario: Corrective implementation is governed by 007
- **WHEN** an implementation attempt is premature, falsely blocked, structurally blocked, or otherwise incomplete
- **THEN** the run delegates correction, reassignment, waiting, and escalation to the existing continuation governance and resumes from its persisted result.

#### Scenario: Review changes require remediation
- **WHEN** an authoritative primary or qualifying DeepSeek reviewer returns `CHANGES_REQUIRED`
- **THEN** the run delegates remediation through continuation governance, freezes the resulting candidate as a new generation, and requires fresh authoritative review for that generation.

#### Scenario: Audit failure requires a full fresh audit
- **GIVEN** an audit is required by applicable policy or explicit human authorization
- **WHEN** the authorized audit returns a blocking result
- **THEN** the run delegates remediation, records the old audit as historical evidence, freezes the new candidate, and requires fresh required audit evidence for the new candidate before any human-gate transition.

#### Scenario: Medium audit finding blocks advancement
- **GIVEN** an audit is required by applicable policy or explicit human authorization
- **WHEN** the current candidate's authorized audit contains one or more MEDIUM findings, regardless of any LOW findings or overall textual PASS claim
- **THEN** the audit cannot authorize progression to `PR_PREPARED` or `READY_FOR_HUMAN_MERGE` and remediation follows existing continuation governance.

#### Scenario: DeepSeek reviewer is authorized only as a distinct reviewer
- **GIVEN** no eligible primary reviewer can serve and the DeepSeek reviewer contract, exact candidate input, compatible read-only capability, explicit authorization, and budget are verified
- **WHEN** the structured DeepSeek review response passes deterministic validation and reviewer-independence checks
- **THEN** it may satisfy the review evidence requirement for that candidate
- **AND** no existing audit record or audit response is promoted to review evidence and human merge remains mandatory.

#### Scenario: No routine audit is invoked without authority
- **GIVEN** required checks and authoritative independent review pass and no applicable policy or explicit human authorization requires an additional audit
- **WHEN** the pipeline evaluates advancement
- **THEN** it does not invoke DeepSeek Direct or another paid fallback audit
- **AND** the human gate remains governed by checks, review, and exact candidate evidence.

### Requirement: Candidate-bound evidence authority
The system SHALL bind each candidate generation to the registered base SHA, actual managed-worktree candidate SHA, manifest identity/hash, authorship history, and the review records that evaluated it. Any audit evidence that is required and obtained SHALL also be bound to that candidate generation and identity. A DeepSeek reviewer record SHALL be distinct from an audit record and SHALL bind the repository identity, base SHA, candidate SHA, generation, manifest, reviewer identity, sufficient review input, authorization/budget reference, and validated structured result.

#### Scenario: Stale review cannot authorize a changed candidate
- **WHEN** remediation changes the candidate HEAD SHA or manifest
- **THEN** review authority for the prior generation is historical only and the run cannot advance until a new authoritative review is recorded for the current candidate.

#### Scenario: Stale audit cannot authorize a changed candidate
- **GIVEN** an audit is required by applicable policy or explicit human authorization
- **WHEN** remediation occurs after an audit PASS
- **THEN** the prior PASS is historical only and cannot authorize the new candidate
- **AND** fresh required audit evidence for the exact new candidate is obtained before any human-gate transition.

#### Scenario: Invalid DeepSeek reviewer evidence fails closed
- **GIVEN** DeepSeek review evidence is missing required input, malformed, stale, ambiguous, unauthorized, or identity-conflicting
- **WHEN** the pipeline evaluates the review gate
- **THEN** it rejects that evidence, preserves the candidate, and waits or blocks without deriving approval from audit output.

### Requirement: Idempotent human-gate preparation
The system SHALL make branch push and GitHub PR creation/update idempotent, SHALL reserve and persist a durable external-action identity, target identity, and request fingerprint before every covered mutation, and SHALL never push or expose a candidate that lacks current required checks and authoritative independent review; any separately required audit SHALL also be current and candidate-bound.

#### Scenario: Restart during PR creation
- **WHEN** the daemon restarts after GitHub accepted a PR creation but before local completion was recorded
- **THEN** recovery reconciles the durable binding and remote evidence, records the existing PR, and does not create a duplicate PR or push a candidate lacking current required evidence.

#### Scenario: External mutation requires reservation
- **WHEN** branch push or PR create/update is requested
- **THEN** the system first durably reserves the action identity, target identity, and request fingerprint; if reservation fails, the mutation is not executed and the run stops safely.

#### Scenario: Remote PR head differs
- **WHEN** the existing PR head SHA differs from the current candidate SHA with valid required check/review evidence
- **THEN** the system fails closed with a structured human stop and does not overwrite or merge the PR automatically.

#### Scenario: Ambiguous external action is reconciled before retry
- **WHEN** an external mutation returns an ambiguous result
- **THEN** the system reconciles remote state before any retry; temporary inability to observe remote state produces `WAITING_EXTERNAL`, while contradictory evidence produces `NEEDS_HUMAN`.

### Requirement: Human-gate contract
The system SHALL stop at exactly one of `READY_FOR_HUMAN_MERGE`, `WAITING_CAPACITY`, `WAITING_EXTERNAL`, or `NEEDS_HUMAN` for the run's MVP lifecycle, and SHALL not merge, deploy, archive, or close the change automatically. `READY_FOR_HUMAN_MERGE` is only a human-gate outcome, not an orchestration stage. DeepSeek review, when used under the explicit fallback contract, can satisfy only the independent review gate and SHALL NOT satisfy or bypass human merge authorization.

#### Scenario: Operator resumes a waiting run
- **WHEN** provider capacity or a recoverable external condition is independently verified as restored/observable
- **THEN** `orchestrate resume` continues the same run from its durable checkpoint without repeating completed authoritative work.

#### Scenario: External wait is not capacity wait
- **WHEN** GitHub or another non-provider dependency is temporarily unavailable
- **THEN** the run uses `WAITING_EXTERNAL`, while `WAITING_CAPACITY` remains reserved for canonical 005/006 capacity evidence.

#### Scenario: Human merge remains mandatory
- **GIVEN** a run has current passing checks and authoritative review from an eligible primary or qualifying DeepSeek reviewer
- **WHEN** the run reaches `READY_FOR_HUMAN_MERGE`
- **THEN** mini me exposes the exact PR, base SHA, candidate SHA, manifest/review evidence, any required audit evidence, and stop reason while taking no merge action.
