# Design: 005-provider-resilience-and-exhaustion

## Context

In Stages 0–3, mini me established the foundation, execution pipeline, complementary review (Codex ↔ Antigravity), and DeepSeek Direct audit. Continuous operation requires resilience against subscription quota exhaustion, provider rate limits, network transients, and daemon restarts.

See `proposal.md` for motivation.

Canonical constraints (from `AGENTS.md` and `docs/CANONICAL_DECISIONS.md`):
- Primary providers are complementary: Codex ↔ Antigravity. DeepSeek Direct is an independent read-only auditor.
- Provider exhaustion must NEVER cause silent self-review, provider substitution, pairing mutation, or review bypass.
- OpenRouter real execution, paid fallback calls, fallback model selection, and token/cost charging belong strictly to `006-openrouter-budgeted-drain-fallback` and are NOT implemented in 005.
- PostgreSQL is the sole operational database; schema evolves via versioned Alembic migrations.
- Secrets remain in host configuration and are redacted from all logs, events, and API payloads.
- Daemon/core owns orchestration; TUI/API/CLI are clients.

## Goals / Non-Goals

**Goals:**
- Implement structured provider outcome classification conforming to `schemas/provider-result.schema.json` distinguishing transport/capacity health from domain verdicts (`CHANGES_REQUIRED` is transport `success`).
- Track primary provider health states (`available`, `temporarily_unavailable`, `exhausted`, `degraded`) and capacity reset windows in PostgreSQL (`provider_health`, `capacity_windows`).
- Implement the primary-driven scheduler capacity lifecycle state machine (`RUN`, `DRAIN`, `WAIT`) with strict complete-pair admission gating of `READY` work (no speculative admission).
- Implement verified capacity reset probing where `capacity_reset_at` is an eligibility hint requiring positive probe evidence before marking a provider available.
- Implement `WAITING_CAPACITY` behavior to preserve in-flight jobs and checkpoints safely when required primary capacity is unavailable.
- Implement daemon restart and crash recovery that reconciles interrupted in-flight jobs without state corruption or duplicate execution of completed phases.
- Implement safe worktree Git lock recovery that cleans up `.git/index.lock` only when ownership and dead-process safety are verified within managed worktrees, failing closed to `RECOVERY_BLOCKED` otherwise.
- Expose scheduler mode, primary provider health, and blockage details via FastAPI REST endpoints and CLI commands.

**Non-Goals:**
- Real OpenRouter HTTP/API execution, `OPENROUTER_API_KEY`, paid fallback calls, fallback model selection, token/cost charging, daily/monthly budget tracking, and `budget_usage` table (deferred to `006-openrouter-budgeted-drain-fallback`).
- DeepSeek Direct audit driving primary scheduler capacity modes (DeepSeek failures remain governed by the 004 audit lifecycle).
- Automated remediation/re-review loops (Post-MVP).
- Container preview deployments and UI human validation scenarios (Stage 5).
- GitHub PR creation, human merge, and production deployment (Stage 6).
- Multi-project fairness/concurrency scheduling, remote PWA, or local Qwen helper (Post-MVP).

## Decisions

### 1. Data Model & Alembic Migration (`005_provider_resilience`)
- **Decision**: Create a new versioned Alembic migration `005_provider_resilience.py` (revising `004_deepseek_audit`) adding two PostgreSQL tables:
  1. `provider_health`:
     - `id`: UUID (PK)
     - `provider`: String(64) (`codex`, `antigravity` strictly enforced at domain/repository boundary)
     - `model`: String(128), nullable
     - `status`: String(32) (`available`, `temporarily_unavailable`, `exhausted`, `degraded`)
     - `consecutive_failures`: Integer (default 0)
     - `last_result_class`: String(32), nullable (from `schemas/provider-result.schema.json`)
     - `last_error_summary`: Text, nullable
     - `last_success_at`: DateTime(timezone=True), nullable
     - `last_failure_at`: DateTime(timezone=True), nullable
     - `updated_at`: DateTime(timezone=True)
  2. `capacity_windows`:
     - `id`: UUID (PK)
     - `provider`: String(64) (`codex`, `antigravity` strictly enforced at domain/repository boundary)
     - `model`: String(128), nullable
     - `quota_exhausted_at`: DateTime(timezone=True)
     - `capacity_reset_at`: DateTime(timezone=True), nullable
     - `retry_after_seconds`: Integer, nullable
     - `source_signal`: String(64) (e.g. `header_retry_after`, `response_body_timestamp`, `unknown`)
     - `created_at`: DateTime(timezone=True)
- **Primary-Provider Scope Enforcement**: `provider_health` and `capacity_windows` persist records exclusively for primary execution providers (`codex` and `antigravity`). DeepSeek Direct remains governed exclusively by the 004 audit lifecycle, is not tracked in `provider_health` or `capacity_windows`, and never influences `RUN` / `DRAIN` / `WAIT` transitions or `READY` admission.
- **Scope Note on `budget_usage`**: `budget_usage` is omitted from 005 because real paid fallback execution is deferred to 006.

### 2. Provider Outcome Normalization & Domain Verdict Separation
- **Decision**: Wrap primary provider executions (Codex CLI and Antigravity CLI) in normalized outcome handlers conforming to `schemas/provider-result.schema.json`:
  - Strict classification into `success`, `transient_error`, `quota_limit`, `rate_limit`, `auth_error`, `timeout`, `malformed_output`, `cancelled`, `policy_denied`, `unsafe_binding`, `unknown_error`.
  - **Domain vs Transport Separation**: Normal domain outcomes (such as a reviewer returning `CHANGES_REQUIRED` or findings) count as transport `success` and do NOT degrade provider health.
  - Distinguish transient connection drops from hard quota exhaustion; extract `retry_after` or reset timestamp signals when explicitly provided.
  - Never invent reset timestamps; if unknown, persist `capacity_reset_at = null`.
  - Malformed or unparseable output fails closed as `malformed_output` without falsely marking a provider exhausted or available.

