# Proposal: 005-provider-resilience-and-exhaustion

## Why

In Stages 0–3, mini me established the foundation, execution pipeline, complementary review (Codex ↔ Antigravity), and DeepSeek Direct audit. However, continuous operation encounters subscription quota exhaustion, provider rate limits, network transients, and daemon restarts. If a primary subscription is depleted or the service restarts mid-run, jobs could be lost or left in inconsistent states.

Stage 4 (`005-provider-resilience-and-exhaustion`) hardens provider resilience, capacity tracking, and crash recovery exclusively for the primary execution providers (Codex and Antigravity). When primary subscription capacity is depleted or any required role in the configured primary pair becomes unavailable, the scheduler transitions from `RUN` to `DRAIN` to `WAIT`, halting admission of new `READY` work while preserving in-flight jobs and checkpoints in `WAITING_CAPACITY` without data loss, speculative admission, or silent policy violations.

## What Changes

- **Primary Provider Outcome Classification & Health Tracking**:
  - Strict provider outcome normalization conforming to `schemas/provider-result.schema.json` behind provider-specific adapters for primary providers (`Codex` and `Antigravity`).
  - Classify outcomes into `success`, `transient_error`, `quota_limit`, `rate_limit`, `auth_error`, `timeout`, `malformed_output`, `cancelled`, `policy_denied`, `unsafe_binding`, and `unknown_error`.
  - Distinguish transport/capacity health from domain verdicts: normal domain outcomes (such as a reviewer returning `CHANGES_REQUIRED` or findings) count as transport `success` and do NOT degrade provider health.
  - Durable persistence of primary provider health and capacity windows in PostgreSQL (`provider_health` and `capacity_windows` tables).
  - Capture explicit reset timestamp signals and `retry_after` headers where reported by providers without inventing arbitrary reset times.
- **Deterministic Reset Window Probe Verification**:
  - A capacity reset timestamp is treated as a scheduling eligibility hint, never as automatic proof of recovery.
  - When a reset window elapses (`capacity_reset_at <= now`), the system executes a configured availability probe or awaits a verified fresh success signal; only positive evidence transitions a provider to `available`.
  - If a probe fails, remains exhausted, or is ambiguous, the system remains in `DRAIN` or `WAIT`.
- **Strict Scheduler Capacity Lifecycle (`RUN` → `DRAIN` → `WAIT`)**:
  - `RUN`: Normal execution mode. A new `READY` change may be admitted ONLY when the complete configured primary pair (implementer AND reviewer) has verified availability. Speculative admission (starting work hoping an unavailable reviewer recovers later) is strictly prohibited.
  - `DRAIN`: Entered as soon as the system cannot safely admit a complete new pipeline because any required primary role in the configured pair is unavailable or exhausted (e.g. Codex available, Antigravity exhausted). Halts all new `READY` change admission; allows already in-flight work to advance through stages whose required provider is currently available.
  - `WAIT`: Entered when no in-flight job can make useful progress with available primary capacity. No new work is admitted, no fallback provider is invoked in 005, and in-flight jobs pause durably in `WAITING_CAPACITY` until primary capacity is verified recovered.
  - Deterministic return to `RUN` occurs only after positive probe evidence confirms complete primary pair availability.
- **Primary-Provider Scope Boundary**:
  - Scheduler capacity modes and admission gating in 005 are driven exclusively by primary execution providers (Codex and Antigravity). DeepSeek Direct remains governed by the 004 audit lifecycle and does not drive scheduler `RUN`/`DRAIN`/`WAIT` transitions.
- **Pairing Invariant Protection & Safe WAITING_CAPACITY**:
  - Enforce Codex ↔ Antigravity complementary pairing without compromise. Provider exhaustion must NEVER cause silent self-review, provider replacement, pairing mutation, review bypass, or audit skipping.
  - When an in-flight job reaches a stage whose required primary provider is unavailable, it transitions safely to `WAITING_CAPACITY` with durable evidence.
- **Safe Daemon Restart & Git Lock Recovery**:
  - Safe startup reconciliation scanning PostgreSQL for non-terminal in-flight jobs (`RUNNING`, `CHECKS_RUNNING`, `REVIEW_RUNNING`, `AUDIT_RUNNING`).
  - Preserve candidate head SHA, base SHA, worktree binding, and prior check/review/audit evidence without re-executing completed expensive phases.
  - Reconcile interrupted executions into deterministic resumable or `WAITING_CAPACITY` states without inferring completion without evidence.
  - Safe Git lock recovery: `.git/index.lock` files may be cleared ONLY if verified to belong to a mini me-managed worktree with no active owning process. If ownership cannot be established, fail closed to `RECOVERY_BLOCKED` for operator inspection.
- **Observability API & CLI Extensions**:
  - REST endpoints: `GET /scheduler/status`, `GET /providers/health`, `GET /jobs/{job_id}` (including blockage reason and lock state).
  - CLI commands: `minime scheduler status`, `minime providers health`.
  - Full secret redaction in all logs, events, and API payloads.

### Non-Goals (Explicitly Excluded)
- Real OpenRouter HTTP/API execution, `OPENROUTER_API_KEY`, paid fallback calls, fallback model selection, token/cost charging, and daily/monthly budget tracking (deferred to `006-openrouter-budgeted-drain-fallback`).
- Automated remediation/re-review loops (Post-MVP).
- Container preview and guided UI human validation (Stage 5).
- GitHub PR submission, human merge, and production deployment (Stage 6).
- Multi-project fairness/concurrency scheduling, remote PWA, or local Qwen helper (Post-MVP).

## Capabilities

### New Capabilities
- `provider-capacity-tracking`: Primary provider outcome classification (`schemas/provider-result.schema.json`), transport vs domain verdict separation, health states (`available`, `temporarily_unavailable`, `exhausted`, `degraded`), rate limit tracking, reset window persistence, and probe verification.
- `scheduler-capacity-lifecycle`: Scheduler state machine (`RUN`, `DRAIN`, `WAIT`), strict primary-pair admission control for `READY` changes, and in-flight job preservation.
- `process-restart-recovery`: Daemon restart crash recovery, in-flight job reconciliation, restart-safe checkpoint resumption, and safe worktree Git lock verification.

### Modified Capabilities
- `execution-jobs`: Job pipeline transitions extended with `WAITING_CAPACITY` upon primary capacity exhaustion while preserving complementary pairing invariants.
- `pipeline-observability`: Observability for scheduler mode, primary provider health/capacity states, reset windows, blockage reasons, and lock recovery status via REST API and CLI commands.

## Impact

- **Database Schema**: New versioned Alembic migration `005_provider_resilience` (revising `004_deepseek_audit`) adding `provider_health` and `capacity_windows` tables.
- **API & CLI**: New REST endpoints (`GET /scheduler/status`, `GET /providers/health`) and CLI commands (`minime scheduler status`, `minime providers health`).
- **Safety & Policy**: Enforce complete primary pair availability before admission; eliminate speculative admission, silent self-review, and unsafe lock deletion.
