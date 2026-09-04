# Roadmap

Only the current stage should exist as an active OpenSpec change. Future stages are converted into OpenSpec changes only after prior-stage closure and a fresh readiness review.

## Delivered Stages (001 – 018)
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
- **018 End-to-End Self-Operating Development Loop (`018-end-to-end-self-operating-loop`)**: Full autonomous SDLC loop proven end-to-end from backlog discovery to production closure:
  - **018.1 Provider Efficiency & Reviewer Independence Hardening (`018.1-provider-efficiency-reviewer-independence-hardening`)**: DELIVERED. Codex primary workhorse, AG premium governor, retry budgets, anti-loop suppression, lightweight reconciliation, reviewer independence, telemetry persistence.
  - **018.2 Autonomous End-to-End Execution (`018.2-autonomous-end-to-end-execution`)**: DELIVERED. Autonomous queue-driven progression across all 9 canonical lifecycle stages without human intervention until the final human merge gate.
  - **018.3 Autonomous Post-Merge Closure (`018.3-autonomous-post-merge-closure`)**: DELIVERED. Native post-merge lifecycle: PR merge detection, ancestry verification, spec sync, change archiving, branch deletion, issue closure, project status transition, lock cleanup.
  - **018.4 Metrics + Final Proving Run (`018.4-metrics-final-proving-run`)**: DELIVERED. End-to-end multi-change proving run, 100% productive attempt ratio on proving candidate, 0 AG routine implementation, 0 same-SHA duplicate retries, complete post-merge closure.

---

## Canonical Roadmap (Next Stages)

### 019 — Server Runtime & Production Deployment (`019-server-runtime-deployment`)
- **019.1 Server Bootstrap (`019.1-server-bootstrap`)**: DELIVERED. Machine bootstrap, user `minime`, Python 3.14 virtualenv, GitHub App token minting, headless Codex/Antigravity/DeepSeek/Chrome verified on `192.168.0.194`.
- **019.2 Server Runtime (`019.2-server-runtime`)**: DELIVERED. Systemd services `minime-api.service` and `minime-scheduler.service`, LAN PWA acceptance, controlled reboot recovery, zero Mac dependency.
- **019.3 Google Authentication & Operator Authorization (`019.3-google-authentication`)**: DELIVERED. Google OIDC/OAuth 2.0 authentication, allowlist authorization, server-managed sessions, fail-closed API protection, PWA login shell, security audit trail.
- **019.4 Cloudflare Tunnel & Secure Remote Access (`019.4-cloudflare-tunnel-remote-access`)**: DELIVERED. Discovered and adopted existing Cloudflare Tunnel, public HTTPS ingress `https://mini-me.silverman.pro`, origin bound to `127.0.0.1:8787`, zero router port forwarding, 14 server workloads preserved, full HTTPS authentication and authorization verified.
- **019.5 Final Mac-Independent / Public Proving Run (`019.5-final-proving-run`)**: CURRENT. End-to-end proving run executed entirely on the server runtime with zero local machine involvement.
