## Context

See `proposal.md` for motivation. In Change 005 (`005-provider-resilience-and-exhaustion`), mini me established scheduler capacity modes (`RUN`, `DRAIN`, `WAIT`), primary provider health tracking (`Codex` and `Antigravity`), crash recovery, and the `WAITING_CAPACITY` job state. In Change 006, we introduce an optional paid drain fallback via OpenRouter to allow eligible in-flight jobs in `DRAIN` mode to make progress during dual-primary quota exhaustion, under authoritative budget policy locking, durable immutable pricing snapshots, true maximum-cost reservations, all-time unresolved encumbrance, immutable spend ledgers, and canonical model-independence constraints.

## Goals / Non-Goals

**Goals:**
- Implement `OpenRouterAdapter` conforming to `schemas/provider-result.schema.json` and agent role contracts (`schemas/reviewer-result.schema.json`).
- Implement the strict 10-point OpenRouter eligibility evaluator, ensuring fallback runs only during dual-primary exhaustion in `DRAIN` mode for existing in-flight jobs.
- Enforce canonical model independence: normalize model names to `(provider, family, architecture)` tuples to prevent same-family self-review ("Qwen does not review Qwen") across aliases or routes.
- Implement an authoritative budget policy guard (`openrouter_budget_policies`) in PostgreSQL as the row-level serialization lock (`SELECT ... FOR UPDATE`), computing true maximum-request reservations and enforcing daily and monthly hard caps (UTC).
- Persist durable pricing snapshots in `openrouter_pricing_snapshots` so that authorization parameters and maximum costs can be deterministically audited and reconstructed after daemon restart.
- Compute daily and monthly headroom with all-time `UNRESOLVED` encumbrance: unresolved reservations from past dates remain fully encumbered across UTC boundaries until explicit operator reconciliation.
- Implement an immutable financial ledger (`budget_ledger`) recording all actual settlements, adjustments, and breach events without arbitrary updates or deletes.
- Enforce pinned exact model routing and price ceilings; prohibit uncontrolled auto-routing.
- Implement fail-closed `SETTLEMENT_BREACH` protection if actual provider cost exceeds reserved maximum, preserving `is_breached = true` across daemon restarts and configuration reloads.
- Preserve DeepSeek Direct audit isolation (`DEEPSEEK_API_KEY` is direct only, never routed through OpenRouter; OpenRouter never skips or replaces audit).
- Maintain complete decoupling between OpenRouter outcomes and primary provider health (Codex/Antigravity health is not modified by OpenRouter, and OpenRouter success never returns scheduler to `RUN`).
- Expose REST API and CLI commands for budget tracking, active reservations, policy breach states, and OpenRouter status.

**Non-Goals:**
- Admitting new `READY` work using OpenRouter or using OpenRouter as a general load balancer.
- Paid routing during `RUN` mode (primary subscription providers are always used in `RUN`).
- Container previews and guided UI human validation (Stage 5).
- GitHub PR submission and production deployment (Stage 6).
- Autonomous budget limit modification by agents (human operator configuration only).

## Decisions

### Decision 1: PostgreSQL Persistence & Alembic Migration (`006_openrouter_budget`)
- **Choice**: Implement a four-table architecture created via Alembic migration `006_openrouter_budget` (down revision `005_provider_resilience`):
  1. `openrouter_budget_policies`: Authoritative per-project budget guard and serialization lock.
  2. `openrouter_pricing_snapshots`: Durable, immutable registry of model pricing used for authorization.
  3. `budget_reservations`: Mutable lifecycle tracking for in-flight requests (`RESERVED`, `SETTLED`, `RELEASED`, `UNRESOLVED`, `SETTLEMENT_BREACH`).
  4. `budget_ledger`: Immutable append-only financial ledger of all settled costs, adjustments, and breaches.
