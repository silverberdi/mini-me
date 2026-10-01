# Delta Specification: Scheduler and Recovery Convergence

## ADDED Requirements

### Requirement: Canonical Recovery Authority
The system SHALL have one canonical recovery authority that evaluates durable PostgreSQL state and verified external evidence to determine exactly one safe recovery action for each interrupted run, job, or saga.

#### Scenario: Startup and periodic tick produce same recovery decision
GIVEN identical durable state and external observations
WHEN recovery is invoked from daemon startup or a later scheduler tick
THEN both entry points SHALL resolve through the same recovery decision rules
AND SHALL NOT implement separate private recovery logic.

### Requirement: Recovery Before Fresh Admission
The scheduler SHALL reconcile interrupted/continuable durable work before considering new READY work for fresh admission.

#### Scenario: Restart with interrupted run and READY backlog
GIVEN one interrupted active run and one unrelated READY backlog item
WHEN the daemon starts
THEN recovery SHALL first classify and reconcile the interrupted run
AND fresh admission SHALL occur only after the recovery state is durably converged
AND fresh admission SHALL still pass through `SchedulerService.admit_work_item()`.

### Requirement: Safe Checkpoint Resume
Recovery SHALL resume only from a committed checkpoint whose candidate, stage, job, and evidence bindings are internally consistent.

#### Scenario: Completed expensive phase is preserved
GIVEN a run with candidate-bound passing checks already committed
WHEN restart recovery executes
THEN recovery SHALL preserve those checks
AND SHALL NOT rerun implementation/checks merely because the daemon restarted.

#### Scenario: Missing completion evidence never becomes success
GIVEN a provider phase was interrupted without committed completion evidence
WHEN recovery evaluates the run
THEN recovery SHALL classify the phase as interrupted/unfinished
AND SHALL NOT infer provider success.

### Requirement: External Action Reconciliation Before Repeat
Recovery SHALL reconcile Stage B/D external-action records before repeating any external mutation.

#### Scenario: Ambiguous external action with observable winner
GIVEN an external action is UNKNOWN or AMBIGUOUS
AND remote observation proves the intended effect already occurred
WHEN recovery executes
THEN recovery SHALL adopt the observed effect and advance from the durable checkpoint
AND SHALL NOT repeat the mutation.

#### Scenario: Temporarily unobservable remote state
GIVEN required remote evidence is temporarily unavailable
WHEN recovery cannot prove success or failure
THEN recovery SHALL fail closed to a waiting-external condition
AND SHALL NOT promote the run to success or repeat the action blindly.

#### Scenario: Contradictory evidence
GIVEN durable and remote evidence are irreconcilably contradictory
WHEN recovery evaluates the action
THEN recovery SHALL stop at NEEDS_HUMAN with explicit diagnostic evidence.

### Requirement: Durable Saga Recovery Authority
Active intake and closure sagas SHALL resume through SagaEngine checkpoint semantics and SHALL NOT be bypassed by direct uncheckpointed service execution.

#### Scenario: Intake saga restart
GIVEN an active intake saga at a persisted phase
WHEN daemon recovery executes
THEN the saga SHALL resume from its durable phase/checkpoint
AND SHALL reconcile any external action before repeating it
AND SHALL not restart preparation from phase zero.

#### Scenario: Closure saga restart
GIVEN an active closure saga
WHEN recovery executes
THEN closure SHALL continue through the durable closure saga authority
AND SHALL not infer final closure from a single terminal flag.

### Requirement: Run Recovery Uses Locked Canonical State
Recovery of an active orchestration run SHALL re-read and lock canonical run state before authorizing a mutating continuation.

#### Scenario: Two scheduler processes recover same run
GIVEN two independent scheduler processes observe the same recoverable run
WHEN both attempt continuation
THEN Stage F row-lock/concurrency guarantees SHALL serialize the command
AND at most one mutating continuation SHALL become canonical.

### Requirement: Waiting Capacity Recovery Requires Verified Truth
A waiting-capacity run SHALL resume only after authoritative provider health proves required capacity available.

#### Scenario: Reset timestamp passes without successful probe
GIVEN a capacity reset estimate has elapsed
BUT no verified provider observation marks the required provider AVAILABLE or DEGRADED
WHEN the scheduler reevaluates the run
THEN the run SHALL remain waiting
AND SHALL NOT resume from elapsed time alone.

### Requirement: Canonical Post-Merge Convergence
Post-merge reconciliation SHALL use one closure authority and repeated ticks/restarts SHALL adopt already-observed merge/closure evidence without duplicating closure effects.

#### Scenario: Merge observed before daemon restart
GIVEN GitHub proves the PR merged before local closure completed
WHEN startup recovery executes
THEN recovery SHALL resume/adopt the existing closure saga
AND SHALL not create duplicate closure actions.

### Requirement: Idempotent Repeated Recovery Cycles
Running recovery repeatedly against unchanged durable/external truth SHALL converge without creating duplicate runs, jobs, sagas, external actions, stage transitions, lifecycle transitions, or expensive provider calls.

#### Scenario: Second no-op recovery
GIVEN one recovery cycle has already converged all recoverable work
WHEN an immediate second recovery cycle runs with no new evidence
THEN it SHALL perform zero duplicate external effects
AND SHALL not regress any terminal or waiting state.

### Requirement: Scheduler Tick Ordering
One scheduler tick SHALL execute a deterministic high-level order: capture truth, reconcile recovery/continuations, converge closure/waiting work, perform autonomous intake/discovery, then evaluate fresh admission through Stage F authority.

#### Scenario: Recovery and fresh admission compete
GIVEN a recoverable in-flight run and a READY candidate
WHEN one tick executes
THEN recovery SHALL be evaluated before fresh admission
AND stale pre-count logic SHALL NOT authorize admission independently of Stage F locks.

### Requirement: Recovery Failure Isolation
A malformed or blocked work item SHALL not abort recovery or scheduling for unrelated work, but its failure SHALL be durably observable.

#### Scenario: One run recovery throws
GIVEN two recoverable runs
AND recovery of one deterministically fails
WHEN the recovery cycle executes
THEN the failed run SHALL be recorded as blocked/failed-closed
AND the other run SHALL still be evaluated.

### Requirement: Recovery Observability
Every recovery cycle SHALL produce durable, correlation-bound evidence describing the prior checkpoint, observed evidence, chosen action, and result.

#### Scenario: Operator inspects recovered run
GIVEN a run was recovered after restart
WHEN status is queried
THEN the operator SHALL be able to determine why recovery resumed, waited, adopted prior work, or required human intervention.

### Requirement: Entry-Point Convergence
CLI scheduler run/tick, REST scheduler tick, TUI tick action, and systemd scheduler loop SHALL delegate to the same canonical scheduler/recovery orchestration semantics.

#### Scenario: Identical state through different entry points
GIVEN the same durable state
WHEN a tick is initiated through CLI, REST, TUI, or daemon
THEN policy and recovery classification SHALL be equivalent
AND no entry point SHALL bypass recovery ordering or fresh-admission authority.

### Requirement: Legacy Scheduler Contract Supersession
The completed `scheduler-capacity-policy-convergence` behavior SHALL remain preserved, but Stage G SHALL become the sole active contract for scheduler/recovery convergence after closure.

#### Scenario: Capacity policy remains intact
GIVEN Stage G implementation
WHEN provider capacity/admission is evaluated
THEN the four-decision capacity semantics and safe executable pair behavior already delivered SHALL remain unchanged
AND Stage G SHALL not reimplement provider selection or routing.
