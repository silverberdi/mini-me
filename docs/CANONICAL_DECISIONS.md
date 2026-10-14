# Canonical Decisions

These decisions supersede the previous AgentFlow context pack.

## Effective product delivery contract (2026-10-13)
- Governing details for the recovery backlog: [BACKLOG](BACKLOG.md), [ROADMAP](ROADMAP.md), [CHANGE_DELIVERY_CONTRACT](CHANGE_DELIVERY_CONTRACT.md) and its 10 vertical MM-R01–MM-R10 dossiers. Historical delivery claims are not accepted E2E proof.
- mini me is **control plane**, not the author/implementer of OpenSpec planning or application. Codex/Antigravity operate native OpenSpec agent workflows: propose, update, continue when installed, apply, verify when installed, sync, archive. Do not replace these with Python templates, custom prompt-driven implementations or custom semantic merges.
- Every Change bundles all required specs to deliver real, deployed, E2E-demonstrated user/operator value. Unit/integration PASS alone cannot close a Change; retain fail-closed human merge and explicit permission for agent inference. No auto-merge.
- These decisions override older requirements making a DeepSeek audit mandatory or assigning immutable Codex/Antigravity roles across all stages. DeepSeek/OpenRouter are authorized fallback **only after both primaries cannot supply the stage**, and only with explicit per-stage provider/budget approval and capability verification. A subscription provider may author or review different stages, but not authoritatively review its own substantive candidate. For R01 only, DeepSeek Direct may serve as a distinct read-only authoritative reviewer when no eligible primary reviewer can serve and a separate candidate-bound structured review contract, complete input, reviewer independence, deterministic validation, and explicit stage/budget authorization are all verified. Audit output is never review evidence. A valid review does not authorize merge/closure/deployment; human merge remains mandatory.
- No automatic scheduler re-enablement, quota consumption, GitHub Issue mass closure or production migrations when approving backlog documents.

## Identity and installation
- Product name: **mini me**.
- Technical naming: repo `mini-me`, Python package/CLI namespace `minime` unless an implementation constraint requires otherwise.
- Personal, non-commercial, single installation.
- Runtime is a long-lived Linux service. Mac/phone/tablet are operator/development clients, not runtime dependencies.

## Stack and persistence
- Python 3.12+.
- FastAPI API boundary; Pydantic v2 models.
- PostgreSQL only for operational persistence.
- SQLAlchemy 2.x + Alembic migrations.
- Async subprocess execution for local CLIs.
- pytest for tests; Ruff for linting. Static typing should be enforced where practical.
- TUI later in MVP using Textual; future PWA consumes the same API.

## Work management and GitHub
- One global GitHub Project under the owner's personal GitHub account.
- Issues remain in their corresponding repositories.
- GitHub App is the target runtime integration with minimum per-repository permissions.
- GitHub Project presentation data never authorizes repository selection.
- Executable identity is a durable binding: `project_id ↔ repository ↔ GitHub issue ↔ OpenSpec change`.
- Every executable OpenSpec change ends in a PR.
- Human merge is mandatory in MVP.

## Agent roles
- Normal path: Codex and Antigravity alternate proposer, implementer, verifier and independent reviewer **by stage**, respecting project policy and resource budgets; the implementer and authoritative reviewer for a given candidate must differ.
- Primary provider preference (e.g. Codex workhorse / Antigravity premium) is configurable per project/stage, not a permanent agent identity or ban across all workflows.
- Bounded Premium Recovery (`PREMIUM_RECOVERY_NON_CONVERGENCE`): When material candidate progress exists but the primary executor exhibits non-convergence (repeated malformed results, failing checks, retries/reassignments exhausted), Antigravity may be engaged for a strictly bounded recovery attempt (max 1 attempt per failure episode; anti-ping-pong enforced).
- Reviewer independence: The same primary agent / model identity cannot implement and review the same candidate. If Antigravity performs recovery implementation, Antigravity must NOT review that candidate; review role must reassign to Codex or an independent model.
- DeepSeek Direct: optional explicitly authorized read-only analysis/fallback, not a mandatory audit before every PR. Under R01's narrow conditional exception, it may provide authoritative review only when no eligible primary reviewer is available and the separate, compatible, candidate-bound, structured, deterministic, independently authored, explicitly budget-authorized reviewer contract is satisfied; audit evidence cannot be converted to review, and human merge remains mandatory.
- Qwen local: optional advisory helper only.
- OpenRouter: optional paid alternative only after dual-primary exhaustion and explicit authorization, subject to actual agent/tool capabilities and budget.
- In OpenRouter drain fallback, substantive implementer model and authoritative reviewer model must differ. Qwen does not review Qwen.
- Human Gate Semantics: `NEEDS_HUMAN` is reserved strictly for genuine human-only decisions (product ambiguity, credentials/secrets, irreversible operator decisions, merge gates, business policy decisions). Deterministic executor recovery and non-convergence must use machine-operable state/reason semantics (`EXECUTOR_RECOVERY_REQUIRED`, `WAITING_CAPACITY`) without triggering false human gates.

