# Tasks

## 1. Ledger-to-dashboard contract

- [x] 1.1 Confirm the existing `budget_ledger` fields, settlement semantics, repository methods, Dashboard response contract, and current token/synthetic cost consumers; verify the inventory with targeted source searches and focused existing tests.
- [x] 1.2 Define the typed Dashboard cost projection for liquidated ledger entries, including provider, optional model, USD precision, source timestamp, UTC daily bucket, and the explicit no-data response `{ "status": "no_data", "providers": [], "series": [] }`; verify serialization against the existing API conventions without adding a new persistence authority.

## 2. Backend projection and API

- [x] 2.1 Implement the Dashboard read path using the existing unit-of-work ledger repository and verified liquidated entries only; verify unit tests reject Run-token-derived prices, reservations, unresolved usage, missing timestamps, and synthetic provider/model attribution.
- [x] 2.2 Expose the cost projection through the existing Dashboard API/read model with DeepSeek Direct and OpenRouter separation, recognized model detail, and a `Modelo no identificado` bucket for liquidated entries with a verified provider but null/unrecognized model; verify API tests assert exact USD precision, provider/model identity, timestamps, UTC aggregation, the no-data payload, inclusion in provider totals without model misattribution, and exclusion of entries with unknown provider identity.
- [x] 2.3 Preserve secret redaction, authorization, and existing Dashboard fields while adding the cost projection; verify the existing Dashboard security and regression suites remain green.

## 3. Dashboard UI

- [x] 3.1 Replace the Dashboard cost visualization's token/synthetic fallback with the API cost projection, rendering provider/model labels, liquidated USD values, precision, and timestamp-backed series; verify a UI test renders both DeepSeek Direct and OpenRouter fixtures correctly.
- [x] 3.2 Render an accessible Spanish “sin datos” state when no verified cost exists and suppress `0`, `CLI`, estimates, and default attribution; verify the no-data UI test checks the negative cases explicitly.
- [x] 3.3 Remove or migrate only the obsolete Dashboard cost consumers and assertions that read `run.tokens` for this chart; verify static reference searches and post-change regression tests show no active duplicate cost path.

## 4. Real integration evidence

- [x] 4.1 Add PostgreSQL-backed fixtures/seed data for settled DeepSeek Direct and OpenRouter ledger entries, including distinct models, null/unrecognized models, and timestamps; verify the database rows are observable before the Dashboard request and that unidentified-model amounts remain in the verified provider totals.
- [x] 4.2 Execute a real end-to-end path from PostgreSQL ledger records through the application Dashboard read endpoint to the rendered visualization; verify captured database input, HTTP response, provider/model/USD output, timestamps, and visible UI effects for both providers, and retain those captured inputs, response, rendered output, commands, exit codes, and candidate SHA as named evidence artifacts for OpenSpec Verify.
- [x] 4.3 Run the complete focused unit/API/UI/PostgreSQL regression suites after the obsolete token path is removed; verify exit code 0 and retain candidate SHA, commands, and outputs as evidence for official OpenSpec Verify.
