# Canonical Decisions

These decisions supersede the previous AgentFlow context pack.

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
- Normal path: Codex implementer / Antigravity reviewer, or the reverse, configured per project.
- Same primary agent cannot implement and review the same candidate.
- DeepSeek Direct: independent read-only auditor.
- Qwen local: optional advisory helper only.
- OpenRouter: optional paid drain fallback only.
- In OpenRouter drain fallback, substantive implementer model and authoritative reviewer model must differ. Qwen does not review Qwen.

## Capacity policy
- When both primary subscription agents are exhausted, scheduler stops admitting new READY changes.
- Scheduler enters DRAIN and may use permitted OpenRouter models/budget only to finish eligible in-flight stages.
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

