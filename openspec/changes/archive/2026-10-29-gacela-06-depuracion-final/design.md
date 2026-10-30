# Design

## Context

See `proposal.md` for motivation and `specs/f6-final-retirement/spec.md` for the observable contract. The current repository contains a modular FastAPI/Python application with PostgreSQL/Alembic state, native OpenSpec adapters/services, project and worktree isolation, candidate/evidence services, and a substantial historical migration chain. The static census found active-looking surfaces in `src/minime/services/`, `src/minime/adapters/`, `src/minime/local_worker/`, `alembic/versions/` and `tests/`; names alone do not establish dead code. Existing specs already govern PostgreSQL durability, repository binding, managed runtime isolation, worktree lifecycle, external-action fail-closed behavior, evidence integrity, native OpenSpec boundaries and safe retirement.

The only newly introduced contract is the F6-specific final-retirement capability. Existing capabilities remain the authorities for their boundaries; F6 must compose them rather than create a second lifecycle, evidence model, OpenSpec implementation or repository registry.

## Goals / Non-Goals

**Goals:**

- Produce a concrete census and Removal Ledger before any implementation deletion, including static, configuration and dynamic reachability evidence.
- Reuse the installed native OpenSpec propose/apply/verify/sync/archive workflows and the existing repository, worktree, PostgreSQL, migration, evidence and external-action boundaries.
- Remove only demonstrably obsolete code, tests, dependencies, flags, endpoints and schema objects in the same Change after retained behavior has passed real checks.
- Make PostgreSQL cleanup recoverable and identity-bound, preserving audit trails, candidate/worktree continuity, applied migrations and required historical evidence.
- Reconcile the exact `mini-me-fixture` identity and require a separate, explicit human authorization before any irreversible GitHub deletion.
- Repeat focused tests, regression tests and real E2E after retirement and bind evidence to the immutable candidate SHA.

**Non-Goals:**

- No F7 or F8 capability, Angular migration, new scheduler, new queue/backlog authority, deployment, or production post-deploy action.
- No custom Markdown generator/merger, semantic OpenSpec validator, archive-by-filesystem substitute, prompt replacement, or second evidence ledger service.
- No deletion of historical OpenSpec specs, archived changes, audit trails, applied migrations, legitimate jobs/claims, candidate identities, or unrelated dirty worktrees.
- No deletion of the fixture based on this proposal alone; the destructive action is a later human-gated apply operation and is not performed during planning.

## Decisions

### 1. One F6 inventory, with existing authorities reused

The implementer will inspect the actual dependency graph and classify each candidate as REUSE, MODIFY, REMOVE or RETAIN-WITH-REASON. The census covers API/CLI/UI routes, service/adapters, DI/configuration, imports and dynamic references, tests/fixtures, Alembic metadata and writers, PostgreSQL tables/columns, Git/worktrees, jobs/claims, budgets and external references. The existing `minime-safe-retirement` guidance and repository/worktree/evidence guards are reused; F6 will not add a generic cleanup subsystem.

Alternative rejected: a global grep-only cleanup, because reflection, configuration, recovery, historical evidence and durable foreign-key relationships can make an apparently unused symbol live.

### 2. Retire only after parity, then repeat proof

For each replacement, first prove the retained path with focused unit/integration checks and the applicable real E2E. Then migrate all consumers, remove the old route and exclusive protection, and repeat the checks after deletion. The final evidence records old entrypoints/writers, consumers, new authority, action and post-retirement result. If a legitimate dependency or safety concern remains, the item is retained with reason and blocks any claim of complete final cleanup.

Alternative rejected: deleting first and relying on a green test suite, because the project contract requires evidence that the old path was unreachable and that post-removal tests did not run with both paths present.

### 3. PostgreSQL changes are Alembic-only and fail closed

The implementer will derive schema candidates from SQLAlchemy metadata, Alembic history, actual writers/readers and durable retention requirements. A migration is permitted only after database identity, backup, affected-row/data retention and rollback are verified. Upgrade and downgrade/rollback are tested against an explicitly disposable database or an authorized operational rehearsal; canonical operational credentials are never inherited by destructive tests. Ambiguous identity, missing backup or missing rollback stops before mutation.

