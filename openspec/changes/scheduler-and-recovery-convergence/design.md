# Design: Stage G — Scheduler and Recovery Convergence

## Canonical Base

`15e55c515ae917c2f0330809f0d9e44d49bce12b`

## Existing Reality

Recovery exists but authority is split across `RestartRecoveryService`, `SchedulerService.tick()`, `OrchestrationService.resume()`, control-plane actions, saga helpers, and post-merge reconciliation. The current code can therefore classify the same durable identity from more than one entry point.

Stage F row locks serialize short state transitions. They intentionally do not solve ownership of a long continuation after the DB lock is released. Stage G adds that missing durable ownership layer without holding PostgreSQL locks during slow I/O.

## Architectural Laws G1–G10

- **G1 Durable State First:** every mutating recovery decision re-reads canonical durable state.
- **G2 One Canonical Recovery Authority:** startup, tick, API/CLI resume, control-plane continue/retry, waiting wake-up, queued-run drive, and post-merge continuation delegate to one convergence authority.
- **G3 Durable Continuation Ownership:** any slow mutating continuation requires a durable recovery claim/fence.
- **G4 Observe Before Repeat:** a claim never authorizes blind replay of an external effect.
- **G5 Checkpoint Preservation:** committed candidate-bound checks/review/audit evidence survives restart.
- **G6 Recovery Before Admission:** interrupted/continuable work is converged before fresh READY admission.
- **G7 No Lock Across Slow I/O:** DB row/advisory locks are held only in bounded transactions, never around Git/GitHub/provider/subprocess waits.
- **G8 Terminal Dominance:** terminal execution cannot be resurrected; closure-only convergence may finish strictly within its existing durable saga.
- **G9 Fenced Result Application:** a worker whose claim token is stale may not advance Run/Job/Saga lifecycle.
- **G10 External Ambiguity Is Stronger Than Lease Expiry:** an expired recovery claim never makes an unresolved external mutation safe to repeat.
- **G11 Atomic Dispatch Intent:** fence validation and durable dispatch-intent persistence occur atomically in one short transaction immediately before slow mutation I/O.
- **G12 Fenced Claim Mutation:** heartbeat, release, dispatch-intent creation, and result application are compare-and-swap operations scoped to the current claim key, owner, fence token, and expected lease state.

## Canonical Recovery Service

Introduce `RecoveryConvergenceService` as the only public continuation/recovery authority.

Conceptual entry points:

- `reconcile_cycle(project_id=None, source=STARTUP|TICK)`
- `request_run_continuation(run_id, source, requested_action=None)`
- `reconcile_saga(saga_id, source)`
- `reconcile_action(action_key, source)`

`RestartRecoveryService` becomes a restart-evidence helper for process interruption and Git-lock inspection, not an orchestration driver.

Low-level methods such as `OrchestrationService.resume()`, `drive_coordinator()`, `SagaEngine.resume_saga()`, and `PostMergeReconciliationService.reconcile_post_merge()` remain implementation primitives but must not be reachable as public bypasses without a validated recovery claim context when they can drive slow mutation.

## Durable Recovery Claim / Fence

Stage G introduces PostgreSQL `recovery_claims`.

### Identity

Canonical `claim_key`:

- orchestration/run continuation, waiting wake-up, queued-run drive, post-merge continuation, closure saga bound to a run, and direct operator resume/retry: `run:<run_id>`
- intake saga before a run exists: `intake:<project_id>:<work_item_key>`
- orphan/non-run job only if no run identity exists: `job:<job_id>`

External actions do not get an independent competing claim when a parent run/saga claim exists; they execute under the parent claim plus their Stage B/D `action_key`.

### Schema

`RecoveryClaim` SHALL contain at least:

- `claim_key` UNIQUE / primary identity
- `fence_token BIGINT NOT NULL`, monotonic per claim key
- `owner_instance_id UUID/string NOT NULL`
- `claimed_at`
- `heartbeat_at`
- `lease_expires_at`
- `released_at` nullable
- `last_decision_id` nullable

### Lease Policy

- Default lease: 60 seconds, configuration-backed (not hidden magic).
- Heartbeat interval: 15 seconds, and MUST remain strictly less than one-third of lease duration if configuration changes.
- Claim acquisition/reacquisition happens in a short DB transaction.
- Existing unexpired claim owned by another instance => no continuation; classify as `NO_ACTION/CLAIMED_ELSEWHERE`.
- Released or expired claim may be reacquired by atomically incrementing `fence_token`.
- Expiry only transfers planning/driver ownership. It does **not** authorize repeating any unresolved external effect.

