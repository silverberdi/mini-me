## Context

See `proposal.md` for the user value and scope. The binding technical contract is the complete pre-OpenSpec analysis at `docs/architecture/pre-openspec/safe-frozen-candidate-code-review-continuation.md`, commit `aa98f266be1957c1f21272b5a26e0cbbd3a4f828`; this Change translates that analysis into reviewable OpenSpec, not a new architecture study.

The product already has a canonical Control Plane, `RecoveryConvergenceService` claims and fencing, frozen `OrchestrationCandidate`/`CandidateManifest` evidence, `DeepSeekCodeReviewService`, `BudgetService`, durable `OperatorActionRecord`, `BudgetReservation`, `Review`, and external-action/recovery checkpoints. The needed capability is a narrow continuation that invokes the existing independent reviewer and safely finalizes its result without re-entering the general implementation pipeline.

Focused read-only verification on 2026-10-20, on the production PostgreSQL host, established the following for N01 (no writes were performed):

- Run `8e7ebec8-9eff-478b-bae3-cf686ea91be2`, Job `b917a9f0-0354-4805-863f-7ab4e7ada559`, candidate SHA `2fcad0ef73eb4766ca1bb6249a081cb4070ecced`, generation 1, base `6c051b87eb9a8f379e9305b62773bf486a7825f5`, are joined consistently; candidate is frozen.
- The exact manifest record is `2f8ec99f-c3c2-4f23-99cb-13fd6115c717`, hash `422f505120debda6f7b0645bcb92be4e9bb89a4f6bab050f0fefbde87cd2690a`, 55 files. Durable authorship records one primary `antigravity` author for attempt 1. These are database facts, not a fresh verification of candidate contents or authorship beyond the stored records.
- The project's configured check set is exactly `pytest -q`. For the same candidate SHA and generation, one historical result failed on 2026-10-18 and the later result passed on 2026-10-20. Thus the current full configured batch is passing while the earlier failure remains preserved. No test suite was run as part of this proposal.
- The Run remains `FREEZING_CANDIDATE` / `NEEDS_HUMAN`, with `REVIEW_AUTHORIZATION_PENDING`; the Job is `CHECKS_PASSED`. No durable `AUTHORIZE_DEEPSEEK_CODE_REVIEW` action or CODE_REVIEW reservation/review exists. The stored CONTRACT_REVIEW is distinct and does not authorize CODE_REVIEW.
- The query ran in a PostgreSQL `READ ONLY` transaction against database `minime` on the service's private network. No records were changed. Production N01 itself was neither resumed nor dispatched.

## Goals / Non-Goals

**Goals:**

- Provide one canonical, review-only continuation under the current Run claim/fence, using the existing direct DeepSeek CODE_REVIEW service and validated review authority.
- Require exactly the latest complete configured check batch, bound to the current frozen candidate SHA and generation; preserve older results as history.
- Consume exceptional one-shot authorization durably and link it to the exact reservation, review checkpoint, action, and candidate before provider I/O.
- Converge review verdict and spend evidence safely; stop at the authorized human gate for N01, while preserving ordinary autonomous flow for non-pilot Runs.
- Reconcile the minimal stale OpenSpec instructions that conflict with the higher-precedence canonical reviewer policy.

**Non-Goals:**

- No N01 execution, provider call, check rerun, authorization creation, PostgreSQL mutation, scheduler activation, PR, merge, deployment, or production configuration change in this Change proposal.
- No provider/policy redesign, new scheduler/orchestrator, generic budget system, routine per-call approval, new reviewer, OpenRouter/primary-provider substitution, new migration unless implementation proves existing persistence insufficient, or general repair of unrelated lifecycle state.
- No automatic APPLY/remediation after a N01 verdict, no automatic merge, and no changes to the frozen candidate or historical check rows.

## Decisions

### 1. Extend the canonical continuation path; do not create a parallel runner

Control Plane authorization/continuation acquires or validates the existing `run:<run_id>` recovery claim, starts one heartbeat owner, and uses the monotonic fence through the durable checkpoint and result application. `RecoveryConvergenceService` remains the recovery authority. Add only a narrowly classified review-only continuation branch for the exact review hold; generic `CONTINUE` must reject this hold before mutating Run stage, Job state, attempt count, or candidate.

