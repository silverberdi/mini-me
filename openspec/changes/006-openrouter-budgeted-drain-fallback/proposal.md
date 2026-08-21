# Proposal: 006-openrouter-budgeted-drain-fallback

## Why

In Stages 0–4 (Changes `001` through `005`), mini me established durable orchestration, complementary primary pairing (Codex ↔ Antigravity), independent DeepSeek Direct audit, primary provider health tracking, and crash-safe scheduler modes (`RUN` → `DRAIN` → `WAIT`). When primary subscription capacity is depleted, the scheduler transitions to `DRAIN` and pauses pipeline progress in `WAITING_CAPACITY`.

However, halting in-flight tasks until primary quotas recover may introduce lengthy operational stalls for active, partially completed changes. Stage 4 (`006-openrouter-budgeted-drain-fallback`) enables an optional, strictly budgeted, paid OpenRouter drain fallback. This mechanism allows mini me to finish eligible in-flight work already in progress when **both** subscription primaries are exhausted, without admitting new `READY` changes, while enforcing hard daily/monthly spend limits via authoritative policy locking, durable immutable pricing snapshots, true maximum-cost reservations, all-time unresolved encumbrance, immutable ledger settlements, privacy/secret boundaries, and strict canonical model-independence between substantive implementers and authoritative reviewers ("Qwen does not review Qwen").

## What Changes

- **Strict 10-Point OpenRouter Eligibility Rule**:
  - Being in `DRAIN` mode is necessary but **not** sufficient. Paid OpenRouter fallback may execute ONLY when ALL 10 conditions are simultaneously satisfied:
    1. Scheduler mode is `DRAIN`.
    2. The job was already in-flight before fallback eligibility was reached.
    3. The job is blocked on a primary implementer/reviewer stage.
    4. No new `READY` work is being admitted.
    5. **BOTH** subscription primary providers (Codex AND Antigravity) are verified exhausted/unavailable under the 005 capacity contract. (If only one primary is exhausted, normal 005 DRAIN behavior applies; OpenRouter is strictly forbidden to accelerate or bypass).
    6. Explicit fallback spending is enabled by operator configuration.
    7. Required daily and monthly budget exists with remaining reservable capacity.
    8. A valid independent fallback model can be selected.
    9. Candidate, base, and change identity bindings remain valid.
    10. No existing pipeline invariant (complementary review, DeepSeek Direct audit) would be bypassed.
  - OpenRouter is an emergency drain mechanism, never normal load balancing or performance acceleration.

- **Prohibition on New Work & Decoupling from RUN Mode**:
  - OpenRouter must NEVER make a `READY` change admissible or start new work.
  - OpenRouter fallback capacity does NOT count as evidence that the scheduler may return to `RUN`.
  - Returning to `RUN` mode requires verified primary-pair recovery (Codex + Antigravity). Successful OpenRouter execution never alters primary provider health or triggers a transition to `RUN`.

- **Authoritative Budget Policy Guard & Breach Persistence**:
  - Project-scoped `openrouter_budget_policies` table in PostgreSQL serves as the durable authority and row-level serialization lock for all budget evaluations.
  - Default configuration is strictly disabled (`enabled = false`, `$0.00` daily and monthly caps).
  - Missing policy row, missing caps, or `$0.00` caps fail closed (`policy_denied`), preventing all paid calls (never interpreted as unlimited).
  - Synchronized from operator config on daemon startup / config reload, but runtime safety state (`is_breached = true`) is **never** silently cleared by config reloads; resetting a breach requires explicit operator action. Autonomous agents cannot modify budget policies or raise caps.

- **Durable Pricing Snapshots & True Maximum-Request Reservation**:
  - Naive estimations are prohibited. Pricing evidence is durably stored in an immutable `openrouter_pricing_snapshots` table.
  - Before any billable HTTP dispatch, the system computes the exact upper-bound maximum cost:
    `maximum_billable_request_usd = conservative_input_cost + maximum_possible_output_cost + any_billable_components`.
  - Transactionally locks the `openrouter_budget_policies` row (`SELECT ... FOR UPDATE`), verifies daily (00:00:00 UTC) and monthly (1st day 00:00:00 UTC) headroom against committed spend, active reservations in the current window, and **all** historical `UNRESOLVED` reservations for the project across time boundaries, and commits a `budget_reservations` row in `RESERVED` status.
  - Uncontrolled auto-routing is strictly forbidden: requests must use exact pinned model routes with verified pricing snapshot IDs so execution cost cannot exceed the reserved maximum. If pricing changes prior to dispatch, the request is not sent; the old reservation is released and a new atomic reservation is attempted.

