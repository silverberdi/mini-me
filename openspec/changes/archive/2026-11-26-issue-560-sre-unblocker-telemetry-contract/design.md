## Context

See `proposal.md` and the three modified capability deltas. The Watchdog already detects stalls, persists mutable per-stage diagnoses, and has a bounded mechanical-remediation mode. Orchestration stage events already form a durable append-only ledger used by recovery and temporal telemetry. Autonomy telemetry currently reduces completed-run evidence to operator-assisted versus no operator action; Mejora Continua already persists and presents operator-controlled Watchdog suggestions.

The rector v2.0 retains explicit human authority over scope, security, exceptional cost, implementation merge, and other reserved decisions. The requested v2.1 language must clarify how technical gates can be resolved without overriding those protections.

## Goals / Non-Goals

**Goals:**
- Route eligible technical blockers to a configured SRE Unblocker role through the existing Watchdog and lifecycle authorities.
- Make each attempt and outcome auditable from immutable stage-event evidence and usable by autonomy telemetry.
- Reuse existing PostgreSQL event persistence, Watchdog diagnosis, metrics projection, and improvement feed.
- Record a formal skill/playbook improvement proposal only when the evidence supports it.

**Non-Goals:**
- Granting the agent general permission to answer human questions or execute arbitrary commands.
- Creating a parallel scheduler, policy engine, event store, GitHub issue writer, or provider-specific role.
- Changing merge, deploy, budget, security, product-scope, or destructive-action authority.

## Decisions

1. **Use configured Watchdog identity and existing orchestration entry point.** Extend the current Watchdog diagnosis/remediation flow to invoke the SRE Unblocker skill with the configured Watchdog provider/model and existing bounded recovery setting. CLI providers expose a dedicated read-only `thinking` invocation profile; pass the configured model unchanged so model-specific effort variants are not contradicted by a hardcoded effort. This avoids a second scheduler or duplicated provider configuration. A cause is eligible only if the playbook explicitly allows it and current Run, stage, candidate, and ownership evidence matches. Otherwise the current human gate remains authoritative. The alternative—an always-on independent SRE agent—is rejected because it would duplicate orchestration and widen authority.

2. **Use typed stage events as intervention facts.** Persist `SRE_UNBLOCKER_ATTEMPTED`, `SRE_UNBLOCKER_RESOLVED`, and `SRE_UNBLOCKER_ESCALATED` as append-only orchestration stage events, with a deterministic transition/event key and sanitized evidence references for trigger, action, outcome, root cause, and improvement proposal. Keep the mutable `watchdog_diagnoses` row as the current diagnosis projection, not the audit record. The existing `run_id` links project identity through the authoritative Run. This avoids a new table and migration. Do not update a prior event to record a later outcome; append a later event. If existing event retention or deletion behavior cannot preserve the required audit history, resolve that before implementation rather than silently introducing a mutable substitute.

3. **Derive outcome categories from complete event evidence.** Extend the existing autonomy projection/read model to expose counts for no intervention, successful autonomous recovery, and operator-needed completion, while preserving the current aggregate autonomy denominator and no-data semantics. Unresolved, contradictory, or missing evidence stays unverified and excluded. Do not calculate an autonomy index from model self-report or Watchdog diagnosis status alone.

4. **Reuse the current improvement feed.** Store evidence-backed skill/playbook proposals through the existing Watchdog suggestion and Mejora Continua lifecycle, with links to source intervention events. Operators remain responsible for converting a suggestion into GitHub work. Do not introduce an autonomous issue-creation path.

5. **Make skill guidance subordinate to the contract.** Add `minime-sre-unblocker` to the canonical skills and wire it through the existing Watchdog role/skill invocation path. The skill must state its allowlist, evidence checks, stop conditions, and escalation behavior. Update `docs/CONTRATO_RECTOR.md` to v2.1 and `docs/METRICS.md` to define the intervention categories and evidence requirements. Contract text must explicitly preserve all v2.0 reserved human authorities; an ambiguous technical gate is not automatically a technical permission.

6. **Seed only three evidenced playbooks and preserve source gates.** The initial skill catalog covers (A) a PF-03 fallback/precondition warning only when existing local evidence proves the fallback is non-blocking and the required verification mapping is complete; (B) an MCP OAuth 401 by delegating renewal to the existing encrypted credential service, with no token exposure and no replay of a potentially effective tool call; and (C) an orphaned Git index lock only through existing exact-worktree ownership, candidate, and process-absence checks. For any business/cost/scope escalation, retain the original OpenSpec question and options byte-for-byte/structurally unchanged, adding technical diagnosis in a separate field. The alternative—allowing the model to dismiss generic heuristic blockers or rewrite human gates—is rejected because current contracts explicitly fail closed on unmapped checks and reserve those decisions for the operator.

## Risks / Trade-offs

- [Skill output may recommend an unauthorized action] → Treat model output as a proposal; enforce eligibility and action through existing deterministic recovery authorities, and fail closed on ambiguity.
- [Stage-event evidence may be incomplete or misclassified] → Use typed event names and schema-validated, sanitized payloads; omit unverified runs from autonomy categories.
- [Watchdog diagnosis is mutable and could be mistaken for audit history] → Keep intervention outcomes in append-only stage events and use diagnosis only as a current-state projection.
- [The requested v2.1 phrasing could be read as blanket autonomy] → Explicitly preserve the v2.0 reserved decision classes and require operator escalation when a blocker intersects them.

## Migration Plan

No schema migration is planned if existing stage-event records can represent and retain intervention evidence. Deploy the application and canonical skill together; older Runs without complete intervention events retain existing no-data/exclusion behavior. If implementation proves an additive schema migration is necessary to preserve append-only identity or evidence, pause and update this Change before applying it. Rollback disables the new invocation path and leaves recorded stage events readable by existing consumers.
