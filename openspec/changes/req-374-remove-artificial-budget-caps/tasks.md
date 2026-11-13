## 1. Align active contracts

- [x] 1.1 Validate the delta specs against the rector contract and Issue #374; reconcile every remaining active cap prerequisite in the modified capabilities.
- [x] 1.2 Validate OpenSpec artifacts and preserve the immutable historical migrations and archived changes.

## 2. Remove runtime cap authority

- [x] 2.1 Remove daily/monthly OpenRouter budget configuration, project authorization flags, policy model/repository, and policy synchronization while preserving configured provider roles and separate reviewer controls.
- [x] 2.2 Remove budget/headroom as an execution preflight and fallback-eligibility condition; preserve in-flight, verified-provider-capacity, role, candidate, and review safeguards.
- [x] 2.3 Remove obsolete budget endpoints/fields and CLI/UI cap controls; retain only accurately sourced provider usage evidence.

## 3. Retire persistence and stale consumers

- [x] 3.1 Add a forward-only Alembic migration to remove obsolete policy persistence after all runtime consumers are gone; preserve usage/ledger evidence and historical migrations.
- [x] 3.2 Remove stale cap references from active specs, tests, configuration examples, and generated/source UI consumers without editing archived history.

## 4. Verify behavior with evidence

- [x] 4.1 Add service-level coverage proving provider preflight dispatch eligibility no longer depends on a legacy policy row or cap and provider-native rejection remains truthfully surfaced.
- [x] 4.2 Verify ineligible/new work, missing fallback configuration, reviewer independence, and provider credential boundaries remain enforced.
- [x] 4.3 Run focused tests, the relevant full suite, and PostgreSQL migration/integration checks against the authorized test database; record commands, results, and database identity.
  - Evidence: focused Python tests 121 passed; provider-boundary regressions 12 passed; full suite 1091 passed, 12 pre-existing failures, 15 skipped (the same 12 fail on clean `main`). On the server, migrated the dedicated `minime_test` database from `f14_provider_model_enablement` to `req374_remove_artificial_budget_caps`; verified the old policy table and project authorization column are absent; PostgreSQL E2E selection: 8 passed. Frontend build and 67 frontend tests passed locally.
- [ ] 4.4 Capture real in-flight Run evidence in the final validation batch; this remains deferred until all implementation Issues are covered.
