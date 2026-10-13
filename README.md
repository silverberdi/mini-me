# mini me — canonical implementation context

`mini me` is a personal, single-installation **control plane for AI agents using native OpenSpec workflows** across software repositories. It coordinates GitHub needs, agent-led OpenSpec proposals and changes, assigns Codex/Antigravity by stage with independent review, enforces deterministic and real E2E checks, survives interruptions/quotas, and automates PR/deployment/closure mechanics around human merge. It **never programs or semantically generates/merges/archives OpenSpec artifacts instead of the agents**. DeepSeek/OpenRouter are opt-in compatible fallback only after both primary agents cannot serve a stage.

## Canonical reading order
1. `docs/BUSINESS_INTENT.md`
2. `docs/CANONICAL_DECISIONS.md`
3. `docs/PRODUCT.md`
4. `docs/ENGINEERING_DISCIPLINE.md`
5. `docs/CHANGE_DELIVERY_CONTRACT.md`
6. `docs/agent-capabilities/V1_MANIFEST.md` (and linked hook/harness/retirement contracts)
7. `docs/ARCHITECTURE.md`
6. `docs/PROVIDER_POLICY.md`
7. `docs/DOR_DOD.md`
8. `docs/ROADMAP.md` and `docs/BACKLOG.md`
9. `docs/backlog/MM-Rxx.md` for the one authorized value increment
10. `docs/AGENT_CONTRACTS.md` and `openspec/config.yaml`
11. single active change under `openspec/changes/`

## Source-of-truth boundaries
- **GitHub Projects / Issues:** work portfolio, visible planning and progress.
- **OpenSpec:** behavior contract, design intent and implementation tasks for a change.
- **PostgreSQL:** durable operational state, attempts, events, evidence, provider state, decisions and metrics.
- **Git:** code, branches, commits, worktrees, diffs and PR candidate identity.
- **Project config:** execution/deployment/provider policy.
- **Host secret files/environment:** credentials; never the repository.

## Primary path
`GitHub need / READY OpenSpec → agent-side propose/update (when needed) → safe preflight → native agent apply → checks/native verify → complementary independent review → real E2E → draft PR → human merge → native OpenSpec sync/archive with Git authority → authorized deployment + functional postdeploy E2E → GitHub closure → DONE`

## Important constraint
Only **one explicitly authorized OpenSpec change** is active at a time. The ten MM-R01–MM-R10 backlog dossiers are planning contracts, **not** ten active `openspec/changes/` directories. Do not start change apply by copying their text into prompts; use the actual agent-side OpenSpec workflow.