### Acquisition Transaction

1. begin transaction;
2. select claim row FOR UPDATE (or insert if absent);
3. re-read canonical Run/Job/Saga and terminal state;
4. reconcile whether an unresolved external action/attempt blocks mutation;
5. create/update RecoveryDecision;
6. atomically acquire claim and increment fence when permitted;
7. commit;
8. perform slow observation/external work outside DB locks.

Heartbeat, release, pre-dispatch validation, dispatch-intent creation, and result application SHALL all use fenced compare-and-swap semantics. The write predicate SHALL include at least `claim_key`, `owner_instance_id`, `fence_token`, and the expected current lease/release state. A stale owner therefore cannot renew, release, dispatch under, or finalize a successor's claim.

Immediately before every slow external mutation, the current worker SHALL open a short transaction that atomically:

1. re-validates the current RecoveryClaim by compare-and-swap predicate;
2. re-reads the canonical parent Run/Job/Saga state;
3. re-validates Stage B/D mutation authorization;
4. creates a unique durable external-action attempt/dispatch-intent identity bound to `action_key + claim_key + fence_token + attempt_id`;
5. transitions the external action/attempt into an execution-intent state (`RESERVED -> EXECUTING` or equivalent canonical attempt record) only when that transition is authorized;
6. commits before the network/Git/provider/subprocess mutation begins.

The uniqueness contract SHALL prevent two dispatch intents for the same logical action attempt. Once an EXECUTING/dispatch-intent record exists, any successor SHALL treat the action as **possibly executed** and MUST observe/reconcile its postcondition before any repeat.

There is therefore no bare 'validate fence, then call network' gap. The durable dispatch intent is the crash boundary.

Before applying a slow-operation result to Run/Job/Saga lifecycle, the worker SHALL again perform a fenced compare-and-swap validation. If the fence is stale, the worker SHALL NOT advance lifecycle. Remote evidence may still be persisted only through monotonic Stage B/D action/evidence reconciliation for adoption by the current owner.

### Crash / Lease Expiry

A successor may acquire an expired claim, but MUST first classify in-flight provider/external work:

- resolvable external action => observe and adopt/retry under Stage B/D rules;
- provider invocation with committed completion => adopt checkpoint;
- provider invocation interrupted with no verifiable completion => unfinished/WAITING_EXTERNAL or NEEDS_HUMAN according to existing outcome evidence; never infer success or blindly re-dispatch merely because the lease expired.

## Durable Recovery Decision

Introduce PostgreSQL `recovery_decisions`.

Minimum fields:

- `decision_id UUID`
- `cycle_id UUID`
- `claim_key`
- `identity_type`
- `identity_id`
- `project_id`, `change_name` where applicable
- `source` (STARTUP/TICK/API/CLI/TUI/CONTROL_PLANE)
- `prior_checkpoint` JSON
- `observation_refs` JSON
- `classification`
- `planned_action`
- `fence_token` nullable
- `status` (PLANNED/CLAIMED/EXECUTING/COMPLETED/BLOCKED/NO_ACTION)
- `result_payload` / `reason_code`
- timestamps

Unique invariant: `UNIQUE(cycle_id, claim_key)`.

The recovery claim prevents cross-cycle concurrent driving; the unique decision record prevents duplicate decision authority inside one cycle.

## Recovery Classification

- `NO_ACTION`
- `CLAIMED_ELSEWHERE`
- `RESUME_SAFE_CHECKPOINT`
- `ADOPT_OBSERVED_EFFECT`
- `WAITING_CAPACITY`
- `WAITING_EXTERNAL`
- `NEEDS_HUMAN`
- `TERMINAL_EXECUTION_BLOCKED`
- `CLOSURE_ONLY_CONTINUATION`

These are recovery classifications and need not become lifecycle enums.

## External Action Status Matrix

Every Stage B/D action is evaluated by `action_key` and action-specific observation/postcondition.

