## 1. Database Schema & Migration

- [x] 1.1 Add `OpenRouterBudgetPolicyModel`, `OpenRouterPricingSnapshotModel`, `BudgetReservationModel`, and `BudgetLedgerModel` SQLAlchemy models in `src/minime/db/models.py` and domain models in `src/minime/domain/models.py`.
- [x] 1.2 Create Alembic migration `006_openrouter_budget.py` (down revision `005_provider_resilience`) creating `openrouter_budget_policies`, `openrouter_pricing_snapshots`, `budget_reservations`, and `budget_ledger` tables with transactional indexes.
- [x] 1.3 Extend `src/minime/config.py` with `OpenRouterConfig` and `BudgetConfig` with default no-spend values (`enabled=False`, `$0.00` caps) and policy synchronization logic preserving `is_breached` state.
- [x] 1.4 Add new domain events (`FALLBACK_INVOKED`, `BUDGET_RESERVED`, `BUDGET_SETTLED`, `BUDGET_CAP_EXCEEDED`, `BUDGET_BREACH_DETECTED`, `FALLBACK_MODEL_SELECTED`, `FALLBACK_DENIED`) and enums in `src/minime/domain/enums.py`.

## 2. Authoritative Budget Policy & Reservation Service

- [x] 2.1 Implement `BudgetService` in `src/minime/services/budget_service.py` with transactional row locking on `openrouter_budget_policies` (`SELECT ... FOR UPDATE`), computing daily and monthly UTC headroom encumbering committed spend, active reservations, and all historical `UNRESOLVED` reservations using exact Decimal math.
- [x] 2.2 Implement true maximum-cost reservation calculation (`maximum_billable_request_usd`) in `BudgetService.reserve_budget()` binding input token bounds, max output token limits, and durable `openrouter_pricing_snapshots` records.
- [x] 2.3 Implement settlement protocol in `BudgetService.settle_reservation()` to record immutable `budget_ledger` entries, transition reservations to `SETTLED`, and release unused reservation headroom.
- [x] 2.4 Implement fail-safe unknown-cost handling in `BudgetService.mark_unresolved()` retaining 100% of reserved amounts across window boundaries, and `SETTLEMENT_BREACH` handling to set `is_breached=true` when actual cost exceeds reservation.
- [x] 2.5 Add unit and concurrency integration tests in `tests/test_budget_service.py` verifying policy row locking, true maximum cost calculations, cross-boundary unresolved encumbrance, fail-closed denials, and breach persistence.

## 3. Canonical Model Identity & Independence Policy

- [x] 3.1 Implement `CanonicalModelRegistry` and fail-closed normalization logic in `src/minime/services/model_identity_service.py` to map OpenRouter model strings and routing aliases to proven canonical `(provider, family, architecture)` identities.
- [x] 3.2 Implement `ModelIndependencePolicy` in `src/minime/services/model_independence_policy.py` ensuring `model_reviewer != model_implementer` by canonical identity and family ("Qwen does not review Qwen"), failing closed if distinct identity cannot be proven.
- [x] 3.3 Add unit tests in `tests/test_model_identity.py` verifying alias resolution, same-family self-review rejection, unprovable identity rejection, and distinct model approval.

## 4. OpenRouter Adapter & DeepSeek Isolation

- [x] 4.1 Implement `OpenRouterAdapter` in `src/minime/adapters/openrouter_adapter.py` conforming to `schemas/provider-result.schema.json` and role schemas with async HTTP client, timeout handling, outcome classification, and complete secret redaction.
- [x] 4.2 Implement pinned exact route enforcement and pricing snapshot binding in `OpenRouterAdapter.verify_authorization_envelope()`, rejecting uncontrolled auto-routing endpoints and route substitution prior to dispatch.
- [x] 4.3 Enforce physical credential isolation ensuring `DEEPSEEK_API_KEY` is never passed or referenced in `OpenRouterAdapter`.
- [x] 4.4 Add unit tests in `tests/test_openrouter_adapter.py` verifying outcome normalization, pinned route enforcement, credential redaction in logs/events, and timeout handling.

## 5. Strict 10-Point Eligibility Evaluator & Scheduler Integration

- [x] 5.1 Implement `OpenRouterEligibilityEvaluator` in `src/minime/services/openrouter_eligibility.py` evaluating all 10 eligibility conditions before fallback invocation.
- [x] 5.2 Integrate fallback orchestration into `src/minime/services/capacity_lifecycle_service.py` and `src/minime/services/execution_pipeline.py` to invoke OpenRouter fallback during `DRAIN` mode only when dual-primary exhaustion is verified, all 10 eligibility conditions pass, and atomic reservation succeeds.
- [x] 5.3 Ensure OpenRouter outcomes do not alter primary provider health records and OpenRouter success never returns the scheduler to `RUN` mode.
- [x] 5.4 Enforce strict prohibition on admitting new `READY` changes into OpenRouter fallback during `DRAIN` or `WAIT` modes.
- [x] 5.5 Add integration tests in `tests/test_scheduler_drain_fallback.py` verifying the 10-point eligibility rule, dual vs single primary exhaustion, prohibition of new `READY` work, and primary health decoupling.

## 6. REST API & CLI Observability

- [x] 6.1 Implement REST API routes in `src/minime/api/app.py` for `GET /budget/usage`, `GET /projects/{project_id}/budget`, and `GET /providers/openrouter/status` exposing committed spend, active reservations, remaining headroom, unresolved settlements, and policy breach status with secret redaction.
- [x] 6.2 Implement CLI commands in `src/minime/cli/main.py` for `minime budget status` and `minime providers openrouter`.
- [x] 6.3 Add API and CLI tests in `tests/test_budget_api.py` and `tests/test_budget_cli.py` verifying output formatting, breach indicators, and secret redaction.

## 7. Verification & OpenSpec Validation

- [x] 7.1 Run full pytest suite (`pytest tests/`) validating all unit, integration, and contract tests.
- [x] 7.2 Run `openspec validate 006-openrouter-budgeted-drain-fallback --strict` and `openspec validate --all` to verify change validity and delta spec consistency.
