## MODIFIED Requirements

### Requirement: Durable deterministic orchestration lifecycle
The system SHALL persist a finite, ordered orchestration stage and checkpoint for every run, SHALL advance it only after the required authoritative evidence for that stage is committed, and SHALL use deterministic logical transition keys (`{run_id}:RESUME:{resumable_stage}:{current_generation}`) for resume operations and stage events to prevent duplicate event evidence upon repeated reconciliation or restart. For R01, Codex and AGY SHALL be selectable primary planning/execution providers by validated stage profile and SHALL support safe handoff of compatible work while preserving durable identity, checkpoints, fencing, and idempotent side-effect reconciliation. Read-only CONTRACT REVIEW SHALL precede APPLY and remain distinct from code REVIEW; DeepSeek Direct SHALL perform both as separate reviewer stages using its own account/API and separate evidence/usage records. Ordinary calls SHALL proceed autonomously when fresh provider capacity/balance, identity, compatibility, and the owner's applicable spending policy permit them; a new human approval or mandatory per-call maximum SHALL NOT be required. Usage SHALL be recorded from provider evidence. If a required review is unavailable, unknown, or disallowed by policy, wait without advancing through its gate. Neither review SHALL authorize APPLY, product decisions, or human merge. OpenRouter MAY rescue only already-started work after both primary providers are blocked by quota, using its own account/capacity and applicable spending policy; it SHALL NOT review or start READY work. An additional audit SHALL be required only when applicable policy or explicit human authorization requires it; audit evidence SHALL NOT substitute for either review.

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

#### Scenario: New CONTINUE recovers a committed checkpoint with failed acknowledgment
- **GIVEN** an active Run has one exact active Job in `CHECKS_FAILED`, a unique completed latest attempt matching `job.attempt_count`, and `job.candidate_sha` matching that attempt's `end_sha`
- **AND** the Run has no frozen `current_candidate_sha`, no pending/running/timed-out review, and no unresolved external action
- **AND** the latest exact Run-bound `CONTROL_PLANE` recovery decision is `RESUME_SAFE_CHECKPOINT` / `DRIVE_CONTINUATION` and remains `EXECUTING` under an expired or released claim
- **AND** a later failed CONTINUE record matches the Run's project, change, and current precondition stage; a null legacy `job_id` is accepted only via the Run's current `active_job_id`
- **WHEN** a new CONTINUE request with a distinct `action_request_id` is evaluated
- **THEN** the Control Plane exposes recovery only after verifying the exact run/job/attempt/candidate identity and stale fence evidence
- **AND** execution acquires a new current claim/fence and reuses the same Run, Job, worktree, and candidate checkpoint under all normal integrity, capacity, and idempotency guards
- **AND** it does not replay a review or external action whose outcome is pending, ambiguous, or unresolved
- **AND** live claims, contradictory Job identity, attempt/candidate mismatch, frozen candidate, active review, or unresolved external actions fail closed.

#### Scenario: Required DeepSeek review evidence is absent or unauthorized
- **GIVEN** DeepSeek reviewer compatibility, account identity, fresh capacity/balance, applicable owner spending policy, or contract/candidate-bound evidence is absent or uncertain
- **WHEN** the run evaluates advancement
- **THEN** it preserves the candidate in a truthful waiting/blocked state and does not treat audit or self-authored evidence as review.

### Requirement: Existing pipeline coordination
The system SHALL invoke existing PLAN, read-only CONTRACT REVIEW, implementation APPLY, implementation TEST, VERIFY/E2E, final REVIEW, 007 continuation, and PR authorities in their configured order and SHALL preserve their decisions and diagnostics. For R01, Codex and AGY SHALL be selected for compatible planning and execution stages by validated per-stage profiles and MAY hand off work under durable, fenced, idempotent authority. DeepSeek Direct SHALL perform separate read-only CONTRACT REVIEW and final code REVIEW using its own account/API, fresh capacity/balance, the applicable owner spending policy, and distinct usage accounting. Each review is distinct evidence and cannot authorize APPLY, product decisions, or merge, nor substitute for the other review. OpenRouter MAY rescue only already-started work after both primary providers are blocked by quota, using its own capacity/account and applicable spending policy; it SHALL NOT review or start READY work. The existing DeepSeek audit authority SHALL remain distinct and its result SHALL NOT be converted into either review type. An independent audit SHALL be invoked only when explicitly required by applicable policy or human authorization.