Use the existing stage checkpoint/RecoveryDecision and durable action records as the source for recovery. An expired/lost fence, another live claimant, mismatched checkpoint, or contradictory action state blocks without provider I/O. No database row/advisory lock is held across HTTP.

**Alternative rejected:** invoking `ExecutionPipelineService.execute_queued_job` or creating a second review coordinator. The pipeline can cross into APPLY/checks/audit/PR and is not a safe review-only boundary.

### 2. Share one authoritative current-check-batch validator

The Control Plane authorization descriptor/execution and `DeepSeekCodeReviewService` must use the same semantic rule as `_validate_current_checks_batch` (shared collaborator or delegation, chosen during APPLY without a second weaker predicate): expected configured check names exactly once, exact commands, candidate SHA and generation, bounded time clustering, and every result passing in the newest complete batch. Historical rows remain immutable evidence but are excluded from the current batch. Empty configuration is not implicit permission for exceptional review-only continuation.

The N01 read-only query verified one configured check (`pytest -q`), with an older failed result and a later passing result bound to the same SHA/generation. This supports the requirement that latest-batch selection retain the historical failure without treating it as current. The Change must still verify at runtime; the observation does not waive fresh preflight.

**Alternative rejected:** accepting any row with `exit_code == 0`, which can authorize an incomplete or stale batch.

### 3. Keep the existing reviewer and account/budget authorities

The only reviewer for this path is `DeepSeekCodeReviewService.review_candidate` via DeepSeek Direct. Reuse fresh capacity, model/effort/account, price snapshot, spending policy, review-authority, manifest, authorship-independence, and payload selection validations. Do not route DeepSeek credentials through OpenRouter. A balance/capacity observation is not itself spend authority. Ordinary Runs retain the already-approved autonomous review policy and optional owner-configured limits; the one-shot human authorization is exceptional to the N01 pilot gate only.

Before billable HTTP, validate the durable `AUTHORIZE_DEEPSEEK_CODE_REVIEW` record against Run, Job, candidate/base SHA, generation, manifest id/hash, reviewer model/account, verified pricing snapshot, expiry, and authorized maximum. Consume/link the authorization once to the existing reservation and Review record, using the existing unique `action_request_id`, reservation `authorization_id`/`idempotency_key`, and `Review.budget_authorization_id`/`budget_reservation_id` fields. Persist a fenced dispatch intent/checkpoint before HTTP. Reservation, consumed authorization linkage, review checkpoint, and action/evidence state must be transactionally consistent using the existing persistence transaction boundary; if existing repositories cannot provide the required compare-and-swap/atomic linkage, stop and propose the smallest Alembic-backed persistence extension rather than approximating it.

**Alternative rejected:** treating `OperatorActionRecord.status=COMPLETED` as proof that review already executed or as reusable authorization. Authorization and execution are distinct. Also rejected: a second budget system or reusing OpenRouter reservations.

### 4. Review-only dispatch and safe finalization

After fenced preflight and durable one-shot consumption, invoke the existing DeepSeek reviewer once. It must receive a read-only, candidate-bound payload and must not write to the repository. Use the existing structured-verdict and usage/settlement handling. Reuse/extract only safe finalization primitives from `ExecutionPipelineService`: post-review integrity validation, fence validation, result persistence, review status transition, and event/metrics recording. Final state is a durable `REVIEW_COMPLETED` (or explicit failure/ambiguous status) for the same SHA/base/generation/manifest, with verified cost or unresolved exposure as the existing accounting policy requires.

The review-only operation ends at that durable review result; it never itself continues to audit, PR, APPLY, checks, or merge. A later continuation is a separate, explicitly authorized Control Plane action with a fresh `action_request_id`, optimistic preconditions and the same canonical Run claim/fence authority. It must validate the completed review and all frozen-candidate identity (Run, Job, project/change, candidate/base SHA, generation, manifest id/hash, review id/verdict/provider/account/independence) again, then resume at `COMPLEMENTARY_REVIEW` or the existing equivalent post-review checkpoint. It must never route through `IMPLEMENTING`, re-run checks, or call DeepSeek again for a review already durably completed. A stale or missing review, contradictory identity, absent authorization, concurrent owner, or lost fence blocks before mutation.

