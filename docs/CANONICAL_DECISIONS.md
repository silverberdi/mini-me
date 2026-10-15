# Canonical Decisions

These decisions supersede the previous AgentFlow context pack.

## Effective product delivery contract (2026-10-13)
- Governing details for the recovery backlog: [BACKLOG](BACKLOG.md), [ROADMAP](ROADMAP.md), [CHANGE_DELIVERY_CONTRACT](CHANGE_DELIVERY_CONTRACT.md) and its 10 vertical MM-R01–MM-R10 dossiers. Historical delivery claims are not accepted E2E proof.
- mini me is **control plane**, not the author/implementer of OpenSpec planning or application. Codex/Antigravity operate native OpenSpec agent workflows: propose, update, continue when installed, apply, verify when installed, sync, archive. Do not replace these with Python templates, custom prompt-driven implementations or custom semantic merges.
- Every Change bundles all required specs to deliver real, deployed, E2E-demonstrated user/operator value. Unit/integration PASS alone cannot close a Change; retain fail-closed human merge and explicit permission for agent inference. No auto-merge.
- Codex and Antigravity are the primary planning and execution providers. Their provider/model/effort profiles are independently configured by stage and resolved from fresh account/CLI capability, identity, capacity, cost and budget evidence; either may hand off compatible work to the other while preserving durable Run/Job/worktree identity, checkpoints, fencing and idempotent external effects. A substantive author cannot authoritatively review the same candidate.
- DeepSeek Direct is the independent reviewer for two separate read-only stages: CONTRACT REVIEW of the OpenSpec contract and code REVIEW of the exact frozen candidate. It uses only its own official API, account, capacity/balance and budget authority. The review stages have separate inputs, records and gates; one cannot substitute for the other. Review findings never authorize APPLY, product decisions, merge, closure or deployment. If a required review cannot be performed with verified compatibility, identity, capacity and explicit budget, preserve and wait. Audit output is never review evidence.
- OpenRouter is exceptional rescue only for previously started work that must finish when both primary providers are blocked by quota. It is not a primary executor or reviewer and cannot start new READY work or bypass any security, identity, authorization, compatibility, budget or review gate. Its account, credits, limits, pricing and reservations are distinct from DeepSeek Direct.
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
- Normal path: Codex and Antigravity plan and execute compatible stages selected by validated per-stage profiles; neither has a fixed lifetime role. DeepSeek Direct is the independent reviewer for the separately gated contract and code review stages. The implementer and reviewer for a given candidate must differ.
- Provider, model, and effort preference are independently configurable for each project stage; a configured profile is only a request and must be validated against the installed provider CLI/version, supported model catalog, supported effort controls, workflow/tool capability, authorization, current capacity, and stage budget before dispatch. Start with the least-cost profile that meets the documented complexity/risk and workflow requirements. Premium models and maximum effort are never defaults. Any escalation requires objective evidence, a recorded justification, a bounded retry/effort limit, and explicit budget authorization. Do not infer CLI compatibility from another provider or version.
- R01 configures Codex and Antigravity per stage according to actual CLI/workflow capability, effort, capacity and budget; either may plan or execute compatible work and may hand off durably to the other. DeepSeek Direct performs both read-only CONTRACT REVIEW and independent candidate-bound code REVIEW as distinct stages, only with its own compatible API/account, capacity and explicit budget authorization. If either required review is unavailable, preserve and wait; no review authorizes APPLY, product decisions or merge.
- Bounded Premium Recovery (`PREMIUM_RECOVERY_NON_CONVERGENCE`): When material candidate progress exists but the primary executor exhibits non-convergence (repeated malformed results, failing checks, retries/reassignments exhausted), Antigravity may be engaged for a strictly bounded recovery attempt (max 1 attempt per failure episode; anti-ping-pong enforced).
- Reviewer independence: The same primary agent / model identity cannot implement and review the same candidate. If Antigravity performs recovery implementation, Antigravity must NOT review that candidate; review role must reassign to Codex or an independent model.
- DeepSeek Direct: paid and never implicitly invoked; when a review is required, it is the independent reviewer for CONTRACT REVIEW and code REVIEW, with distinct candidate/contract-bound evidence. It uses its own official API, account and spend authority; the two review stages are not interchangeable. Missing compatibility, identity, capacity or explicit budget authorization means wait, not substitution or fabricated PASS. Audit evidence cannot be converted to review.
- Local AI (including Qwen): optional, non-blocking assistance only for preliminary complexity classification, context preparation/reduction, extraction, labeling, and other auxiliary tasks. It must not diagnose failures, implement authoritatively, review security, or make binding decisions. Its absence or failure cannot stop an otherwise eligible pipeline.
- OpenRouter: normally inactive; exceptional rescue for already-started work only when both primary providers are blocked by quota, with its own account/capacity/budget authorization. It is never an independent reviewer and cannot start new READY work. Qwen does not review or make binding decisions.
- Human Gate Semantics: `NEEDS_HUMAN` is reserved strictly for genuine human-only decisions (product ambiguity, credentials/secrets, irreversible operator decisions, merge gates, business policy decisions). Deterministic executor recovery and non-convergence must use machine-operable state/reason semantics (`EXECUTOR_RECOVERY_REQUIRED`, `WAITING_CAPACITY`) without triggering false human gates.

## Capacity policy
- When both primary subscription agents are exhausted, scheduler stops admitting new READY changes.
- Scheduler may continue eligible in-flight work through OpenRouter only as explicitly authorized quota rescue after both primary providers are blocked by quota; DeepSeek remains the independent reviewer under its separate review authority. Otherwise wait.
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

