# mini me — agent instructions

Read `README.md`, `docs/BUSINESS_INTENT.md`, `docs/CANONICAL_DECISIONS.md`, `docs/PRODUCT.md`, **`docs/ENGINEERING_DISCIPLINE.md`**, `docs/CHANGE_DELIVERY_CONTRACT.md`, `docs/BACKLOG.md`, `docs/ARCHITECTURE.md`, `docs/UX.md`, `docs/DOR_DOD.md`, `docs/AGENT_CONTRACTS.md`, `docs/agent-capabilities/V1_MANIFEST.md` and its contracts, the MM-Rxx dossier of the change (if applicable), and the single active folder under `openspec/changes/` before changing code.

## Non-negotiable rules
- Implement only the active OpenSpec change. Do not implement future roadmap work opportunistically.
- **AI agents using native installed OpenSpec workflows** propose/update/continue/apply/verify/sync/archive; mini me orchestrates. Never replace these workflows with deterministic mini me-authored Markdown/implementation generators, ad hoc LLM prompts, custom semantic spec merges or custom archive emulator.
- A change must deliver independently usable vertical value and include all applicable backend/DB/UI/security/agent capabilities and real E2E scenarios. Unit/integration PASS is not E2E; health checks alone are not postdeploy verification.
- At every propose/apply/verify gate, test for architecture/product drift against Business Intent and canonical decisions; block contradictions and require OpenSpec update rather than silently accepting drift.
- OpenSpec specs define observable behavior; `design.md` defines change-specific architectural decisions.
- If ambiguity can materially change behavior, security, cost, architecture, repository identity, deployment behavior or scope: stop and surface it. Do not guess.
- Repository/workspace selection comes only from validated durable project binding, never from issue titles, labels, Project fields or prose.
- Codex and Antigravity are complementary: the same primary agent must not implement and review the same candidate.
- In OpenRouter drain fallback, the same **model identity** must not perform substantive implementation and authoritative review of that candidate.
- DeepSeek Direct is not a mandatory auditor; it may be used only as explicitly authorized compatible fallback after both primary subscription agents cannot serve the stage. Never route `DEEPSEEK_API_KEY` through OpenRouter or count text-only API output as coding-agent tool execution.
- OpenRouter is an explicitly operator-authorized and budgeted fallback only after both subscription primaries cannot serve the required stage, subject to real tool/workflow capability; it must not start new READY work just because budget exists.
- No agent may merge. Human merge is mandatory in MVP.
- No agent may raise budgets, weaken provider/security policy, change secrets, change repo binding, or silently bypass human validation.
- PostgreSQL is the only supported operational database. Schema evolution uses versioned Alembic migrations; no ad-hoc DDL lifecycle.
- TUI/future PWA are clients of the daemon/API. Orchestration lives in core/daemon.
- UI-affecting changes marked for human validation must provide a runnable containerized preview plus explicit validation scenarios.
- Human approval is bound to the candidate identity (head SHA + base SHA, and immutable image digest when deployed). Stale validation must not be silently reused.
- Deterministic evidence beats agent self-claims.
- Every completed OpenSpec task requires verifiable evidence, plus stage E2E, complete-value E2E and postdeploy functional E2E for Change acceptance. An agent's own PASS claim is not evidence.

## Git safety
Never change `origin`, the registered repository, assigned base branch, or assigned worktree. Before push/PR, revalidate repository identity and candidate SHA.

## Closure
`APPROVED`, `MERGED`, and `DEPLOYED` are not `DONE`. The Definition of Done in `docs/DOR_DOD.md` is authoritative.