For N01's exceptional pilot, the separate continuation is available only for a valid `READY_TO_MERGE` review and an explicit new operator action; a favorable reviewer verdict is not that action. It resumes through the existing normal downstream audit and PR preparation/publishing gates, each under its established authority. It does not authorize merge, which remains human. `CHANGES_REQUIRED` does not take this continuation: preserve findings and the frozen candidate and require a separate, explicitly authorized remediation decision under existing candidate-remediation rules. Never alter the frozen candidate in place. For ordinary Runs, preserve the canonical autonomous next-stage/remediation behavior; do not add a per-review human approval.

**Alternative rejected:** interpreting reviewer `READY_TO_MERGE` as automatic permission to prepare/publish a PR, skip audit, or merge. Also rejected: generic `CONTINUE` without a review-completed checkpoint selector, because it can reset the Run to `IMPLEMENTING` and repeat work.

### 5. Treat dispatch uncertainty as ambiguity, not retry permission

Atomically record at-most-one dispatch intent under current claim/fence before the external request. A timeout, process crash, lost fence, or response uncertainty after dispatch is recorded as `AMBIGUOUS`/the canonical equivalent and cannot trigger blind repeated HTTP. Reconciliation may use only authentic provider/transport evidence under existing policies; it must not fabricate a verdict or spend. Do not claim remote exactly-once behavior unsupported by DeepSeek. Idempotent action request IDs and a later explicit safe recovery may reconcile durable local state but cannot repeat an uncertain billable request.

### 6. Preserve observable evidence and correct only scoped policy instructions

Expose current-check status separately from historical check history and expose honest review/gate state through existing status/API/UI projections. Do not delete old failures or claim checks are green from a historical result.

At the same Change implementation stage, make the minimum wording correction to `openspec/config.yaml` and `docs/CHANGE_DELIVERY_CONTRACT.md` so neither implies DeepSeek Direct is unavailable for an ordinary authorized independent review or conflates it with OpenRouter rescue. Align wording with `docs/CANONICAL_DECISIONS.md` and `AGENTS.md`; do not change provider roles, budget policy, or unrelated policy text. Other stale historical descriptions may be listed for later reconciliation only if this Change's active instructions would otherwise contradict canonical authority.

### 7. Reuse persistence unless proof shows it cannot express the contract

Existing durable entities already represent the relevant identity: `OperatorActionRecord`, `BudgetReservation` (unique authorization/idempotency identity), `Review` (authorization/reservation linkage, candidate and manifest binding), `RecoveryClaim`/`RecoveryDecision`, and external-action dispatch intent. No migration is currently justified by the source/model inspection. During APPLY, prove atomic transaction/CAS semantics and uniqueness under PostgreSQL concurrency. If they are insufficient, keep the implementation blocked until a minimal versioned Alembic migration and rollback-compatible transition are specified; do not add a parallel table or hand-edit schema.

## Operational Call Graph

```text
Control Plane (one review-only action/continuation)
  -> validate current Run/Job review-hold identity and fresh exact candidate/check batch
  -> RecoveryConvergenceService: acquire/renew run:<id> claim + one heartbeat + fence
  -> consume/link one-shot action + existing BudgetService reservation + Review checkpoint
  -> persist fenced dispatch intent and release DB locks
  -> DeepSeekCodeReviewService.review_candidate (DeepSeek Direct, read-only)
  -> reconcile authentic usage/cost; validate post-review candidate integrity under fence
  -> persist verdict/findings + REVIEW_COMPLETED + durable events
  -> stop at durable review-completed gate
  -> separate explicitly authorized Control Plane CONTINUE + fresh claim/fence + exact review/candidate validation
       -> READY_TO_MERGE: resume COMPLEMENTARY_REVIEW/equivalent -> existing audit -> PR policy gates -> human merge
       -> CHANGES_REQUIRED: preserve evidence; require separate authorized remediation decision
       -> never repeat APPLY/checks/CODE_REVIEW for this completed review
```

Every stage checks exact Run/Job/project/change, candidate/base SHA, generation, manifest id/hash, provider/account/model/effort, claim owner/fence, action id, reservation id, and expected stage. No action may resolve repository identity from caller-supplied prose.

## Verification and Traceability

