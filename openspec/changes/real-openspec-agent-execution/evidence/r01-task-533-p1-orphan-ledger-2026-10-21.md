# R01 task 5.3.3 P1 — orphaned direct CODE_REVIEW usage

## Scope and environment

- Change: `real-openspec-agent-execution`, task 5.3.3 only.
- Branch: isolated PR #168 worktree `codex/r01-task-533b`.
- PostgreSQL: disposable PostgreSQL 16 container `minime-r01-e2e-pg-20261014`, database `minime_r01_terminal_code_review_test`, Alembic head `r02_contract_review_budget_identity`.
- Git: real temporary managed repository and Job worktree created by the integration test.
- Provider: DeepSeek HTTP requests were intercepted in-process; no real provider call or inference occurred.

## Acceptance evidence

The PostgreSQL/Git parameter case `terminal-recovery-length` now creates a direct DeepSeek `REVIEW` / `USAGE` ledger row with `reservation_id=NULL` for the exact project and Job, without a Review. The shared identity audit cannot associate it with a terminal Review and therefore:

- Reconciliation returns `UNRESOLVED_OR_AMBIGUOUS`, not `NO_PRIOR_REVIEW`.
- The expired authorization is not classified as expired-unused; its USD 0.05 ceiling remains in cumulative authorized exposure (USD 0.55 including the USD 0.50 contract-review grant).
- Action discovery disables `AUTHORIZE_DEEPSEEK_CODE_REVIEW` and the public Control Plane authorization action is rejected before any HTTP review dispatch.
- Budget exposure includes the orphaned actual ledger amount in REVIEW and combined totals without assigning it to a grant.

The same test then removes the orphaned row and creates a distinct terminal Review operation whose deterministic ledger `entry_id` is derived from that Review ID and whose project, Job, Run, candidate, manifest, provider, account, model, stage, and completed authorization agree. It is attributed to that distinct operation independent of timestamps; it does not become a false positive against the expired authorization. Its ledger amount is counted exactly once in financial totals.

## Validation

- Focused adversarial PostgreSQL/Git case: `1 passed` after the final financial-total assertion.
- Consolidated affected PostgreSQL/Git, code-review service, and Control Plane suites: `86 passed`.
- No production database, N01 data/worktree, scheduler, candidate, or provider credentials were touched.
