# scheduler-and-recovery-convergence Specification

## Purpose
TBD - created by archiving change scheduler-and-recovery-convergence. Update Purpose after archive.

## Requirements

### Requirement: Single Canonical Recovery Authority
All mutating recovery/continuation entry points SHALL delegate to one canonical RecoveryConvergenceService and SHALL NOT independently decide or drive continuation.

#### Scenario: Startup, tick, and direct resume share authority
GIVEN identical durable state
WHEN continuation is requested by daemon startup, scheduler tick, REST/CLI resume, TUI/control-plane continue/retry, or post-merge reconciliation
THEN each request SHALL resolve through the same recovery authority
AND no entry point SHALL bypass durable claim/fencing or Stage F fresh-admission authority.

### Requirement: Durable Recovery Claim and Fencing
Slow mutating continuation SHALL require a durable PostgreSQL claim keyed to the canonical work identity with a monotonic fencing token.

#### Scenario: Two processes attempt same run continuation
GIVEN no valid current claim for `run:<run_id>`
WHEN two PostgreSQL sessions concurrently request continuation
THEN exactly one SHALL acquire the claim
AND the other SHALL observe the active claim and perform no mutating continuation.

#### Scenario: Expired claim is replaced
GIVEN a claim lease is expired
WHEN a successor acquires the same claim key
THEN PostgreSQL SHALL atomically increment the fencing token
AND the prior owner SHALL become stale
AND the prior owner SHALL NOT advance Run/Job/Saga lifecycle.

#### Scenario: Lease expiry does not authorize external replay
GIVEN the predecessor claim expired while an external action remains unresolved
WHEN a successor acquires the claim
THEN the successor SHALL reconcile the external action first
AND SHALL NOT repeat the external mutation solely because the recovery lease expired.

### Requirement: Safe recovery of orphaned stage invocations after restart
The coordinator SHALL recover an incomplete stage invocation only when the durable claim is no longer active, the recorded candidate and stage match the invocation being resumed, and persisted process identity evidence proves that the previous coordinator and workflow process group are gone. A different recorded boot identity SHALL classify the previous process as gone when the identity belongs to the same host. Recovery SHALL use the existing fenced claim mechanism to replace the expired ownership, record one auditable `STAGE_INVOCATION_ABANDONED` event with a reason grounded in the observed evidence, and start a new invocation for the same candidate and stage. A `DOC_CLOSING` worktree SHALL be recorded in the existing durable worktree-ownership registry before it is created or reused. Any reuse or recovery SHALL match the persisted run, Change, canonical path, registered source repository, branch, and base identity; a legacy worktree without an ownership record MAY be adopted only when an incomplete `SYNC` or `ARCHIVE` invocation event recorded while the Run was in `DOC_CLOSING`, together with Git worktree metadata, independently proves that exact identity, and the ownership record is persisted before cleanup. For an abandoned `SYNC` or `ARCHIVE` invocation in `DOC_CLOSING` whose managed worktree has uncommitted or untracked changes, recovery SHALL restore that exact owned worktree to its current `HEAD` before recalculating candidate identity; it SHALL NOT apply this reset to another stage, worktree, or candidate. Live, unknown, mismatched, or otherwise ambiguous process or worktree evidence SHALL remain fail-closed. A proven-absent process SHALL NOT bypass an active durable claim or its fencing rules. No direct database repair or manual SQL SHALL be required for the proven-dead restart case.

#### Scenario: Restarted host has a different boot identity
- **GIVEN** an incomplete invocation with an expired claim, an unchanged candidate and stage, and coordinator/workflow identities from an earlier boot on the same host
- **WHEN** the coordinator evaluates recovery and confirms the prior processes are gone
- **THEN** it SHALL record exactly one `STAGE_INVOCATION_ABANDONED` event citing the observed restart/process evidence
- **AND** it SHALL acquire a successor claim with a higher fencing token and start a new invocation for the same candidate and stage.

#### Scenario: Prior process is absent after scheduler restart
- **GIVEN** an incomplete invocation with an expired claim, an unchanged candidate and stage, and a recorded process identity whose PID is no longer present
- **WHEN** recovery verifies the coordinator, workflow process, and process group are gone
- **THEN** it SHALL durably mark the old invocation abandoned and proceed under a successor fenced claim
- **AND** the previous invocation SHALL NOT be treated as completed.