The new spec is the acceptance authority and maps FCR-01–09 to observable requirements and E01–12 to PostgreSQL+Git, intercepted provider, API/status, lifecycle, adversarial and explicitly gated post-deployment scenarios. Tests must use disposable PostgreSQL and real Git/worktrees for state/identity/fencing; intercept the DeepSeek HTTP boundary for deterministic unit/integration cases. A mocked HTTP review is never reported as paid/provider E2E. E12 requires a separate human authorization and is not part of propose or routine CI. E07/E08/E10/E11 additionally prove the separate post-review continuation: READY_TO_MERGE proceeds only after a new governed action, CHANGES_REQUIRED waits for a distinct remediation authority, generic CONTINUE cannot re-enter implementation, and ordinary Runs retain autonomous continuation.

The final verification must include ordinary autonomous-flow recovery (E11), N01 history preservation, and no unintended `JobAttempt`/APPLY/check rerun. The final N01 review is a separate operational gate after implementation, merge, deployment, fresh authority/capacity/budget checks, and explicit authorization; this proposal does not grant it.

## Removal Ledger

No known implementation is approved for removal at proposal time. APPLY must inventory actual consumers and prove parity before retiring any superseded branch.

| Disposition | Surface / evidence required |
|---|---|
| REUSE | `ControlPlaneService` action discovery/idempotency; `RecoveryConvergenceService` claim, heartbeat, fencing and checkpoint; candidate/manifest/authorship repositories; existing `DeepSeekCodeReviewService`; `BudgetService`; review authority and post-review integrity validator; current-check-batch semantics; API/status projections. |
| MODIFY | Existing review-only authorization/continuation dispatch to require the full latest batch and one-shot linkage; review finalization to use fenced safe primitives; status projection only where it currently conflates history with current checks; stale OpenSpec/provider instructions named above. |
| REMOVE (only after E2E parity) | Any weaker `any passing row` authorization predicate, duplicate check-batch predicate, or route that can funnel this exceptional review-only continuation into generic APPLY/check/audit/PR execution. Identify all callers first; remove only after stage E2E and repeat all affected regressions after removal. |
| RETAIN WITH REASON | Ordinary autonomous review/verification pipeline; historic `CheckResult`, review, reservation, action and candidate evidence; general `execute_queued_job`; current OpenRouter rescue authorities for their separately defined role. |
| OUT OF SCOPE | OpenSpec generation/sync/archive, provider onboarding or selector redesign, generic budget refactor, unrelated intake/lifecycle changes, broad PWA redesign, production scheduler behavior. |

## Risks / Trade-offs

- [Lost claim or duplicate dispatch around slow HTTP] → Durable fenced intent before I/O; one heartbeat owner; fail closed on uncertainty; never blind retry.
- [Historical passing row masks incomplete current batch] → Shared latest-complete-batch validator and adversarial tests for duplicates, missing names, wrong command, timestamp spread, SHA/generation mismatch and newer failure.
- [One-shot permission is consumed but reservation/review is not linked] → PostgreSQL atomic transaction and uniqueness/CAS tests; do not claim support if current repositories cannot atomically express it.
- [Review finalizer accidentally advances general pipeline] → Isolated review-only finalization contract and E2E asserting zero APPLY/check/audit/PR side effects.
- [Post-review continuation repeats paid work or bypasses downstream gates] → Separate action request and claim/fence, exact completed-review revalidation, resume from the post-review checkpoint only, and tests asserting zero repeated CODE_REVIEW/APPLY/checks and no audit/PR/merge bypass.
- [Canonical provider policy diverges from OpenSpec instructions] → Minimal scoped wording reconciliation; `CANONICAL_DECISIONS.md` remains higher precedence.
- [Stored candidate authorship or manifest differs from physical worktree] → Verify exact live candidate/manifest/worktree identity at execution; the proposal's read-only DB observations are not a substitute.

## Migration Plan

No schema migration is planned because existing models carry action, reservation, review linkage and dispatch identity. APPLY must prove this with isolated PostgreSQL concurrency/fault-injection tests. If not proven, stop before implementation dependent on the gap and propose the minimal versioned Alembic migration within this Change. Rollback must leave the existing frozen candidate, check rows, Run/Job, action records and reservations intact; disable only the new review-only route if rollback is needed, without deleting evidence or modifying the ordinary pipeline.

## Open Questions

None that alter the contract or implementation path. Atomic authorization/reservation/review linkage is a required verification gate, not a deferred design decision; if persistence cannot support it, APPLY must remain blocked pending a minimal schema design.