- **Immutable Spend Ledger, Safe Settlement, & Breach Handling**:
  - Authoritative spend evidence is recorded in an append-only `budget_ledger` table (never updated or deleted).
  - Standard settlement: actual cost is recorded in `budget_ledger`, reservation status transitions to `SETTLED`, and unused reservation headroom (`reserved - actual`) is atomically released.
  - Fail-safe unknown cost: timeouts, network drops, or malformed usage data transition reservations to `UNRESOLVED` and retain 100% of the reserved amount against all future daily and monthly headroom across UTC window boundaries until operator reconciliation. Never assumed $0.00.
  - Settlement breach (`SETTLEMENT_BREACH`): if provider actual cost exceeds reservation, actual spend is immutably logged, the reservation is marked `SETTLEMENT_BREACH`, the project's policy is set to `is_breached = true` (immediately disabling further paid fallback for that project), and an alert is raised.

- **Canonical Model Identity & Independence Policy**:
  - Independence is evaluated on canonical model identity (normalizing provider, model family, and architecture), NOT naive string matching.
  - Aliases or routing names resolving to the same underlying model count as the same model.
  - If canonical independence cannot be proven, the system fails closed and transitions the job to `WAITING_CAPACITY` rather than permitting self-review.

- **Complementary Review Authority & DeepSeek Direct Isolation**:
  - Preserves authoritative role separation; persisted evidence records exact provider and model for each stage.
  - DeepSeek Direct remains the independent direct auditor (`DEEPSEEK_API_KEY` is direct only, never routed through or fallback-replaced by OpenRouter).
  - Provider outcome normalization conforms strictly to `schemas/provider-result.schema.json` (distinguishing local budget denials from OpenRouter provider errors).
  - Complete credential redaction in all logs, events, API responses, and CLI outputs.

- **Observability API & CLI Extensions**:
  - REST endpoints: `GET /budget/usage`, `GET /providers/openrouter/status`.
  - CLI commands: `minime budget status`, `minime providers openrouter`.
  - Operators can inspect enablement, policy breach state, job eligibility reasons, committed vs reserved spend, remaining headroom, unresolved settlements, and canonical model selections.

### Non-Goals (Explicitly Excluded)
- Admitting new `READY` work into OpenRouter or using OpenRouter for general load balancing.
- Dynamic or cheapest-model routing during normal `RUN` mode.
- Autonomous budget limit modification by agents.
- OpenRouter fallback for DeepSeek Direct audit.
- Automated remediation loops (Post-MVP).
- Container previews and guided UI human validation (Stage 5).
- GitHub PR submission, human merge, and production deployment (Stage 6).
- Multi-project concurrency scheduler, remote PWA, or local Qwen helper (Post-MVP).

## Capabilities

### New Capabilities
- `openrouter-drain-fallback`: OpenRouter HTTP adapter for paid drain fallback execution during dual-primary exhaustion in `DRAIN` mode, pinned exact routing, durable pricing snapshot binding, canonical model normalization, model independence enforcement, and provider outcome classification.
- `budget-spend-tracking`: Transactional budget policy guard, durable pricing snapshot registry, and immutable ledger in PostgreSQL (`openrouter_budget_policies`, `openrouter_pricing_snapshots`, `budget_reservations`, and `budget_ledger`), true maximum-request reservation, all-time unresolved encumbrance, atomic settlement, concurrency-safe daily/monthly hard cap enforcement (UTC), settlement breach protection, and fail-safe unknown-cost accounting.

### Modified Capabilities
- `scheduler-capacity-lifecycle`: Scheduler in `DRAIN` mode coordinates budgeted OpenRouter fallback under the strict 10-point eligibility rule, strictly prohibits `READY` admission, preserves primary health decoupling, and transitions to `WAIT` when budgets, policy breaches, or fallback capacity deplete.
- `pipeline-observability`: REST API and CLI surface extended with budget status, policy breach state, spend metrics (committed, reserved, remaining), OpenRouter fallback state, and eligibility/denial inspection with complete secret redaction.

## Impact

- **Database Schema**: Versioned Alembic migration `006_openrouter_budget` (down revision `005_provider_resilience`) adding `openrouter_budget_policies`, `openrouter_pricing_snapshots`, `budget_reservations`, and `budget_ledger` tables with transactional locking support.
- **API & CLI**: REST endpoints (`GET /budget/usage`, `GET /providers/openrouter/status`) and CLI commands (`minime budget status`, `minime providers openrouter`).
- **Security & Privacy**: Strict credential isolation; `DEEPSEEK_API_KEY` is direct only; all OpenRouter keys and sensitive payloads redacted.
- **Cost Policy**: Hard daily and monthly spend caps with authoritative policy row locking, immutable pricing snapshots, true maximum-cost reservation, persistent unresolved encumbrance, settlement breach fail-closed protection, and operator-only budget configuration.
