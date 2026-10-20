## 1. Contract and authority alignment

- [ ] 1.1 Map each FCR-01–09 and E01–12 to the existing Control Plane, recovery, candidate, review, budget, and status authorities; record concrete call sites and test consumers without changing implementation outside this Change.
- [ ] 1.2 Reconcile only the conflicting DeepSeek Direct reviewer wording in `openspec/config.yaml` and `docs/CHANGE_DELIVERY_CONTRACT.md` with `docs/CANONICAL_DECISIONS.md` and `AGENTS.md`; verify no provider role or ordinary spending policy changes.
- [ ] 1.3 Confirm disposable PostgreSQL schema and repositories can atomically bind one-shot action, unique reservation, review checkpoint, and fenced dispatch intent; if they cannot, design the minimum versioned Alembic migration before dependent implementation.

## 2. Readiness and review-only lifecycle

- [ ] 2.1 Implement one shared latest-complete-check-batch validator and use it for exceptional CODE_REVIEW action discovery, action execution, and reviewer preflight; require exact configured checks/commands, uniqueness, time window, candidate SHA/generation, and pass status.
- [ ] 2.2 Add the canonical review-only continuation branch under the existing Run claim, one heartbeat owner, fencing, and RecoveryDecision/checkpoint; ensure generic CONTINUE rejects `REVIEW_AUTHORIZATION_PENDING` before any Run/Job/attempt mutation.
- [ ] 2.3 Consume and link the exceptional one-shot authorization to exactly one direct DeepSeek reservation and candidate-bound Review before dispatch, enforcing account/model/effort/price/expiry/maximum and existing spending policy.
- [ ] 2.4 Persist an at-most-one fenced dispatch intent before provider I/O and fail closed as AMBIGUOUS on uncertain post-dispatch outcomes; never blindly retry a possibly billed request.
- [ ] 2.5 Finalize valid verdicts through only the safe existing integrity, fencing, spend reconciliation, review status, metrics, and event collaborators; stop N01 at its human gate and preserve ordinary autonomous next-stage behavior.
- [ ] 2.6 Keep API/status projections truthful about current versus historical checks, exact candidate/review identity, authorization/dispatch state, and human gate without deleting or rewriting historical evidence.

## 3. Adversarial and operational verification

- [ ] 3.1 Add E01 PostgreSQL + real Git/worktree integration proving latest complete passing batch wins over an unchanged historical failure, one intercepted DeepSeek call yields a durable candidate-bound review, and no APPLY/checks/audit/PR side effects occur.
- [ ] 3.2 Add E02/E04/E05/E09 denial coverage for invalid or expired authorization, missing/partial/duplicate/wrong-command/current-failed checks, empty check configuration, mismatched candidate/binding/worktree/manifest, and wrong provider/account/model/effort/price/budget; assert zero provider calls.
- [ ] 3.3 Add E06 claim/fence/concurrency/crash/timeout tests proving at-most-one dispatch intent, no stale-owner mutation, and no blind repeated HTTP after ambiguity.
- [ ] 3.4 Add E07/E08 tests for durable READY_TO_MERGE and CHANGES_REQUIRED verdicts, N01 pilot stop, preserved candidate, and no automatic remediation/audit/PR/merge.
- [ ] 3.5 Add E10 regression proving generic CONTINUE cannot rewrite a review-authorized hold to IMPLEMENTING or alter Job/Run/attempt/candidate/check evidence.
- [ ] 3.6 Add E11 ordinary autonomous-flow regression proving the exceptional one-shot path did not introduce per-review human approval or break existing recovery/continuation.
- [ ] 3.7 Add E03 status/projection test proving the latest passing batch is current while the historical failed check remains unchanged and visible.

## 4. Retirement and release evidence

- [ ] 4.1 Inventory every caller of the weaker `any passing row` predicate and any duplicate current-check selector or exceptional route into the general execution pipeline; record the disposition in the design Removal Ledger.
- [ ] 4.2 After parity E2E passes, remove only proven superseded predicates/dispatch paths, migrate all callers, and rerun the affected unit, PostgreSQL/Git, Control Plane, review, recovery, and ordinary-flow regressions after removal.
- [ ] 4.3 Run one consolidated disposable PostgreSQL + Git stage E2E for frozen-candidate review-only continuation, including denial/fault injection and N01 evidence non-mutation; distinguish intercepted-provider evidence from actual paid-provider E2E.
- [ ] 4.4 Verify no schema migration was needed, or validate the narrowly justified Alembic upgrade/rollback against disposable PostgreSQL; never stamp or mutate production schema.
- [ ] 4.5 Prepare a separately gated post-deployment N01 verification procedure; execute it only after deployment and new explicit authorization, and never include it in proposal, ordinary CI, or implementation tests.
- [ ] 4.6 Complete OpenSpec strict validation, focused/full relevant regressions, Ruff, diff checks, and an evidence-based task trace; keep human review, merge, deployment, and post-deployment verification open until their actual authorities run.