### 3. Primary-Driven Scheduler Capacity Lifecycle (`RUN` → `DRAIN` → `WAIT`)
- **Decision**: Implement `CapacityLifecycleService` driven strictly by primary execution providers (Codex and Antigravity):
  - **`RUN`**: Normal mode. A new `READY` change may be admitted ONLY when all required roles in the project's configured primary pair (implementer AND reviewer) are verified available. Speculative admission is prohibited.
  - **`DRAIN`**: Entered as soon as the system cannot safely admit a complete new pipeline because any required primary role in the configured pair is unavailable or exhausted (e.g. Codex available, Antigravity exhausted).
    - Halts admission of all new `READY` changes.
    - Allows already in-flight work to advance only through stages whose specific primary provider is currently available.
    - If an in-flight job reaches a stage whose required primary provider is unavailable, it transitions to `WAITING_CAPACITY` and stops safely.
  - **`WAIT`**: Entered when no eligible in-flight primary-provider work can make safe progress.
    - No new work is admitted.
    - No fallback provider is invoked in 005.
    - In-flight jobs remain durably paused in `WAITING_CAPACITY`.
    - Scheduler waits until provider reset/recovery condition is met.
  - **Return to `RUN`**: Occurs only after positive probe evidence confirms that both roles of the required primary pair are verified available.
  - **DeepSeek Audit Boundary**: DeepSeek Direct audit failures are governed by the 004 audit lifecycle and do NOT drive scheduler `RUN`/`DRAIN`/`WAIT` transitions.

### 4. Verified Capacity Reset Probing
- **Decision**: `capacity_reset_at` is treated strictly as an eligibility hint:
  - When `capacity_reset_at <= now`, the scheduler does not automatically mark the provider `available`.
  - The system triggers a provider availability probe or awaits a verified fresh success signal.
  - Only after positive evidence is the provider status updated to `available`. If the probe fails or encounters transient errors, the provider remains non-available and the scheduler remains in `DRAIN` or `WAIT`.

### 5. Complementary Pairing Invariants & Safe WAITING_CAPACITY
- **Decision**: Preserve 003 complementary review invariants unconditionally.
  - Codex implementation strictly requires Antigravity review; Antigravity implementation strictly requires Codex review.
  - Primary provider exhaustion must NEVER trigger self-review, provider replacement, pairing reconfiguration, review bypass, or DeepSeek audit skipping.
  - When the required complementary reviewer is exhausted, the job transitions to `WAITING_CAPACITY` and retains all check results, diffs, and attempt records in PostgreSQL.

### 6. Safe Daemon Crash & Git Lock Recovery
- **Decision**: Implement `RestartRecoveryService` executed on daemon startup:
  - Scans PostgreSQL for non-terminal jobs (`RUNNING`, `CHECKS_RUNNING`, `REVIEW_RUNNING`, `AUDIT_RUNNING`).
  - Records `DAEMON_RESTARTED` and `JOB_INTERRUPTED` events.
  - Preserves completed check results and candidate head SHA without re-running checks; preserves verified review/audit records.
  - Interrupted mid-agent attempts are recorded as `INTERRUPTED` and transitioned to `WAITING_CAPACITY` or a clean resumable state. Never infers agent completion without evidence.
  - **Safe Git Lock Recovery**:
    - An `.git/index.lock` file is removed ONLY if it is located within a mini me-managed worktree AND the system conclusively verifies there is no active owning mini me process.
    - If ownership/safety cannot be established (or if the lock is outside managed worktrees), the system fails closed, sets job status to `RECOVERY_BLOCKED`, and exposes the lock path and reason in observability for operator intervention.

### 7. Observability Endpoints & CLI Commands
- **Decision**: Expose REST endpoints in FastAPI:
  - `GET /scheduler/status`: returns `{ mode, admission_allowed, active_jobs_count, primary_capacity_available, wait_reason, updated_at }`
  - `GET /providers/health`: returns list of primary provider health records with reset timestamps.
  - `GET /jobs/{job_id}`: includes `WAITING_CAPACITY` blockage details and `RECOVERY_BLOCKED` lock diagnostics.
  And CLI commands in `minime.cli`:
  - `minime scheduler status`
  - `minime providers health`
- **Secret Redaction**: Provider credentials are never exposed in API payloads, logs, or CLI output.

### 8. Future 006 Seam (Abstract Fallback Eligibility Contract)
- **Decision**: Define a lightweight abstract interface / policy seam (`FallbackPolicyHook` or `is_fallback_eligible`) in `src/minime/domain/interfaces.py` that defaults to no fallback in 005.

## Risks / Trade-offs

- **[Risk]** Spurious 429 rate limit causing premature transition to DRAIN/WAIT.
  - **Mitigation**: Distinguish transient rate limits (with `retry_after`) from definitive quota exhaustion.
- **[Risk]** Prematurely resuming on reset window timestamp without actual capacity.
  - **Mitigation**: Require positive probe verification before transitioning provider health to `available` and scheduler to `RUN`.
- **[Risk]** Deleting an active Git process's lock during restart recovery.
  - **Mitigation**: Strict ownership verification for `.git/index.lock`; fail closed to `RECOVERY_BLOCKED` if ownership cannot be confirmed.
