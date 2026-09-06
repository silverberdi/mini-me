# Proposal: Generic Provider Capacity Recovery & Drain Policy

## Problem Statement
Mini me requires a robust, provider-agnostic capability model for capacity recovery and drain fallback.
Previously, provider health evaluation lacked automated background probing, leaving providers indefinitely stuck in `TEMPORARILY_UNAVAILABLE` after transient failures until manual intervention occurred.
Furthermore, drain/fallback execution (e.g. OpenRouter) must strictly adhere to governance constraints: it may only complete materially in-progress work already started when primary subscription capacity is exhausted, and must never be used to initiate new BACKLOG, READY, or QUEUED work.

## Core Requirements & Invariants
1. **Generic Provider Capability Contract**: Scheduler and orchestration interact with execution, review, and audit providers through a generic adapter abstraction (`ProviderAdapterInterface`), not hardcoded provider branches. Future provider replacements (e.g., Cursor) can be added via adapter registration without rewriting scheduler logic.
2. **Autonomous Background Recovery Probing**: Unavailable providers are periodically re-evaluated via lightweight, non-destructive probes without creating Runs, Jobs, or consuming implementation retry budget. Positive probes transition providers to `AVAILABLE` automatically.
3. **Reset Timing & Bounded Blind Wait**:
   - `AUTO_DISCOVERED` and `OPERATOR_REPORTED` reset sources are supported.
   - Operators can enter or update expected return times.
   - Unknown reset periods enter bounded `WAITING_CAPACITY` capped at 2 hours before surfacing explicit operator decisions (`Set Return Time`, `Finish with Drain Provider`, `Keep Waiting`).
4. **Strict Drain Eligibility Boundary**: Drain fallback applies exclusively to active runs where material execution has already started (`attempt_count > 0` or candidate changes produced). Drain fallback is strictly prohibited from starting new BACKLOG, READY, or QUEUED items.
5. **Observability**: Expose detailed provider health, probe telemetry, expected reset, and drain eligibility across PWA, TUI, and API.

## Non-Goals
- Integrating Cursor itself in this milestone.
- Provider marketplace UI or direct dynamic provider switching for new tasks.
- Weakening budget caps or human merge authorization gates.
