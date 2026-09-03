# Proposal: 018.2 — Autonomous End-to-End Execution

## Why
`mini me` requires an end-to-end autonomous delivery pipeline that progresses candidate work across the complete 15-phase lifecycle—from work discovery and readiness through scheduler admission, execution, bounded remediation, candidate freeze, deterministic checks, independent complementary review, DeepSeek Direct audit, preview validation (when UI-affecting), and native GitHub PR creation—until stopping authoritatively at the human merge gate (`READY_FOR_HUMAN_MERGE`).

This stage hardens the autonomous state machine and driver so that once work is marked READY, the orchestrator drives all intermediate transitions natively without manual phase-by-phase supervisor invocations.

## What Changes
- **Autonomous Delivery Loop**: Ensure the scheduler tick and orchestration coordinator advance runs through all 15 canonical phases seamlessly.
- **State Machine Hardening**: Formalize all stage transitions, including remediation paths (`CHECKS_FAILED -> EVALUATING_ATTEMPT -> IMPLEMENTING`, `REVIEW_REMEDIATION -> IMPLEMENTING`, `AUDIT_REMEDIATION -> IMPLEMENTING`) and external waiting states (`WAITING_CAPACITY`, `WAITING_EXTERNAL`, `READY_FOR_HUMAN_MERGE`).
- **Remediation Context Preservation**: Ensure structured review findings, audit findings, and check failure summaries are propagated directly into implementer prompt contexts for targeted single-retry remediation.
- **Native PR Creation & Recovery**: Harden native GitHub PR creation in `PREPARING_PR` with idempotent branch push, head verification, and existing PR adoption without manual `gh pr create` calls.
- **018.1 Baseline Enforcement**: Retain all mandatory efficiency rules (Codex default implementer, anti-loop same-SHA suppression, reviewer material independence, PostgreSQL telemetry).

## Non-Goals & Scope Boundaries
- Autonomous post-merge closure, automated main branch merge, and portfolio synchronization belong to **018.3**.
- Cross-stage multi-change metrics aggregation belongs to **018.4**.
- Modifying canonical database schema beyond existing migrations is out of scope.

## Dependencies & Predecessors
- Requires `018.1-provider-efficiency-reviewer-independence-hardening` DELIVERED.
- Requires PostgreSQL state, GitHub App runtime integration, and isolated worktree management.

## UI / Human Validation Impact
- 018.2 is non-UI infrastructure/governance capability; UI container preview is cleanly bypassed for non-UI changes while remaining mandatory for UI-affecting changes.
