# Roadmap

Only the current stage should exist as an active OpenSpec change. Future stages are converted into OpenSpec changes only after prior-stage closure and a fresh readiness review.

## Delivered Stages (001 – 017)
- **001 Foundation (`001-foundation`)**: PostgreSQL state/events/migrations, project registry, immutable repository binding, OpenSpec DoR, minimal status/health.
- **002 Implementation Pipeline (`002-implementation-pipeline`)**: Worktree lifecycle, Codex/Antigravity implementers, deterministic checks runner.
- **003 Complementary Review Pipeline (`003-complementary-review-pipeline`)**: Codex ↔ Antigravity complementary review, structured verdicts, bounded correction loop.
- **004 DeepSeek Independent Audit (`004-deepseek-independent-audit`)**: Read-only DeepSeek Direct audit gate and risk assessment before human attention.
- **005 Provider Resilience and Exhaustion (`005-provider-resilience-and-exhaustion`)**: Restart recovery, provider health tracking, RUN/DRAIN/WAIT scheduler modes.
- **006 OpenRouter Budgeted Drain Fallback (`006-openrouter-budgeted-drain-fallback`)**: Budgeted drain-only fallback with model independence (substantive implementer model != reviewer model).
- **007 Agent Continuation and Reassignment Governance (`007-agent-continuation-and-reassignment-governance`)**: Continuation engine, blocker validation, structured handoffs, ping-pong prevention.
- **008 Autonomous Change Orchestration (`008-autonomous-change-orchestration`)**: Multi-stage autonomous orchestration coordinator, stage transitions, human gates.
- **009 GitHub App Runtime Integration (`009-github-app-runtime-integration`)**: GitHub App authentication, remote PR lookup/reconciliation, automated PR preparation.
- **010 Governance and Recovery Hardening (`010-governance-and-recovery-hardening`)**: Recovery safety, bounded transition keys, change logical identity preservation.
- **011 Preserved Candidate Remediation Generations (`011-preserved-candidate-remediation-generations`)**: Candidate generation progression, base drift integration, manifest integrity.
- **012 Execution Operations Dashboard (`012-execution-operations-dashboard`)**: Read-only real-time operations dashboard, pipeline phase stepper, secret-redacted diagnostics.
- **013 Container Preview + Guided UI Validation (`013-container-preview-guided-validation`)**: Isolated candidate-bound container previews, image digest authority, guided validation scenarios, stale validation invalidation.
- **014 TUI Operator Console (`014-tui-operator-console`)**: Interactive terminal operator console via Textual, multi-viewport layout, progressive disclosure, 013 preview/validation projection, and zero direct database queries.
- **015 Operator Actions / Control Plane (`015-operator-actions-control-plane`)**: Reusable canonical operational actions and mutation control plane (`ControlPlaneService`), optimistic concurrency protection, idempotency, safe cancellation, audit trail persistence, and TUI/CLI/API execution integration.
- **016 Autonomous Queue + Work Selection (`016-autonomous-queue-work-selection`)**: Autonomous backlog item discovery, deterministic prioritization scoring, starvation aging, roadmap predecessor governance, admission control, native candidate startup, CLI/API management, and TUI queue observability.
- **017 PWA Control Center (`017-pwa-control-center`)**: Responsive web/PWA operator experience on top of the control plane with real-time SSE streaming, offline caching, candidate inspection, container previews, guided UI validation, and zero direct database queries.

---

## Canonical Roadmap (018)

### 018 — End-to-End Self-Operating Development Loop (`018-end-to-end-self-operating-loop`) — ACTIVE
**Outcome:** Consolidate the complete autonomous SDLC from discovery to production closure and metrics:
`discovery -> readiness -> autonomous work selection -> implementation -> deterministic checks -> recovery/remediation -> complementary review -> DeepSeek audit -> preview/UI validation -> PR -> merge gate -> post-merge sync -> OpenSpec archive -> cleanup`.

#### 018.1 — Provider Efficiency & Reviewer Independence Hardening (`018.1-provider-efficiency-reviewer-independence-hardening`) — DELIVERED
- **Outcome:** Establish canonical provider roles (Codex workhorse, Antigravity premium), deterministic task classification, retry budgets, same-SHA anti-loop suppression, lightweight bookkeeping reconciliation, technical reviewer independence enforcement, CHECKS_FAILED remediation routing, anti-polling safeguards, PostgreSQL efficiency telemetry, and TUI/PWA telemetry views.
- **Status:** DELIVERED / PILOT PROVEN (8/8 Gates Passed)

#### 018.2 — Autonomous End-to-End Execution (`018.2-autonomous-end-to-end-execution`) — CURRENT
- **Boundary:** Autonomous queue-driven progression across all 9 canonical lifecycle stages without human intervention until the final human merge gate.
- **Status:** CURRENT / READY TO COMMENCE

#### 018.3 — Autonomous Post-Merge Closure (`018.3-autonomous-post-merge-closure`) — BLOCKED
- **Outcome:** Automated post-merge spec synchronization, change archiving, worktree cleanup, and portfolio state closure.
- **Status:** BLOCKED on 018.2 proving run PASS

#### 018.4 — Metrics + Proving Run (`018.4-metrics-proving-run`) — UPCOMING
- **Outcome:** Autonomy metrics aggregation, cross-stage self-hosting verification, and multi-change autonomous SDLC proving run.