#### Scenario: Corrective implementation is governed by 007
- **WHEN** an implementation attempt is premature, falsely blocked, structurally blocked, or otherwise incomplete
- **THEN** the run delegates correction, reassignment, waiting, and escalation to the existing continuation governance and resumes from its persisted result.

#### Scenario: Review changes require remediation
- **WHEN** the authoritative DeepSeek reviewer returns `CHANGES_REQUIRED`
- **THEN** the run delegates remediation through continuation governance, freezes the resulting candidate as a new generation, and requires fresh authoritative review for that generation.

#### Scenario: Audit failure requires a full fresh audit
- **GIVEN** an audit is required by applicable policy or explicit human authorization
- **WHEN** the authorized audit returns a blocking result
- **THEN** the run delegates remediation, records the old audit as historical evidence, freezes the new candidate, and requires fresh required audit evidence for the new candidate before any human-gate transition.

#### Scenario: Medium audit finding blocks advancement
- **GIVEN** an audit is required by applicable policy or explicit human authorization
- **WHEN** the current candidate's authorized audit contains one or more MEDIUM findings, regardless of any LOW findings or overall textual PASS claim
- **THEN** the audit cannot authorize progression to `PR_PREPARED` or `READY_FOR_HUMAN_MERGE` and remediation follows existing continuation governance.

#### Scenario: DeepSeek reviewer is authorized only through its direct review authority
- **GIVEN** the DeepSeek reviewer contract, exact contract or candidate input, compatible read-only capability, authenticated direct account, fresh capacity/balance, and applicable owner spending policy are verified
- **WHEN** the structured DeepSeek review response passes deterministic validation and reviewer-independence checks
- **THEN** it may satisfy the review evidence requirement for that candidate
- **AND** no existing audit record or audit response is promoted to review evidence and human merge remains mandatory.

#### Scenario: R01 contract review is completed before implementation
- **GIVEN** a READY R01 change and a compatible DeepSeek contract-review profile with fresh direct-account capacity/balance and an applicable owner spending policy
- **WHEN** the orchestration reaches CONTRACT REVIEW
- **THEN** it performs the read-only contract review before APPLY and records separate contract-review evidence
- **AND** it does not treat that result as authorization for APPLY, final code REVIEW, product decisions, or merge.

#### Scenario: Required contract review waits when DeepSeek is unavailable
- **GIVEN** DeepSeek is not eligible for read-only CONTRACT REVIEW
- **WHEN** the orchestration reaches CONTRACT REVIEW
- **THEN** it preserves the work in a waiting state without substituting Codex, AGY, OpenRouter, an audit, or unauthenticated findings, and without APPLY or review inference.

#### Scenario: No routine audit is invoked without authority
- **GIVEN** required checks and authoritative independent review pass and no applicable policy or explicit human authorization requires an additional audit
- **WHEN** the pipeline evaluates advancement
- **THEN** it does not invoke DeepSeek Direct or another paid fallback audit
- **AND** the human gate remains governed by checks, review, and exact candidate evidence.

### Requirement: Candidate-bound evidence authority
The system SHALL bind each candidate generation to the registered base SHA, actual managed-worktree candidate SHA, manifest identity/hash, authorship history, and the code-review record that evaluated it. Contract-review evidence SHALL bind the exact OpenSpec contract revision and remain separate from candidate code-review evidence. Any audit evidence that is required and obtained SHALL also be bound to that candidate generation and identity. A DeepSeek reviewer record SHALL be distinct from an audit record and SHALL bind the repository identity, applicable contract revision or base/candidate SHA, generation, manifest when reviewing code, reviewer identity, sufficient review input, authorization/budget reference, and validated structured result.

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

#### Scenario: Capacity or balance is evaluated with the configured spending policy
- **GIVEN** a provider reports available quota or positive account balance
- **AND** the owner-configured spending policy for the exact provider/account permits the operation
- **WHEN** the orchestration prepares a paid stage
- **THEN** it may dispatch autonomously without a new per-call human approval
- **AND** records the stage and provider-reported usage durably without treating balance as a guarantee of unlimited coverage.

#### Scenario: Missing or restrictive spending policy blocks dispatch
- **GIVEN** capacity is available but no applicable owner spending policy exists, or an optional configured limit would be exceeded
- **WHEN** the orchestration prepares a paid stage
- **THEN** it preserves the checkpoint and does not dispatch.