- **Schema Details**:
  - `openrouter_budget_policies`:
    - `project_id` (String(64), PK, FK to `projects.id`)
    - `enabled` (Boolean, NOT NULL, DEFAULT False)
    - `daily_cap_usd` (Numeric(10, 6), NOT NULL)
    - `monthly_cap_usd` (Numeric(10, 6), NOT NULL)
    - `currency` (String(3), NOT NULL, DEFAULT 'USD')
    - `policy_version` (Integer, NOT NULL, DEFAULT 1)
    - `is_breached` (Boolean, NOT NULL, DEFAULT False)
    - `updated_at` (DateTime with timezone, NOT NULL, DEFAULT NOW())
  - `openrouter_pricing_snapshots`:
    - `id` (String(128), PK) -- e.g. `"openrouter:anthropic/claude-3.5-sonnet:2026-08-20T00:00:00Z"`
    - `canonical_model_identity` (String(128), NOT NULL)
    - `routed_model_identity` (String(128), NOT NULL)
    - `prompt_price_per_token` (Numeric(14, 10), NOT NULL)
    - `output_price_per_token` (Numeric(14, 10), NOT NULL)
    - `additional_cost_per_request` (Numeric(10, 6), NOT NULL, DEFAULT 0)
    - `currency` (String(3), NOT NULL, DEFAULT 'USD')
    - `source` (String(64), NOT NULL) -- e.g. `"openrouter_catalog_api"`, `"operator_pinned"`
    - `observed_at` (DateTime with timezone, NOT NULL)
    - `created_at` (DateTime with timezone, NOT NULL, DEFAULT NOW())
  - `budget_reservations`:
    - `id` (UUID, PK)
    - `project_id` (String(64), FK to `projects.id`, NOT NULL)
    - `job_id` (String(64), FK to `jobs.id`, NOT NULL)
    - `change_id` (String(128), NOT NULL)
    - `role` (String(32), NOT NULL) -- `"implementer"`, `"reviewer"`
    - `canonical_model_identity` (String(128), NOT NULL)
    - `reserved_amount_usd` (Numeric(10, 6), NOT NULL)
    - `status` (String(32), NOT NULL) -- `"RESERVED"`, `"SETTLED"`, `"RELEASED"`, `"UNRESOLVED"`, `"SETTLEMENT_BREACH"`
    - `pricing_snapshot_id` (String(128), FK to `openrouter_pricing_snapshots.id`, NOT NULL)
    - `correlation_id` (String(128), indexed)
    - `created_at` (DateTime with timezone, NOT NULL, DEFAULT NOW(), indexed)
    - `updated_at` (DateTime with timezone, NOT NULL, DEFAULT NOW())
  - `budget_ledger`:
    - `id` (UUID, PK)
    - `reservation_id` (UUID, FK to `budget_reservations.id`, nullable)
    - `project_id` (String(64), FK to `projects.id`, NOT NULL)
    - `job_id` (String(64), FK to `jobs.id`, NOT NULL)
    - `change_id` (String(128), NOT NULL)
    - `provider` (String(32), NOT NULL, DEFAULT 'openrouter')
    - `role` (String(32), NOT NULL)
    - `canonical_model_identity` (String(128), NOT NULL)
    - `prompt_tokens` (Integer)
    - `completion_tokens` (Integer)
    - `total_tokens` (Integer)
    - `amount_usd` (Numeric(10, 6), NOT NULL)
    - `entry_type` (String(32), NOT NULL) -- `"SETTLEMENT"`, `"BREACH_SETTLEMENT"`, `"ADJUSTMENT"`
    - `created_at` (DateTime with timezone, NOT NULL, DEFAULT NOW(), indexed)
- **Indexes**: `ix_budget_reservations_project_status` on `(project_id, status)`, `ix_budget_ledger_project_created` on `(project_id, created_at)`, and `ix_budget_ledger_created` on `(created_at)`.

### Decision 2: Authoritative Policy Row Synchronization & Row-Level Locking
- **Choice**: Materialize operator configuration (`minime.yaml` / environment) into `openrouter_budget_policies` upon daemon startup and configuration reload, preserving runtime safety state (`is_breached`).
- **Locking & Verification Protocol**:
  1. Open PostgreSQL transaction and acquire row lock:
     `SELECT * FROM openrouter_budget_policies WHERE project_id = :project_id FOR UPDATE;`
  2. If policy record is absent, `enabled = false`, `is_breached = true`, or either cap is NULL or `$0.00`: DENY (`policy_denied`).
  3. Calculate committed spend from `budget_ledger` plus active encumbrances from `budget_reservations` across deterministic UTC boundaries and all-time unresolved reservations:
     $$\text{DAILY HEADROOM} = \text{daily\_cap\_usd} - \text{committed\_today\_utc} - \text{reserved\_today\_utc} - \text{all\_unresolved\_usd}$$
     $$\text{MONTHLY HEADROOM} = \text{monthly\_cap\_usd} - \text{committed\_month\_utc} - \text{reserved\_month\_utc} - \text{all\_unresolved\_usd}$$
     where:
     - `committed_today_utc` = `SUM(amount_usd)` from `budget_ledger` where `date_trunc('day', created_at AT TIME ZONE 'UTC') = date_trunc('day', NOW() AT TIME ZONE 'UTC')`
     - `committed_month_utc` = `SUM(amount_usd)` from `budget_ledger` where `date_trunc('month', created_at AT TIME ZONE 'UTC') = date_trunc('month', NOW() AT TIME ZONE 'UTC')`
     - `reserved_today_utc` = `SUM(reserved_amount_usd)` from `budget_reservations` where `status = 'RESERVED'` AND `date_trunc('day', created_at AT TIME ZONE 'UTC') = date_trunc('day', NOW() AT TIME ZONE 'UTC')`
     - `reserved_month_utc` = `SUM(reserved_amount_usd)` from `budget_reservations` where `status = 'RESERVED'` AND `date_trunc('month', created_at AT TIME ZONE 'UTC') = date_trunc('month', NOW() AT TIME ZONE 'UTC')`
     - `all_unresolved_usd` = `SUM(reserved_amount_usd)` from `budget_reservations` where `status = 'UNRESOLVED'` (across **all** past dates/months for the project).
  4. If `maximum_billable_request_usd > DAILY HEADROOM` OR `maximum_billable_request_usd > MONTHLY HEADROOM`: ROLLBACK and DENY (`budget_denial`).

