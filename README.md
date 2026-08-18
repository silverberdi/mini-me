# mini me — canonical implementation context

`mini me` is a personal, single-installation orchestration system for spec-driven software development. It coordinates OpenSpec-ready work across repositories, uses Codex and Antigravity as complementary implementer/reviewer agents, runs deterministic checks, adds an independent DeepSeek Direct audit, presents UI candidates for guided human validation when required, and automates the mechanical GitHub/deployment/closure work around the human gates.

## Canonical reading order
1. `docs/BUSINESS_INTENT.md`
2. `docs/PRODUCT.md`
3. `docs/CANONICAL_DECISIONS.md`
4. `docs/ARCHITECTURE.md`
5. `docs/STATE_MACHINE.md`
6. `docs/PROVIDER_POLICY.md`
7. `docs/GITHUB_WORK_MANAGEMENT.md`
8. `docs/DEPLOYMENT_AND_VALIDATION.md`
9. `docs/DOR_DOD.md`
10. `docs/ROADMAP.md`
11. `docs/BACKLOG.md`
12. `docs/AGENT_CONTRACTS.md`
13. active change under `openspec/changes/`

## Source-of-truth boundaries
- **GitHub Projects / Issues:** work portfolio, visible planning and progress.
- **OpenSpec:** behavior contract, design intent and implementation tasks for a change.
- **PostgreSQL:** durable operational state, attempts, events, evidence, provider state, decisions and metrics.
- **Git:** code, branches, commits, worktrees, diffs and PR candidate identity.
- **Project config:** execution/deployment/provider policy.
- **Host secret files/environment:** credentials; never the repository.

## Primary path
`READY → implementation → checks → complementary review → bounded corrections → final checks → DeepSeek audit → UI preview when required → guided human validation/review → draft PR ready → human merge → production deployment/verification → OpenSpec/GitHub closure → DONE`

## Important constraint
Only `openspec/changes/001-foundation/` is scaffolded as active work. Future roadmap stages are intentionally **not** pre-created as active OpenSpec changes. This prevents agents from implementing future stages early.
