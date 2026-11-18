## 1. Align active contracts

- [x] 1.1 Validate the delta specs against the rector contract and Issue #374; reconcile every remaining active cap prerequisite in the modified capabilities.
- [x] 1.2 Validate OpenSpec artifacts and preserve the immutable historical migrations and archived changes.

## 2. Remove runtime cap authority

- [x] 2.1 Remove daily/monthly OpenRouter budget configuration, project authorization flags, policy model/repository, and policy synchronization while preserving configured provider roles and separate reviewer controls.
- [x] 2.2 Remove budget/headroom as an execution preflight and fallback-eligibility condition; for Apply, check only the assigned execution provider's capacity and dispatch the exact configured fallback profile while preserving candidate and independent-review safeguards.
- [x] 2.3 Remove obsolete budget endpoints/fields and CLI/UI cap controls; retain provider usage evidence with source/time and report missing or zero credit denominators as unknown.

## 3. Retire persistence and stale consumers

- [x] 3.1 Add a forward-only Alembic migration to remove obsolete policy persistence after all runtime consumers are gone; preserve usage/ledger evidence and historical migrations.
- [x] 3.2 Remove stale cap references from active specs, tests, configuration examples, and generated/source UI consumers without editing archived history.

## 4. Verify behavior with evidence

- [x] 4.1 Add service-level coverage proving Apply falls back when its assigned primary is quota-limited even if the reviewer provider is healthy, and that enabled OpenCode uses the exact fallback provider/model.
- [x] 4.2 Verify ineligible/new work, missing fallback configuration, reviewer independence, provider credential boundaries, missing/zero credit denominator behavior, and dashboard observation attribution.
- [x] 4.3 Run focused tests, the relevant full suite, and PostgreSQL migration/integration checks against the authorized test database; record commands, results, and database identity.
  - Evidence: focused Python tests: 20 passed; full Python suite: 1096 passed, 12 failed, 15 skipped, with the same 12 failures verified on clean `main`; frontend tests: 68 passed; `npm run build` passed with Angular/bundle-size warnings. On the server, `minime_test` migrated from `f14_provider_model_enablement` to `req374_remove_artificial_budget_caps`; verified the obsolete table and column are absent; selected PostgreSQL E2Es: 8 passed. The migration is unchanged by this correction.
- [ ] 4.4 Capture real in-flight Run evidence in the final validation batch; this remains deferred until all implementation Issues are covered.