### Decision 3: True Maximum-Request Reservation Formula & Routing Control
- **Choice**: Compute true upper-bound request cost using the durable `openrouter_pricing_snapshots` record:
  $$\text{maximum\_billable\_request\_usd} = (\text{prompt\_token\_upper\_bound} \times \text{prompt\_price\_per\_token}) + (\text{configured\_max\_output\_tokens} \times \text{output\_price\_per\_token}) + \text{additional\_cost}$$
- **Pricing Snapshot & Routing Enforcement**:
  - Request must bind to a pinned exact model route with a verified `pricing_snapshot_id`.
  - Uncontrolled auto-routing endpoints (e.g. `openrouter/auto`) are strictly prohibited.
  - If pricing changes between reservation and dispatch: the system **does not** dispatch with a price recalculation; the original reservation is cancelled/released, and a new atomic reservation using the updated snapshot is required before dispatch.

### Decision 4: Immutable Spend Settlement, Safe Unknown-Cost, & Breach Handling
- **Choice**: Differentiate settlement states cleanly:
  1. **Standard Settlement (`actual <= reserved`)**: Insert `budget_ledger` entry with `amount_usd = actual_cost`, update `budget_reservations` to `SETTLED`, releasing `reserved - actual` headroom.
  2. **Unknown Cost (`drop / timeout / malformed`)**: Update `budget_reservations` to `UNRESOLVED`. 100% of the reserved amount remains encumbered against daily and monthly headroom across UTC boundaries until explicit operator reconciliation. Never assumed $0.00.
  3. **Settlement Breach (`actual > reserved`)**: If OpenRouter reports a cost exceeding the reserved maximum:
     - Insert `budget_ledger` entry with `entry_type = 'BREACH_SETTLEMENT'`.
     - Update reservation to `SETTLEMENT_BREACH`.
     - Update `openrouter_budget_policies` setting `is_breached = true` to immediately fail-closed and block further paid fallback for that project.
     - Emit `BUDGET_BREACH_DETECTED` event for operator intervention.
     - `is_breached = true` cannot be cleared by daemon restarts or config reloads.

### Decision 5: Canonical Model Normalization & Independence Engine
- **Choice**: Normalize model strings into canonical tuples `(provider_prefix, model_family, architecture)` before evaluating independence.
- **Normalization Mapping**:
  - `qwen/qwen-2.5-coder-32b-instruct` and `qwen/qwen-2.5-coder-32b-instruct:free` both resolve to canonical family `qwen::qwen-2.5-coder-32b`.
  - `anthropic/claude-3.5-sonnet` and `anthropic/claude-3.5-sonnet:beta` resolve to `anthropic::claude-3.5-sonnet`.
- **Enforcement Rule**:
  - When selecting an OpenRouter fallback reviewer for a candidate implemented via OpenRouter fallback, the system filters `allowed_reviewer_models` to exclude candidates sharing the implementer's canonical model identity or model family.
  - If no distinct model exists or canonical identity cannot be verified, the system fails closed to `WAITING_CAPACITY` with blockage reason `DISTINCT_REVIEWER_UNAVAILABLE`.

### Decision 6: DeepSeek Direct Isolation & Outcome Decoupling
- **Choice**: Complete physical and logical isolation between OpenRouter and DeepSeek Direct.
- **Isolation Boundaries**:
  - `DEEPSEEK_API_KEY` is loaded exclusively into `DeepSeekAdapter`; `OpenRouterAdapter` never receives or references it.
  - OpenRouter is never invoked to audit candidates or replace DeepSeek Direct audit.
  - OpenRouter API outcomes (success, rate limit, quota limit, timeout) are recorded in job attempts and `budget_ledger` but never modify primary `provider_health` for Codex or Antigravity.
  - OpenRouter success never returns the scheduler to `RUN` mode. Returning to `RUN` requires verified primary pair recovery.

## Risks / Trade-offs

- **[Risk] Unresolved reservations lock budget headroom indefinitely** → *Mitigation*: Expose unresolved reservations in `minime budget status` and API, allowing operator reconciliation if an external request is confirmed to have dropped without billing.
- **[Risk] High concurrency contention on budget policy lock** → *Mitigation*: Row locks are scoped per project and held only for the duration of the reservation insert (sub-millisecond), releasing before external HTTP calls begin.
- **[Risk] Provider model alias expansion by OpenRouter** → *Mitigation*: Unknown or unmapped models fail closed and are rejected from selection until mapped in the canonical identity registry.

## Migration Plan

1. Execute Alembic migration `006_openrouter_budget.py` creating `openrouter_budget_policies`, `openrouter_pricing_snapshots`, `budget_reservations`, and `budget_ledger` tables.
2. Initialize configuration schemas in `src/minime/config.py` with default `enabled=False` and `$0.00` budget caps.
3. Rollback plan: Migration can be reversed via `alembic downgrade -1`. Disabling fallback in configuration immediately halts all OpenRouter operations safely without data loss.