#### Scenario: Dirty documentation worktree is restored before identity is recalculated
- **GIVEN** an incomplete `SYNC` or `ARCHIVE` invocation recorded while its Run is in `DOC_CLOSING`, with an expired claim, proven-absent prior processes, and the exact still-owned worktree containing uncommitted or untracked changes
- **WHEN** recovery is authorized to acquire the successor fenced claim
- **THEN** it SHALL restore that worktree to its current `HEAD` using the approved managed-worktree cleanup boundary
- **AND** it SHALL recalculate the candidate fingerprint from the restored worktree
- **AND** it SHALL hold the current successor claim row for update in the same PostgreSQL transaction that persists both invocation events, preventing a competing fence from being acquired between validation and commit
- **AND** it SHALL persist the old `STAGE_INVOCATION_ABANDONED` event and successor `STAGE_INVOCATION_STARTED` event together in one PostgreSQL transaction after cleanup and current-fence validation
- **AND** it SHALL dispatch the same native operation for the restored candidate without treating the stale dirty fingerprint as a different active invocation.

#### Scenario: Archive recovery replays sync effects removed by reset
- **GIVEN** an abandoned `ARCHIVE` invocation in `DOC_CLOSING` and a previously completed native `SYNC` whose main-spec changes are uncommitted in the same worktree
- **WHEN** recovery resets that exact worktree to its current `HEAD`
- **THEN** the DOC_CLOSING flow SHALL rerun native `SYNC` for the same Change and worktree before `ARCHIVE`
- **AND** it SHALL require the replayed SYNC invocation's existing effect postcondition to succeed before archiving with `--skip-specs`
- **AND** it SHALL NOT treat a SYNC completion from before the reset as evidence that the synced main specs still exist.

#### Scenario: Documentation worktree ownership is persisted before reuse
- **GIVEN** a Run in `DOC_CLOSING` requests creation or reuse of its documentation worktree
- **WHEN** the worktree is returned to the coordinator
- **THEN** the existing durable ownership registry SHALL identify its project, run, Change, canonical path, source repository, branch, and base identity
- **AND** a mismatched or ambiguous existing path SHALL be rejected without modifying its contents.

#### Scenario: Legacy documentation worktree is adopted only from matching durable evidence
- **GIVEN** a documentation worktree exists without an ownership record while its Run is in `DOC_CLOSING`
- **WHEN** the persisted invocation identity and Git worktree metadata both match the requested run, Change, canonical path, registered repository, branch, and base identity
- **THEN** the system SHALL persist matching ownership before it reuses or cleans the worktree
- **AND** if any identity is missing or mismatched, it SHALL preserve the worktree and fail closed.

#### Scenario: Dirty worktree is not reset when recovery proof is incomplete
- **GIVEN** an incomplete invocation whose claim is active, whose process identity is live or unknown, or whose worktree ownership/candidate cannot be matched exactly
- **WHEN** recovery evaluates the invocation
- **THEN** it SHALL NOT reset, clean, or dispatch the worktree
- **AND** it SHALL preserve the existing claim and evidence for safe later reconciliation.

#### Scenario: Competing recovery cannot fence between validation and event commit
- **GIVEN** recovery has validated an expired DOC_CLOSING invocation under a successor claim whose lease expires before the recovery event transaction commits
- **WHEN** another scheduler attempts to reacquire that claim after the lease expires
- **THEN** the row lock held by recovery SHALL prevent the competing fence from being acquired before both `STAGE_INVOCATION_ABANDONED` and successor `STAGE_INVOCATION_STARTED` events commit
- **AND** after that commit, the existing claim mechanism MAY grant a newer fence to the competing scheduler

#### Scenario: Process identity is live or unknown
- **GIVEN** an incomplete invocation with an expired claim
- **WHEN** any required process or process-group identity is live, unknown, unavailable, or cannot be proven gone
- **THEN** recovery SHALL NOT abandon or redispatch the invocation
- **AND** it SHALL preserve the candidate, claim/event evidence, and fail-closed behavior.

#### Scenario: Candidate or stage does not match the interrupted invocation
- **GIVEN** an incomplete invocation with an expired claim
- **WHEN** the candidate identity or stage differs from the invocation being considered for recovery
- **THEN** recovery SHALL NOT reuse that invocation's abandonment evidence to dispatch work for the different candidate or stage.

#### Scenario: Stale worker returns after successor claim is acquired
- **GIVEN** recovery has acquired a successor claim with a higher fencing token
- **WHEN** the previous worker later attempts to record a result or mutate the run
- **THEN** the existing fencing checks SHALL reject that mutation
- **AND** the successor claim and run state SHALL remain unchanged by the stale worker.