Alternative rejected: direct SQL/table dropping or automatic repair, because it bypasses versioned history, rollback and the existing PostgreSQL invariant boundary.

### 4. Fixture disposal is a distinct, exact external action

The reconciliation inventory will identify the exact repository, repository binding, worktrees, jobs/claims, budget references and tests. Historical evidence is retained in the main project without secrets. Deletion is a single exact GitHub target, authorized by a human after the census, executed through the existing external-action/fail-closed adapter, and followed by an authoritative read proving absence plus a local operational-reference scan. Timeout or ambiguous deletion never triggers blind retry.

Alternative rejected: treating an open Issue/PR or a title such as `mini-me-fixture` as authorization, and broad repository cleanup, because presentation metadata and historical objects do not authorize destructive mutation.

### 5. Evidence is native-workflow and candidate-bound

F6 orchestration records the installed skill/command invocation, stage result, candidate SHA, migration revision/database identity, E2E command and output references, and human authorization where required using existing durable records and evidence facilities. The independent reviewer is read-only and reviews the final candidate after retirement. Missing or simulated integration evidence is `NOT_VERIFIED`, `WAITING_CAPACITY`, `INCOMPLETE` or `HUMAN_REQUIRED` as appropriate, never PASS.

Alternative rejected: a new semantic verifier or a task-count completion flag, because OpenSpec remains the authority for artifacts and real execution evidence is required.

## Risks / Trade-offs

- **[Risk] A dynamic or recovery consumer is missed.** → Combine static references, configuration/DI inspection, runtime tracing of relevant retained flows and negative checks; retain with reason when uncertain.
- **[Risk] A migration removes needed historical data.** → Require row/column inventory, backup evidence, downgrade rehearsal and a pre-mutation identity check; block if any is absent.
- **[Risk] Fixture deletion has an unobservable external result.** → Use typed external outcomes and observe-before-repeat; keep the action ambiguous and require human resolution rather than retrying blindly.
- **[Risk] F6 absorbs F7/F8 or historical cleanup.** → Apply the explicit phase boundary and exact target allow-list; route any new behavior through a future authorized Change.
- **[Risk] E2E depends on the fixture being deleted.** → Prove dependency absence before deletion, run retained-path E2E before and after retirement, and preserve the fixture when any active dependency remains.

## Migration Plan

1. Native OpenSpec apply begins only after this Change is approved and the authorized candidate/worktree identity is verified.
2. Build and review the census/Removal Ledger; freeze the exact removal set and identify retained historical owners, active jobs/claims, bindings and fixture references.
3. Establish baseline checks and real E2E for retained F2–F5 behavior. Do not delete or mutate the fixture at this stage.
4. Migrate consumers and remove proven-obsolete code, tests, dependencies, flags and routes. Run the relevant checks after each bounded retirement.
5. For approved schema targets, create and exercise Alembic upgrade/downgrade with backup and database-identity evidence. Abort without mutation on any failed precondition.
6. Reconcile `mini-me-fixture`. If and only if the exact dependency census is clear and human authorization is recorded, execute the one exact GitHub deletion and verify absence. Otherwise preserve it and record the blocker.
7. Run full post-retirement regression and real E2E, independent read-only review and native verify against the final candidate SHA. Preserve evidence in the project without credentials.
8. Later, after the implementation PR has the required merge authorization, use a fresh main-based branch for native sync/archive and documentary closure. F6 does not deploy; CI/CD owns deployment.

Rollback is code-revert plus Alembic downgrade only where the migration has a tested downgrade and the database identity is authorized. Restore preserved data from the verified backup when required. A deleted GitHub repository is irreversible in this Change: the precondition and human authorization gate must be satisfied before deletion; if not, the repository remains intact. No rollback claim is made for an unobservable external action.

## Open Questions

- The exact human authorization record and backup destination/encryption mechanism remain deployment/operator decisions already listed in `docs/PENDING_DECISIONS.md`; apply must stop until they are supplied for any destructive operation. This does not change the F6 specification or the non-destructive planning work.