## Capacity policy
- When both primary subscription agents are exhausted, scheduler stops admitting new READY changes.
- Scheduler enters DRAIN; an explicitly authorized compatible DeepSeek/OpenRouter alternative may serve eligible in-flight stages only when budget, independence and tools support the requested role. Otherwise wait.
- When no drainable work remains, scheduler waits for primary capacity recovery.
- Provider reset time should use provider signals when available; do not assume midnight without evidence.

## UI validation and deployment
- Human validation is for UI behavior, not services in isolation.
- Services/APIs are validated automatically unless needed as dependencies of an integrated UI preview.
- UI changes requiring human validation must state exactly what to test, how to test it and expected outcomes.
- Preview deployments are containerized.
- Preview UI port/endpoint is configured per project.
- Preview must never use production data stores unintentionally.
- Human validation is bound to candidate head SHA + base SHA and deployed image digest when applicable.
- Stale validation invalidation is mandatory: any change to head SHA, base SHA, or image digest invalidates prior validation authority for that candidate.
- Production should promote the validated immutable container artifact when technically valid.
- Production deployment occurs only after human merge and project policy authorization.

## Canonical operating model
The canonical future operator workflow is strictly:

```text
Product intent / roadmap
        ↓
GitHub Project + Issue
        ↓
OpenSpec contract
        ↓
mini me Run / Job
        ↓
Candidate
        ↓
Checks
        ↓
Complementary Review
        ↓
Independent agent review / authorized optional audit
        ↓
Preview / Guided Validation (when required)
        ↓
Pull Request
        ↓
Merge gate
        ↓
Archive / cleanup
```

All planning and code changes must be executed through the proper **agent-side OpenSpec workflow**, not an emulation by the mini me daemon. The daemon handles durable authority, tools, sandbox, quotas, lifecycle and evidence.

The operator SHOULD NOT manually create:
- worktrees;
- candidate branches;
- OpenSpec changes;
- orchestration DB records;
- manifests;
- review records;
- audit records.

These are internal mini me responsibilities. The TUI and operational interfaces serve to observe, navigate, and interact with canonical services and read models, not to bypass or replace autonomous lifecycle guarantees.

## Canonical roadmap sequencing (013 – 018)
- The canonical delivery sequence is strictly:
  `013-container-preview-guided-validation` ->
  `014-tui-operator-console` ->
  `015-operator-actions-control-plane` ->
  `016-autonomous-queue-work-selection` ->
  `017-pwa-control-center` ->
  `018-end-to-end-self-operating-loop`.
- Scope boundaries must be strictly enforced:
  - 013 MUST NOT expand into the full operator control plane, TUI, or PWA.
  - 014 (TUI) precedes 015 (control plane) and 017 (PWA).
  - 016 (autonomous queue/work selection) precedes full self-operating loop in 018.

## Safety and closure
- Secrets live outside the repo under host-controlled configuration, e.g. `/etc/minime/`.
- Daemon never runs with provisioning/admin DB credentials.
- No silent paid escalation.
- No autonomous merge.
- `DONE` means full operational closure, not merely merged code.