### Requirement: Bounded Lease and Heartbeat
Recovery claims SHALL use configuration-backed leases with default 60 seconds and heartbeat default 15 seconds, with heartbeat strictly less than one-third of configured lease duration.

#### Scenario: Healthy driver renews claim
GIVEN a driver performs slow external work
WHEN heartbeat executes before lease expiry
THEN renewal SHALL succeed only through fenced compare-and-swap on the current claim identity
AND the same fencing token remains valid
AND another process SHALL NOT acquire the claim.

#### Scenario: Stale owner cannot heartbeat or release successor claim
GIVEN worker B has already acquired a higher fencing token
WHEN stale worker A attempts heartbeat or release with its prior token
THEN the compare-and-swap SHALL affect zero rows
AND worker B's lease/ownership SHALL remain unchanged.

### Requirement: No Database Lock Across Slow External I/O
Recovery SHALL persist claim/decision state in short transactions and SHALL release PostgreSQL row/advisory locks before slow Git, GitHub, provider, or subprocess I/O.

#### Scenario: External operation blocks
GIVEN an external operation is intentionally blocked
WHEN another DB session queries unrelated rows
THEN no recovery-held row/advisory transaction lock SHALL remain open solely for the slow I/O.

### Requirement: Atomic Fenced Dispatch Intent
A recovery worker SHALL NOT perform a slow external mutation after a standalone fence check. Immediately before dispatch it SHALL atomically compare-and-swap validate the current claim and persist a unique durable dispatch intent/attempt bound to the logical action, claim key, owner, fencing token, and attempt identity in the same short transaction.

#### Scenario: Lease expires between planning and dispatch
GIVEN worker A previously held a valid claim
AND its lease expires before external dispatch
AND worker B acquires a higher fencing token
WHEN worker A attempts to create the dispatch intent
THEN the fenced compare-and-swap SHALL affect zero rows or fail deterministically
AND worker A SHALL NOT issue the external mutation.

#### Scenario: Crash after dispatch intent commit
GIVEN a durable dispatch intent was committed as EXECUTING
WHEN the worker crashes before recording the remote result
THEN a successor SHALL treat the mutation as possibly executed
AND SHALL observe/reconcile the action before any repeat.

### Requirement: Fenced Claim Maintenance and Result Application
Heartbeat, release, pre-dispatch intent creation, and result application SHALL be fenced compare-and-swap operations using the current claim key, owner instance, fencing token, and expected lease/release state.

#### Scenario: Old worker returns after losing fence
GIVEN worker A loses its claim and worker B owns a higher fencing token
WHEN worker A later receives a remote success response
THEN A SHALL NOT advance lifecycle
AND any remote evidence SHALL only be recorded through monotonic action/evidence reconciliation for adoption by the current owner.

### Requirement: Durable Recovery Decision
Every recovery cycle SHALL persist at most one RecoveryDecision per claim key with prior checkpoint, observations, classification, planned action, fence token, source, and result.

#### Scenario: Duplicate decision inside one cycle
GIVEN two planners in the same recovery cycle target the same claim key
WHEN decisions are persisted
THEN `UNIQUE(cycle_id, claim_key)` SHALL allow only one canonical decision.

### Requirement: Recovery Before Fresh Admission
Interrupted/continuable work SHALL be classified and durably converged before new READY work is considered for fresh admission.

#### Scenario: Restart contains interrupted run and READY backlog
WHEN the daemon begins its first cycle
THEN the interrupted run SHALL be classified/claimed first
AND fresh admission SHALL occur only after recovery planning/convergence
AND all fresh admission SHALL still use `SchedulerService.admit_work_item()`.

### Requirement: Safe Checkpoint Resume
Recovery SHALL preserve committed candidate-bound implementation, checks, review, and audit evidence and SHALL never infer completion from interruption alone.

#### Scenario: Review and audit already committed
GIVEN a candidate has committed passing checks and candidate-bound authoritative review/audit evidence
WHEN restart occurs
THEN recovery SHALL continue from the next safe checkpoint
AND SHALL NOT rerun completed expensive phases.

#### Scenario: Provider interrupted without completion
GIVEN a provider process ended without committed completion evidence
WHEN recovery evaluates it
THEN success SHALL NOT be inferred
AND replay SHALL require an independently safe continuation decision.

### Requirement: Complete External Action Status Reconciliation
Every Stage B/D external action status SHALL follow explicit observation/repeat semantics.

