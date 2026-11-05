# Design

## Context

See `proposal.md` for the motivation and `specs/execution-operations-dashboard/spec.md` for the observable contract. The repository already has a PostgreSQL `budget_ledger`, a ledger repository exposed through the unit of work, budget settlement logic, a Dashboard read model, and Dashboard UI/API consumers. The current cost card/series is still exposed as token-oriented data in the Dashboard path. PostgreSQL/ledger remains the financial authority; this Change must not add a parallel store or infer a price from token counters.

## Goals / Non-Goals

**Goals:**

- Add a single Dashboard read-model projection for verified liquidated costs, preserving `amount_usd`, provider, model, and ledger timestamp.
- Make provider attribution explicit for DeepSeek Direct and OpenRouter and retain model-level detail when present.
- Define a deterministic UTC daily aggregation for the time series, while retaining the source timestamps and enough identity metadata for traceability.
- Return an explicit no-data representation when the query has no eligible ledger costs.
- Prove the API-to-rendered-UI path with durable PostgreSQL data, plus focused unit/API/UI regression tests.
- Remove the old cost presentation's token/synthetic fallback from this Dashboard path and document the removal evidence.

**Non-Goals:**

- Changing budget reservation, settlement, pricing snapshots, reconciliation, or ledger schema semantics.
- Repricing historical entries, filling missing provider data, or assigning an unrecognized model to a specific model. Entries with a verified provider and missing/unrecognized model remain in the provider total and are grouped as `Modelo no identificado`.
- Adding a new financial table, queue, scheduler, provider integration, or deployment workflow.
- Replacing token telemetry elsewhere in the product where tokens are an independently requested metric.

## Decisions

### 1. Reuse the existing ledger repository and Dashboard read model

The Dashboard service will obtain cost rows through the existing unit-of-work `budget_ledger` repository and expose a typed cost projection in the existing Dashboard response path. This keeps the API boundary singular and ensures the UI cannot bypass the durable authority.

Alternative rejected: querying Run objects and deriving price from tokens. It cannot distinguish settled from unknown usage and violates the ledger authority requirement. A new cost repository or materialized table is also rejected because it would create a second source of truth.

### 2. Select only verified liquidated entries

The projection will apply the existing ledger semantics for settled/verified spend and exclude reservations, unresolved usage, malformed rows, entries without a usable ledger timestamp, and entries whose provider identity is not recognized by the existing provider catalog. A liquidated entry whose provider identity is verified is included in that provider's aggregate even when its model is null or not recognized; its amount is grouped under `Modelo no identificado` rather than attributed to a specific model. The implementation must use the existing provider/model fields rather than inventing identities. Unknown providers are excluded and are never relabeled as DeepSeek or OpenRouter.

Alternative rejected: treating every ledger row as spend or using unresolved reservation amounts as actual cost. Reservations are budget encumbrances, not liquidated spend.

### 3. Preserve traceability and deterministic aggregation

The API projection will include provider groups, recognized model breakdown, a `Modelo no identificado` bucket for verified-provider entries with null/unrecognized models, USD amounts with a decimal-safe serialization compatible with ledger precision, and source timestamps. For a chart series, rows are grouped by UTC calendar day and provider/model identity; each point carries the day bucket plus source timestamp metadata or the contributing ledger timestamps required by the existing response contract. No amount in the unidentified bucket is assigned to a specific model or another provider.

Alternative rejected: client-side aggregation from raw Runs or a locale-dependent browser timestamp. Server-side UTC grouping provides consistent results and makes the E2E assertion observable.

### 4. Make absence a typed UI state

The response will distinguish `no_data` from a numeric zero. When no eligible costs exist, the existing Dashboard response SHALL include the typed cost object `{ "status": "no_data", "providers": [], "series": [] }`; all unrelated Dashboard fields retain their existing response contract. The UI will render the Spanish “sin datos” state without placeholder `0`, `CLI`, estimate, or fallback provider/model labels. A real ledger amount of zero, if the durable contract permits one, remains distinguishable from absence according to the existing ledger semantics rather than being manufactured by the UI.

Alternative rejected: returning an empty numeric series and letting the chart library display zeroes. That loses the distinction required by the product contract.

### 5. Verification and safe retirement

Tests will seed real PostgreSQL ledger rows for both providers, call the application read path, and inspect the rendered Dashboard representation. Unit tests cover filtering/aggregation and no-data behavior; API/UI tests cover serialization and labels; the E2E proof records the database input, request, response, and rendered output. Existing token-oriented assertions are updated only where they describe the replaced Dashboard cost behavior. Budget/ledger settlement tests remain intact.

Removal ledger for this Change:

| Replaced behavior | Old entrypoint/writer | Action | Evidence required |
|---|---|---|---|
| Dashboard cost series based on tokens/synthetic fallback | Dashboard cost mapping in the existing frontend/read-model path, including the `tokens` chart mode | REMOVE/MIGRATE within the Dashboard cost path | Static reference search, red/green UI/API tests, PostgreSQL-to-UI E2E, final candidate SHA |
| Durable budget ledger and settlement history | `budget_ledger`, its migrations and settlement service | RETAIN-WITH-REASON | Existing ledger/settlement regression suite and migration history; no deletion or rewrite |

No other removal is authorized without evidence that the element is exclusively a consumer of the replaced Dashboard behavior.

## Risks / Trade-offs

- [Risk] Existing ledger rows may use provider/model conventions that differ between DeepSeek Direct and OpenRouter. → Mitigation: verify provider identity through the existing canonical provider fields; preserve null/unrecognized models under `Modelo no identificado`, never assign them to a specific model, and add fixtures for both observed forms.
- [Risk] Decimal formatting or browser chart adapters may round values inconsistently. → Mitigation: serialize from decimal ledger values using the established API convention and assert precision at API and UI boundaries.
- [Risk] Some historic ledger records may lack timestamps or model identity. → Mitigation: exclude rows without the timestamp needed for a time point, preserve available provider identity, and never fabricate missing metadata; show no-data when no eligible rows remain.
- [Risk] Removing the token fallback can expose empty dashboards previously showing synthetic content. → Mitigation: make the explicit “sin datos” state accessible and test it as a first-class outcome.
- [Risk] A mocked repository test could appear to prove the integration. → Mitigation: require a PostgreSQL-backed E2E with observable ledger insertion/query/rendering evidence before declaring implementation complete.

## Migration Plan

No schema migration is planned. Apply changes the Dashboard projection and UI in the existing candidate worktree, run the focused tests and the real PostgreSQL E2E, then run the official OpenSpec Verify workflow. Rollback is a Git revert of the candidate change; durable ledger rows and applied migrations are preserved.

## Open Questions

None. The ledger authority, no-data behavior, provider/model traceability, and UTC daily granularity are fixed by this design without requiring a new operator decision.