| Existing status | Required Stage G behavior |
|---|---|
| `COMPLETED` | adopt canonical result; never repeat mutation |
| `RESERVED` | reservation identity alone never authorizes dispatch. Observe the postcondition when observable. If effect exists, adopt COMPLETED. If conclusively absent, dispatch is allowed only when the original Stage B/D mutation authorization or explicit retry authorization still permits it, the current fenced claim is valid, and an atomic durable dispatch intent is committed first. If prior-dispatch possibility cannot be excluded or the postcondition is unobservable => WAITING_EXTERNAL. |
| `EXECUTING` | assume mutation may have occurred; observe before any repeat; success => COMPLETED/adopt; conclusively absent + existing Stage B/D retry authorization => repeat allowed; otherwise wait/human |
| `FAILED` | repeat only when failure evidence proves effect absent AND `original_mutation_retry_authorized=True`; otherwise preserve failure/human classification |
| `UNKNOWN` | mandatory observation; observed success => COMPLETED; proven absent + explicit retry authorization => authorized repeat; unobservable => WAITING_EXTERNAL; contradiction => NEEDS_HUMAN |
| `AMBIGUOUS` | mandatory observation with same outcomes as UNKNOWN; never auto-repeat merely because time/lease elapsed |

No recovery code may interpret reservation existence alone as permission to execute. Existing reservations are identities to reconcile, not invitations to rerun. For a recovered RESERVED record, the recovery planner MUST distinguish `PROVEN_NEVER_DISPATCHED` from `POSSIBLY_DISPATCHED`; only the former may proceed toward a first dispatch, and even then only with Stage B/D original-mutation authorization plus a newly committed fenced dispatch intent. `POSSIBLY_DISPATCHED` requires observation before any repeat.

## Direct Entry-Point Migration

The following mutating continuation entry points SHALL route through `RecoveryConvergenceService` or be made internal claim-requiring primitives:

1. daemon startup recovery;
2. periodic `SchedulerService.tick()`;
3. `OrchestrationService.resume()`;
4. direct `drive_coordinator()` recovery/queued-run invocation;
5. REST orchestration resume endpoint;
6. CLI orchestration resume/retry paths;
7. `ControlPlaneService` CONTINUE/RESUME/RETRY;
8. scheduler DRAIN continuation;
9. WAITING_CAPACITY wake-up;
10. WAITING_EXTERNAL continuation;
11. operator `RECONCILE_POST_MERGE`;
12. scheduler post-merge polling/reconciliation;
13. provider execution primitives that can issue model/provider calls outside `drive_coordinator()`;
14. pipeline stage primitives that can directly perform Git/GitHub/provider/subprocess mutation outside `drive_coordinator()`.

Any provider/pipeline primitive reachable from a recovery/continuation path SHALL either be private behind `RecoveryConvergenceService` or require a validated `RecoveryClaimContext` carrying `claim_key`, `owner_instance_id`, and `fence_token`. Fresh-admission-only primitives remain governed by Stage F as applicable.

Read-only status and query paths remain outside this command authority.

## Terminal Parent / Closure Rules

### DONE / COMPLETED parent

- execution implementation/review/audit must never resume;
- an already-existing closure saga bound to the verified merge may continue only from its durable closure checkpoint;
- closure continuation may finish spec/archive/Issue/Project/worktree cleanup and final evidence, but may not create a fresh Run/Job or move Change/Backlog to a nonterminal state.

### CANCELLED parent

- no execution resume;
- no new closure saga based on an unmerged PR;
- only bounded cleanup already authorized by durable ownership/action identity may proceed;
- cleanup must not infer merge/closure success.

### PR closed unmerged

- classify as not merged;
- do not enter merged closure phases;
- any branch/worktree/project cleanup is a separate idempotent cleanup action with durable action identity;
- lifecycle cancellation requests go through Stage A authority;
- repeated startup/tick/control-plane calls adopt existing cleanup records and do not re-run destructive cleanup blindly.

## Canonical Tick / Startup Order

1. capture provider/external observation inputs needed for fail-closed planning;
2. create recovery cycle;
3. classify/claim/reconcile active Runs/Jobs/Sagas;
4. converge waiting/external/post-merge/cleanup continuations;
5. release/complete claims as appropriate;
6. autonomous intake preparation;
7. discovery/queue projection;
8. fresh admission only through Stage F `SchedulerService.admit_work_item()`;
9. persist scheduler decisions and recovery observability.

Pre-counts are optimization only.

## Surface Audit G01–G20