#### Scenario: COMPLETED action
WHEN recovery sees COMPLETED
THEN it SHALL adopt the result and SHALL never repeat the mutation.

#### Scenario: RESERVED action
WHEN recovery sees RESERVED
THEN reservation existence SHALL NOT authorize mutation
AND recovery SHALL classify whether the action is PROVEN_NEVER_DISPATCHED or POSSIBLY_DISPATCHED
AND it SHALL observe the action-specific postcondition whenever prior dispatch cannot be excluded
AND adopt if already present
AND a first/repeat dispatch SHALL be allowed only when the effect is conclusively absent, Stage B/D original-mutation or explicit retry authorization permits dispatch, the current fence is valid, and a durable fenced dispatch intent is atomically committed before I/O
AND WAITING_EXTERNAL if the postcondition cannot be observed.

#### Scenario: EXECUTING action
WHEN recovery sees EXECUTING
THEN it SHALL assume the effect may have occurred
AND observe before repeat
AND repeat only if the effect is conclusively absent and existing Stage B/D retry authorization permits repeat.

#### Scenario: FAILED action
WHEN recovery sees FAILED
THEN repeat SHALL be permitted only when failure evidence proves the effect absent and original mutation retry is explicitly authorized.

#### Scenario: UNKNOWN or AMBIGUOUS action
WHEN recovery sees UNKNOWN or AMBIGUOUS
THEN observation is mandatory
AND observed success SHALL be adopted
AND proven absence MAY be repeated only with explicit retry authorization
AND temporary unobservability SHALL yield WAITING_EXTERNAL
AND contradictory evidence SHALL yield NEEDS_HUMAN.

### Requirement: Durable Saga Recovery Authority
Intake and closure recovery SHALL resume through durable SagaEngine checkpoints rather than direct service restart from phase zero.

#### Scenario: Intake saga at non-zero phase
WHEN startup recovery encounters it
THEN SagaEngine SHALL resume from the persisted phase
AND previously completed external actions SHALL be reconciled/adopted without duplication.

#### Scenario: Closure saga after observed merge
WHEN recovery encounters an incomplete closure saga
THEN closure SHALL continue from its durable phase under the parent run claim
AND SHALL not infer final closure from a terminal flag alone.

### Requirement: Waiting Capacity Recovery Requires Verified Provider Truth
A waiting-capacity run SHALL resume only after authoritative provider health positively proves required capacity AVAILABLE or DEGRADED and the run is re-read under current recovery authority.

#### Scenario: Reset estimate elapsed only
WHEN a reset timestamp passes without verified provider recovery
THEN the run SHALL remain waiting.

### Requirement: WAITING_EXTERNAL Cannot Be Cleared Blindly
A direct resume request for WAITING_EXTERNAL SHALL perform required remote/action observation before clearing the stop outcome or continuing.

#### Scenario: GitHub remains unobservable
GIVEN a run is WAITING_EXTERNAL for GitHub evidence
WHEN an operator requests resume
THEN the recovery authority SHALL re-observe GitHub
AND if still unobservable SHALL preserve WAITING_EXTERNAL
AND SHALL not drive the coordinator.

### Requirement: Terminal Parent Dominance with Closure Exception
Terminal execution state SHALL never be resurrected, while an already-authorized closure saga may finish closure-only work.

#### Scenario: DONE/COMPLETED parent with unfinished closure
THEN implementation/review/audit SHALL NOT resume
AND the existing closure saga MAY finish only its persisted closure/cleanup phases
AND SHALL NOT create a new Run/Job or reverse lifecycle state.

#### Scenario: CANCELLED parent
THEN execution SHALL NOT resume
AND only durable ownership-proven idempotent cleanup MAY continue.

### Requirement: PR Closed Unmerged Is Not Merge Closure
A PR closed without merge SHALL never enter merged closure phases.

#### Scenario: Unmerged PR cleanup
WHEN GitHub proves the PR is closed and unmerged
THEN merge completion SHALL remain false
AND cleanup SHALL use separately identified idempotent actions
AND lifecycle cancellation SHALL use Stage A authority
AND repeated recovery SHALL adopt existing cleanup effects rather than rerun them blindly.

### Requirement: Idempotent Repeated Recovery
Repeated startup/tick/direct requests against unchanged truth SHALL converge with zero duplicate transitions, runs, jobs, sagas, external actions, destructive cleanup, or expensive provider calls.

