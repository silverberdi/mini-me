# budget-spend-tracking Specification

## Purpose
Tracks token usage and dollar spend for paid fallback operations, enforcing authoritative budget policy guards, durable immutable pricing snapshots, true maximum-cost reservations, immutable spend ledgers, concurrency-safe daily and monthly caps (UTC), persistent cross-boundary unresolved encumbrance, settlement breach protection, and fail-safe unknown-cost accounting.

## Requirements

### Requirement: Authoritative budget policy guard and breach persistence
The system SHALL require an explicit, durable `openrouter_budget_policies` row in PostgreSQL as the serialization and locking authority before any billable request is evaluated, SHALL fail closed with zero spend if the policy row is absent, disabled, unconfigured, or set to $0.00, and SHALL preserve the policy breach flag (`is_breached = true`) across daemon restarts and configuration reloads until explicit human operator reconciliation.

#### Scenario: Missing budget policy row denies reservation
- **WHEN** an in-flight job requests fallback reservation and no `openrouter_budget_policies` record exists for the project
- **THEN** the system denies the reservation (`policy_denied`) and prevents any HTTP call.

#### Scenario: Fallback disabled in policy denies reservation
- **WHEN** the `openrouter_budget_policies` record for the project has `enabled = false`
- **THEN** the system denies the reservation (`policy_denied`) and makes zero HTTP calls.

#### Scenario: Missing daily or monthly cap denies reservation
- **WHEN** the `openrouter_budget_policies` record has `daily_cap_usd` or `monthly_cap_usd` as NULL or unset
- **THEN** the system treats the cap as missing, denies the reservation (`policy_denied`), and makes zero HTTP calls.

#### Scenario: Zero budget cap denies reservation
- **WHEN** the `openrouter_budget_policies` record specifies a daily or monthly cap of $0.00
- **THEN** the system refuses the reservation and prevents all paid execution.

#### Scenario: Breached policy blocks further reservations
- **WHEN** the `openrouter_budget_policies` record has `is_breached = true`
- **THEN** the system rejects all reservation attempts for that project until operator resolution.

#### Scenario: Policy breach persists across daemon restarts and config reload
- **WHEN** a project policy is marked `is_breached = true` and the daemon restarts or operator configuration reloads with `enabled = true`
- **THEN** the system preserves `is_breached = true`, refuses to clear the breach automatically, and continues to deny paid fallback until explicit operator action.

#### Scenario: Autonomous budget increase strictly prohibited
- **WHEN** an agent encounters a budget denial or exhaustion condition
- **THEN** the system prohibits autonomous alteration of budget values and requires human operator configuration.

### Requirement: Durable pricing snapshots and true maximum-request reservation
The system SHALL record and reference immutable pricing snapshots in `openrouter_pricing_snapshots` in PostgreSQL, calculate the true upper-bound maximum cost of each billable request (`maximum_billable_request_usd = conservative_input_cost + maximum_possible_output_cost + billable_components`), and atomically commit a `budget_reservations` row under a row-level lock (`SELECT ... FOR UPDATE` on `openrouter_budget_policies`) before dispatching the HTTP call.

#### Scenario: Successful reservation with verified maximum request cost and durable snapshot
- **WHEN** prompt token upper bound, max output token limit, and pinned route pricing are verified against a durable `openrouter_pricing_snapshots` record, and headroom exists across both daily and monthly UTC windows
- **THEN** the system locks the policy row, inserts a `budget_reservations` record referencing `pricing_snapshot_id` in `RESERVED` status for the full maximum cost, and permits the HTTP request.

#### Scenario: Missing max output bound denies reservation
- **WHEN** a request lacks an explicit maximum completion/output token bound
- **THEN** the system refuses reservation and does not dispatch the HTTP request.

#### Scenario: Pricing change before dispatch cancels reservation and requires re-authorization
- **WHEN** pricing rates change or route validity cannot be guaranteed against the authorized snapshot prior to HTTP dispatch
- **THEN** the system SHALL NOT dispatch the request with an upward recalculation, releases the original reservation, and requires a new atomic reservation with a new pricing snapshot before dispatch.

#### Scenario: Reconstruction of maximum request cost after restart
- **WHEN** the daemon restarts and inspects an existing `budget_reservations` record
- **THEN** the system deterministically reconstructs `maximum_billable_request_usd` from the referenced immutable `openrouter_pricing_snapshots` record.

