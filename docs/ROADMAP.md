# Roadmap

Only the current stage should exist as an active OpenSpec change. Future stages are converted into OpenSpec changes only after prior-stage closure and a fresh readiness review.

## Delivered Stages (001 – 016)
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

---

## Canonical Roadmap (017 – 018)

### 017 — PWA Control Center (`017-pwa-control-center`) — NEXT
**Outcome:** Deliver the rich web/PWA operator experience on top of the already-established control plane.
**Expected Scope:**
- Observability, mutations, previews, guided validation, history, provider/capacity state, responsive operational UX.
**Boundary:** Do NOT implement the PWA early before 017 is activated.

### 018 — End-to-End Self-Operating Development Loop (`018-end-to-end-self-operating-loop`)
**Outcome:** Consolidate the complete autonomous SDLC from discovery to production closure and metrics:
`discovery -> readiness -> autonomous work selection -> implementation -> deterministic checks -> recovery/remediation -> complementary review -> DeepSeek audit -> preview/UI validation -> PR -> merge gate -> post-merge sync -> OpenSpec archive -> cleanup`.
**Expected Scope:**
- Autonomy metrics (autonomous vs human-assisted steps, agent effectiveness, remediation count, provider use, cycle time, recovery points).
**Boundary:** Do NOT implement 018 during 013.
