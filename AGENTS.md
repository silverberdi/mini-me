# mini me — agent instructions

Read `README.md`, `docs/CANONICAL_DECISIONS.md`, `docs/ARCHITECTURE.md`, `docs/DOR_DOD.md`, `docs/AGENT_CONTRACTS.md`, and the single active folder under `openspec/changes/` before changing code.

## Non-negotiable rules
- Implement only the active OpenSpec change. Do not implement future roadmap work opportunistically.
- OpenSpec specs define observable behavior; `design.md` defines change-specific architectural decisions.
- If ambiguity can materially change behavior, security, cost, architecture, repository identity, deployment behavior or scope: stop and surface it. Do not guess.
- Repository/workspace selection comes only from validated durable project binding, never from issue titles, labels, Project fields or prose.
- Codex and Antigravity are complementary: the same primary agent must not implement and review the same candidate.
- In OpenRouter drain fallback, the same **model identity** must not perform substantive implementation and authoritative review of that candidate.
- DeepSeek Direct is a read-only auditor. Never route `DEEPSEEK_API_KEY` through OpenRouter.
- OpenRouter is drain-only paid fallback: it may finish eligible work already in flight when both subscription primaries are exhausted; it must not start new READY changes in that condition.
- No agent may merge. Human merge is mandatory in MVP.
- No agent may raise budgets, weaken provider/security policy, change secrets, change repo binding, or silently bypass human validation.
- PostgreSQL is the only supported operational database. Schema evolution uses versioned Alembic migrations; no ad-hoc DDL lifecycle.
- TUI/future PWA are clients of the daemon/API. Orchestration lives in core/daemon.
- UI-affecting changes marked for human validation must provide a runnable containerized preview plus explicit validation scenarios.
- Human approval is bound to the candidate identity (head SHA + base SHA, and immutable image digest when deployed). Stale validation must not be silently reused.
- Deterministic evidence beats agent self-claims.
- Every completed OpenSpec task requires verifiable evidence.

## Git safety
Never change `origin`, the registered repository, assigned base branch, or assigned worktree. Before push/PR, revalidate repository identity and candidate SHA.

## Closure
`APPROVED`, `MERGED`, and `DEPLOYED` are not `DONE`. The Definition of Done in `docs/DOR_DOD.md` is authoritative.