#### Scenario: Two concurrent reservations cannot exceed daily cap
- **WHEN** two concurrent in-flight jobs attempt to reserve fallback budget simultaneously with daily headroom sufficient for only one job
- **THEN** the transactional row lock serializes the evaluation, granting one reservation and denying the second (`budget_denial`).

#### Scenario: Two concurrent reservations cannot exceed monthly cap
- **WHEN** two concurrent jobs attempt to reserve fallback budget with monthly headroom sufficient for only one job
- **THEN** the transactional lock ensures only one reservation succeeds while the second is denied.

#### Scenario: Daily headroom sufficient but monthly cap exhausted denies reservation
- **WHEN** daily headroom is sufficient but the cumulative monthly spend plus active reservations exceeds `monthly_cap_usd`
- **THEN** the system denies the reservation (`budget_denial`) and transitions the job to `WAITING_CAPACITY`.

#### Scenario: Monthly headroom sufficient but daily cap exhausted denies reservation
- **WHEN** monthly headroom is sufficient but the cumulative daily spend plus active reservations exceeds `daily_cap_usd`
- **THEN** the system denies the reservation (`budget_denial`) and transitions the job to `WAITING_CAPACITY`.

### Requirement: Persistent cross-boundary unresolved encumbrance and settlement
The system SHALL record authoritative financial spend in `budget_ledger`, settle completed requests against active reservations, release unused headroom, and retain 100% of all `UNRESOLVED` reservations against both daily and monthly headroom across UTC boundaries until explicit operator reconciliation.

#### Scenario: Settlement below reservation releases unused difference
- **WHEN** an OpenRouter request completes with actual cost less than the reserved maximum amount
- **THEN** the system inserts an immutable `budget_ledger` entry with `amount_usd = actual_cost`, updates `budget_reservations` to `SETTLED`, and immediately frees the difference (`reserved_amount - actual_cost`).

#### Scenario: Exact settlement matches reserved amount
- **WHEN** an OpenRouter request completes with actual cost exactly equal to the reserved amount
- **THEN** the system records the immutable ledger entry, transitions the reservation to `SETTLED`, and maintains headroom calculations.

#### Scenario: Actual cost exceeding reservation triggers settlement breach
- **WHEN** provider-reported actual cost exceeds the authorized reservation amount
- **THEN** the system persists the actual cost in `budget_ledger` (`BREACH_SETTLEMENT`), updates the reservation to `SETTLEMENT_BREACH`, sets `is_breached = true` on `openrouter_budget_policies` to halt further paid calls, and emits `BUDGET_BREACH_DETECTED`.

#### Scenario: Safe handling of unknown cost or dropped connections
- **WHEN** an OpenRouter request times out after submission, drops connection, or returns malformed usage data
- **THEN** the system SHALL NOT assume the request cost $0.00, SHALL update the reservation to `UNRESOLVED`, and SHALL retain 100% of the reserved amount against both daily and monthly headroom.

#### Scenario: Unresolved reservation from yesterday still reduces today's headroom
- **WHEN** an `UNRESOLVED` reservation was created on a previous UTC day and a new fallback request is evaluated today
- **THEN** the system subtracts the unresolved amount from today's available daily headroom calculation.

#### Scenario: Unresolved reservation from previous month still reduces current monthly headroom
- **WHEN** an `UNRESOLVED` reservation was created in a previous UTC month and a new fallback request is evaluated in the current month
- **THEN** the system subtracts the unresolved amount from the current month's available monthly headroom calculation.

#### Scenario: UTC boundary does not release unresolved amount
- **WHEN** a day (00:00:00 UTC) or month (1st day 00:00:00 UTC) boundary passes while an `UNRESOLVED` reservation exists
- **THEN** the system continues to count the full reserved amount against active reservable headroom and does not change status to `RELEASED`.

#### Scenario: Multiple unresolved reservations accumulate conservatively
- **WHEN** multiple `UNRESOLVED` reservations exist for a project across past dates
- **THEN** the system sums all unresolved amounts and encumbers the full cumulative total against both current daily and monthly headroom.

#### Scenario: Operator reconciliation is required before headroom is restored
- **WHEN** an `UNRESOLVED` reservation is reconciled by an operator
- **THEN** the system updates the reservation status based on operator evidence, records any adjustment in `budget_ledger`, and only then restores available headroom.

#### Scenario: Immutability of historical financial ledger
- **WHEN** budget corrections or reconciliations are applied
- **THEN** existing `budget_ledger` records are never updated or deleted; corrections are recorded solely as additive `ADJUSTMENT` ledger entries.