#### Scenario: Unresolved usage does not fabricate settlement or globally block independent work
- **GIVEN** a prior provider call has an unresolved usage amount and no authenticated provider evidence can reconcile it
- **WHEN** the system evaluates that operation or an independent Run/Job
- **THEN** it retains the original unresolved exposure without inventing usage, cost, or a review result
- **AND** prevents blind replay of the uncertain operation
- **AND** does not block the independent operation unless its own capacity or applicable shared spending policy requires it.

#### Scenario: Failed contract review resumes as a distinct fenced operation
- **GIVEN** the same durable Run/Job has no candidate and its latest exact-contract DeepSeek CONTRACT REVIEW is terminal `REVIEW_FAILED`, with any unknown usage/reservation preserved as unresolved exposure
- **AND** there is no pending/running/timed-out review or contradictory external action
- **WHEN** canonical Control Plane `CONTINUE` resumes the Run and the existing `run:<run_id>` claim/fence has an executing `CONTROL_PLANE` continuation decision
- **THEN** mini me may create a new CONTRACT REVIEW record with a new review/operation identity and, when an owner-configured limit requires a reservation, a distinct reservation idempotency identity
- **AND** it rechecks fresh direct-account capacity, exact contract identity, owner spending policy, and any configured limits before dispatch
- **AND** leaves the failed review and its reservation unchanged, counting unresolved exposure against any applicable configured limits
- **AND** a later CONTINUE observes a pending/running checkpoint and does not dispatch the same operation again.

#### Scenario: Review recovery cannot bypass an incomplete or completed review gate
- **GIVEN** a review is `REVIEW_PENDING`, `REVIEW_RUNNING`, or `REVIEW_TIMED_OUT`, a same-contract review completed with changes required, the claim/fence is absent or stale, identity is contradictory, or a candidate already exists
- **WHEN** a continuation attempts to dispatch another CONTRACT REVIEW
- **THEN** mini me preserves all review, usage, Run/Job, candidate, and budget evidence
- **AND** does not replay or create a new review operation, alter lifecycle state, or advance to APPLY.

#### Scenario: Failed read-only contract review restores only its exact planning snapshot
- **GIVEN** the same Run/Job has only terminal failed CONTRACT REVIEW history for the exact contract, no implementation JobAttempt, no candidate, and a deleted worktree
- **AND** one durable `WORKTREE_RECOVERY_SNAPSHOT` event binds the exact project, Run, Job, change, canonical path, branch, snapshot SHA, and `authoritative_candidate=false`
- **AND** the snapshot commit has the original durable base as its sole parent and contains exactly the verified published OpenSpec artifact manifest for that change, with no code or extra paths
- **AND** canonical Control Plane `CONTINUE` holds the current exact Run claim/fence and an executing continuation decision, with no unresolved external action
- **WHEN** mini me reconstructs the owned worktree before starting a distinct CONTRACT REVIEW operation
- **THEN** it revalidates repository binding, remote identity and base ancestry, ownership, branch, Git registration, publication manifest, review identity, capacity, spending policy, and any configured limits
- **AND** preserves the original base, snapshot commit, failed review, and unresolved exposure
- **AND** fails closed without recreating the worktree if any evidence is missing, ambiguous, contradictory, or includes implementation progress.

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
The system SHALL stop at exactly one of `READY_FOR_HUMAN_MERGE`, `WAITING_CAPACITY`, `WAITING_EXTERNAL`, or `NEEDS_HUMAN` for the run's MVP lifecycle, and SHALL not merge, deploy, archive, or close the change automatically. `READY_FOR_HUMAN_MERGE` is only a human-gate outcome, not an orchestration stage. DeepSeek Direct code review, when valid under its direct-account capacity and the owner's applicable spending policy, can satisfy only the independent code-review gate and SHALL NOT satisfy or bypass human merge authorization.

#### Scenario: Operator resumes a waiting run
- **WHEN** provider capacity or a recoverable external condition is independently verified as restored/observable
- **THEN** `orchestrate resume` continues the same run from its durable checkpoint without repeating completed authoritative work.

#### Scenario: External wait is not capacity wait
- **WHEN** GitHub or another non-provider dependency is temporarily unavailable
- **THEN** the run uses `WAITING_EXTERNAL`, while `WAITING_CAPACITY` remains reserved for canonical 005/006 capacity evidence.

#### Scenario: Human merge remains mandatory
- **GIVEN** a run has current passing checks and authoritative independent DeepSeek code review
- **WHEN** the run reaches `READY_FOR_HUMAN_MERGE`
- **THEN** mini me exposes the exact PR, base SHA, candidate SHA, manifest/review evidence, any required audit evidence, and stop reason while taking no merge action.
