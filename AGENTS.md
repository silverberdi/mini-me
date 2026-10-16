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
- Codex and Antigravity are the primary planning/execution providers and may plan or execute stages selected by the validated per-stage profile. A compatible, authorized handoff between them must preserve durable Run/Job/worktree identity, checkpoints and fencing, and reconcile external effects before retry. The substantive author must not authoritatively review the same candidate.
- In OpenRouter drain fallback, the same **model identity** must not perform substantive implementation and authoritative review of that candidate.
- DeepSeek Direct is mini me's independent reviewer for separate read-only CONTRACT REVIEW and code REVIEW stages. It uses only its own official API/account, fresh balance/capacity evidence and the applicable owner-configured spending policy; it never plans, implements, rescues work, or substitutes one review stage for the other. A review cannot authorize APPLY, product decisions or merge. If a required review is unavailable or disallowed by policy, preserve the work and wait. Record provider-reported usage and retain unknown settlement as unresolved exposure. Never route `DEEPSEEK_API_KEY` through OpenRouter or count text-only API output as coding-tool execution.
- OpenRouter is exceptional rescue only for previously started work that must be completed when both Codex and Antigravity are blocked by quota. It is not a primary executor or reviewer, must not start new READY work, and must not bypass security, integrity, compatibility, applicable owner spending policy or review gates. Require its own account and capacity evidence; ordinary dispatch follows the configured owner policy without a new per-call approval.
- No agent may merge. Human merge is mandatory in MVP.
- No agent may raise budgets, weaken provider/security policy, change secrets, change repo binding, or silently bypass human validation.
- Provider capacity/balance evidence, owner-configured spending policy and usage accounting are separate responsibilities. Capacity or positive balance alone does not override policy or guarantee unlimited coverage. Ordinary operations need no per-call human approval when the owner's policy permits them; optional limits remain enforceable. Record provider-reported usage durably and idempotently, preserving unresolved exposure rather than inventing a settlement. Keep provider identity, protected account, model, stage, Run/Job and billing origin distinct; provider adapters use only their own accounts and billing sources.
- PostgreSQL is the only supported operational database. Schema evolution uses versioned Alembic migrations; no ad-hoc DDL lifecycle.
- TUI/future PWA are clients of the daemon/API. Orchestration lives in core/daemon.
- UI-affecting changes marked for human validation must provide a runnable containerized preview plus explicit validation scenarios.
- Human approval is bound to the candidate identity (head SHA + base SHA, and immutable image digest when deployed). Stale validation must not be silently reused.
- Deterministic evidence beats agent self-claims.
- Every completed OpenSpec task requires verifiable evidence, plus stage E2E, complete-value E2E and postdeploy functional E2E for Change acceptance. An agent's own PASS claim is not evidence.
- **Engineering Removal Gate:** inventory current implementation/callers, reuse existing code/capabilities, and retire superseded implementations within the same Change after E2E parity; migrate references, rerun tests/E2E **after removal**, preserve history and obtain explicit human approval for justified exceptions.
- **Prebuilt Capability Pack:** use the seed skills `minime-engineering-discipline`, `minime-safe-retirement`, `minime-real-e2e-proof`, the existing canonical/scope/repository guards, documented harness/hooks baseline and native OpenSpec commands. Do not invent replacements from scratch; verify any proposed variation with OpenSpec update and E2E. PR #140 hooks are pending, not installed by fiat.

## Git safety
Never change `origin`, the registered repository, assigned base branch, or assigned worktree. Before push/PR, revalidate repository identity and candidate SHA.

## Closure
`APPROVED`, `MERGED`, and `DEPLOYED` are not `DONE`. The Definition of Done in `docs/DOR_DOD.md` is authoritative.
