# Delta Specification: Scheduler and Recovery Convergence

## ADDED Requirements

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