#### Scenario: Repeated recovery on unchanged state
GIVEN an active run has not changed state
WHEN recovery runs multiple consecutive cycles
THEN every cycle SHALL produce identical decisions with zero duplicate side effects.

### Requirement: Recovery Failure Isolation
One blocked/failed recovery identity SHALL be durably classified without preventing unrelated identities from being evaluated.

#### Scenario: One run fails recovery
GIVEN two active runs where run A encounters an unhandled exception during recovery
WHEN recovery cycle runs
THEN run A failure SHALL be isolated
AND run B SHALL still be evaluated and recovered.

### Requirement: Recovery Observability
Status SHALL expose durable RecoveryDecision evidence sufficient to explain source, prior checkpoint, observations, claim/fence, classification, and result without mutating state.

#### Scenario: Querying recovery decisions
GIVEN a recovery cycle completed decisions
WHEN status or control plane queries recovery decisions
THEN the response SHALL expose the durable RecoveryDecision evidence.

### Requirement: Provider and Pipeline Primitive Claim Context
Provider/pipeline execution primitives that can perform Git, GitHub, provider, model, or subprocess mutation from a continuation/recovery path SHALL be private behind the canonical convergence authority or SHALL require a validated RecoveryClaimContext.

#### Scenario: Direct primitive invocation without claim context
GIVEN a provider or pipeline primitive is reachable outside `drive_coordinator()` from a continuation/recovery path
WHEN it is invoked without a current `claim_key + owner_instance_id + fence_token`
THEN the mutation SHALL be rejected before external work begins.

### Requirement: Scheduler Entry-Point Convergence
CLI tick/run, REST tick, TUI tick, daemon loop, API/CLI resume, control-plane continue/retry, scheduler DRAIN continuation, waiting wake-up, queued-run drive, post-merge continuation, and direct provider/pipeline continuation primitives SHALL share canonical convergence semantics.

#### Scenario: Multiple entry points drive continuation
WHEN continuation is triggered via CLI, daemon, REST, or control plane
THEN all entry points SHALL route through RecoveryConvergenceService.

### Requirement: Legacy Capacity Contract Preservation
Delivered `scheduler-capacity-policy-convergence` behavior SHALL remain unchanged and SHALL be treated as predecessor behavior, not reimplemented.

#### Scenario: Capacity policy evaluation
WHEN evaluating provider capacity during recovery
THEN the existing Stage F capacity policy rules SHALL be strictly preserved.

### Requirement: Durable wake-up hints trigger canonical reconciliation
The Scheduler SHALL accept PostgreSQL wake-up notifications as non-authoritative hints that trigger an immediate reconciliation through the existing recovery and claim authority. It SHALL consult durable PostgreSQL state before dispatching any work, and a hint without still-eligible work SHALL produce no execution.

#### Scenario: Eligible work is reconciled after a wake-up
- **GIVEN** a committed durable action leaves a Run eligible for Scheduler processing
- **WHEN** the Scheduler receives its wake-up hint
- **THEN** it immediately reconciles the authoritative PostgreSQL state
- **AND** it processes the work only through the existing claims, fencing, permissions, gate fingerprint, Run identity, and idempotency rules.

#### Scenario: Obsolete or empty wake-up does not dispatch
- **GIVEN** a wake-up is duplicated, delayed, grouped, or refers to work that is no longer eligible
- **WHEN** the Scheduler reconciles PostgreSQL state
- **THEN** it SHALL perform no dispatch for that hint
- **AND** it SHALL NOT skip a gate or treat the notification as a queue or source of truth.

### Requirement: Scheduler wake-up lifecycle preserves reconciliation fallback
The Scheduler SHALL reconcile immediately at process startup and listener reconnection, and SHALL retain a lightweight periodic poll to recover from listener disconnection or lost notifications. Scheduler-produced transitions SHALL NOT create a self-triggering dispatch loop.

#### Scenario: Startup and reconnection reconcile
- **GIVEN** the Scheduler starts or its PostgreSQL listener reconnects
- **WHEN** the listener becomes usable
- **THEN** the Scheduler performs an immediate durable reconciliation
- **AND** it continues the configured lightweight periodic poll.

#### Scenario: Scheduler transition does not loop
- **GIVEN** the Scheduler produces a durable transition while processing eligible work
- **WHEN** that transition is observed by the notification path
- **THEN** it SHALL NOT cause duplicate processing of the same logical work
- **AND** concurrent workers SHALL still converge through the existing claims and idempotency.