| ID | Surface | Current state | Stage G requirement |
|---|---|---|---|
| G01 | daemon startup | separate RestartRecoveryService authority | delegate canonical cycle |
| G02 | periodic tick | embeds multiple recovery paths | delegate canonical cycle |
| G03 | interrupted Job checkpoints | partial candidate/check preservation | complete candidate/check/review/audit checkpoint mapping |
| G04 | active Run recovery | unlocked enumeration + direct resume | claim + locked re-read + fenced continuation |
| G05 | intake saga | direct prepare_work_item | SagaEngine checkpoint resume under intake claim |
| G06 | closure saga | direct reconcile_post_merge | durable closure checkpoint under run claim |
| G07 | external ambiguity | broad human escalation / direct resume gap | full action-status observation matrix |
| G08 | WAITING_CAPACITY | independent stale-data wake-up | claim + verified health + locked re-read |
| G09 | queued active Run | direct drive_coordinator | claim + canonical classification |
| G10 | post-merge | every tick may drive closure | run claim + closure saga + action reconciliation |
| G11 | recovery-before-admission ordering | substantially present | preserve and make contractual |
| G12 | repeated startup/tick | can overlap | durable claim + no-op convergence |
| G13 | concurrent scheduler processes | Stage F only protects fresh admission | durable recovery claim/fence |
| G14 | Git lock recovery | Stage C proof exists | preserve and include in decision envelope |
| G15 | observability | unconstrained events | durable RecoveryDecision invariant |
| G16 | entry-point parity | startup/direct resume differ | canonical service |
| G17 | direct CONTINUE/RESUME/RETRY | public/control-plane bypasses | canonical claim-required route |
| G18 | nonterminal ExternalAction statuses | inconsistent repeat boundaries | complete status matrix |
| G19 | PR closed unmerged / cleanup | cleanup/lifecycle can bypass closure saga semantics | terminal/cleanup rules + action identity |
| G20 | slow-I/O ownership gap | row lock ends before external work | lease/fence + heartbeat + fenced CAS + atomic dispatch intent |
| G21 | provider/pipeline direct primitives | can be invoked below coordinator boundary | require RecoveryClaimContext or make internal |
| G22 | stale claim maintenance writes | stale owner could heartbeat/release without explicit CAS contract | fenced CAS for heartbeat/release/pre-dispatch/result apply |

## Transaction / I/O Rules

- Never keep row/advisory locks open while waiting on Git/GitHub/provider/subprocess I/O.
- Claim acquisition and decision persistence are short DB transactions.
- Slow I/O occurs after claim commit.
- External mutation requires durable action reservation/identity before call.
- Immediately before external mutation dispatch, atomically CAS-validate the current fence, verify Stage B/D authorization, and persist a unique durable dispatch intent/attempt in the same short transaction.
- Heartbeat and release are fenced CAS operations; stale owners cannot extend or release a successor's claim.
- After external result, fenced CAS validation is required before advancing Run/Job/Saga.
- TransactionRetryWrapper must not wrap unreserved external side effects.
- Fresh admission remains Stage F-owned.

## Required Adversarial Evidence

Real PostgreSQL tests SHALL prove:

1. startup vs tick contention for same run => one claim/token drives;
2. tick vs direct API/control-plane resume => one driver;
3. expired claim increments fence; stale owner cannot apply lifecycle result;
4. no DB lock remains held during intentionally blocked slow external I/O;
5. repeated cycle with unchanged truth => no duplicate transitions/actions/provider calls;
6. existing RESERVED/EXECUTING/FAILED/UNKNOWN/AMBIGUOUS actions follow the table above;
7. pre-existing reservation does not itself cause duplicate Issue/Project/spec/worktree/branch mutation;
8. WAITING_EXTERNAL direct resume observes before clearing;
9. intake saga resumes from non-zero checkpoint;
10. closure saga resumes/adopts observed merge exactly once;
11. PR closed unmerged never enters merged closure and cleanup is idempotent;
12. candidate + checks + review + audit checkpoints are preserved;
13. terminal parent cannot restart execution;
14. waiting capacity requires verified provider truth;
15. recovery completes/classifies before fresh admission;
16. CLI/API/TUI/daemon/control-plane entry-point parity at canonical decision layer;
17. Stage A–F targeted regressions plus full suite after focused proving;
18. stale worker validates claim, lease expires before dispatch, successor acquires higher fence, and only one durable dispatch intent/network mutation is possible;
19. stale heartbeat and stale release both affect zero rows after fence increment;
20. RESERVED distinguishes proven-never-dispatched from possibly-dispatched and requires Stage B/D authorization in either eligible first/repeat path;
21. direct provider/pipeline primitive invocation without valid RecoveryClaimContext is rejected.

## OpenSpec Overlap

`scheduler-capacity-policy-convergence` is an already-delivered predecessor. Stage G preserves its four-decision capacity semantics and safe-pair behavior. At Stage G closure the stale active contract is archived/resolved without reimplementation.