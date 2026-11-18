# CODE_REVIEW gate recovery evidence — 2026-10-21

## Read-only production root reproduction

- Production application SHA observed: `a41b59a145b3d5d7d8d55ad325a361970669de0f`.
- Inspection ran as service identity `minime` from `/opt/minime/app`; API was active and scheduler inactive.
- Run/Job/Candidate inspected: `8e7ebec8-9eff-478b-bae3-cf686ea91be2` / `b917a9f0-0354-4805-863f-7ab4e7ada559` / `2fcad0ef73eb4766ca1bb6249a081cb4070ecced`.
- The durable `ProjectManagedRepositoryBinding` selected `/opt/minime/repos/mini-me-r01-e2e-20261014` as the managed repository root. The worktree itself remained at the binding-derived Job path.
- With `WorktreeManager.project_root=/opt/minime/app`, `_verify_frozen_candidate_worktree_adoption` raised `RuntimeError: Refusing to adopt existing frozen candidate worktree at [redacted worktree path]: Path [redacted worktree path] is not present in git worktree list.`
- Repeating the same proof with `WorktreeManager.project_root` set to the exact validated binding root returned `BOUND_ROOT_PROOF=PASS`.
- Database access used a read-only transaction and was rolled back. No Run, Job, authorization, worktree, service, provider, or scheduler state was changed.

## Isolated regression evidence

- PostgreSQL: disposable local PostgreSQL 16 database `minime_contract_review_test`, migrated through `r02_contract_review_budget_identity`.
- Git: real temporary managed repository and registered Job worktree; candidate HEAD remained equal to the frozen candidate SHA and the worktree remained clean after the positive review path.
- Entry points: `minime action execute` and the Control Plane API action endpoint both entered the same binding-root resolution while the service process root was unrelated to the managed repository. A contradictory project/binding identity was rejected.
- Authorization: the expired prior record and its payload remained unchanged. Renewal succeeded only for the exact expired-unused candidate authorization. Unexpired authorization, a persisted reservation, an external dispatch row, an ambiguous execute action, or a persisted review denied renewal. The aggregate-budget test confirms only the proven expired-unused ceiling is excluded.
- Provider calls: all HTTP was handled by an in-process `httpx.MockTransport`; no real DeepSeek request or inference occurred.
- Results: the five parameterized PostgreSQL/Git scenarios passed. Adjacent Control Plane, API, CODE_REVIEW service, and worktree/runner suites passed `87/87` with an isolated temporary `MINIME_RUNTIME_ROOT`. Ruff check/format, strict OpenSpec validation, and `git diff --check` passed.
- Protected N01 state, production PostgreSQL, and scheduler were not modified.
