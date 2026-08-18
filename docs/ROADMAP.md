# Roadmap

Only the current stage should exist as an active OpenSpec change. Future stages are converted into OpenSpec changes only after prior-stage closure and a fresh readiness review.

## 0 — Foundation (`001-foundation`) — ACTIVE
**Value:** durable, safe control plane.
PostgreSQL state/events/migrations; config; project registry; exact repo binding; OpenSpec discovery/DoR; GitHub work binding primitives; minimal status/health API/CLI; evidence/metrics foundations.

## 1 — Execution pipeline
**Value:** a READY change reaches a checked implementation in an isolated worktree using the configured primary implementer.

## 2 — Complementary review + human inbox
**Value:** Codex↔Antigravity review, bounded corrections, durable human decisions and supervision-first TUI/API inbox.

## 3 — DeepSeek Direct audit
**Value:** independent read-only audit before human attention.

## 4 — Resilience, capacity and drain fallback
**Value:** restarts/quotas preserve work; RUN/DRAIN/WAIT; OpenRouter drain fallback with model-independence and hard budget/privacy controls.

## 5 — Container preview + guided UI validation
**Value:** UI candidates are testable through an exact preview with explicit human validation scenarios tied to candidate identity.

## 6 — GitHub PR/merge + production closure
**Value:** draft PR identity, human merge, production promotion/deployment/verification, rollback action, OpenSpec archive, Issue/Project closure and final metrics.

**MVP = stages 0–6.**

## Post-MVP
- richer multi-project fairness/concurrency scheduler (data model is multi-project from Foundation)
- local Qwen helper optimization if useful
- secure remote PWA and push notifications
- metrics-informed/dynamic routing
- distributed workers only if a real need appears
