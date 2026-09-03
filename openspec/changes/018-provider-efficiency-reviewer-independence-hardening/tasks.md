# Tasks: 018.1 Provider Efficiency & Reviewer Independence Hardening

## 1. Domain Models, Database Schema & Migration
- [x] 1.1 Add `TaskClass`, `PremiumProviderReasonCode`, `AttemptProductivityClass`, and new `EventType` values in `src/minime/domain/enums.py`.
- [x] 1.2 Define `ProviderEfficiencyMetrics` and associated data structures in `src/minime/domain/models.py`.
- [x] 1.3 Add `ProviderEfficiencyMetricsModel` table and candidate/attempt telemetry fields in `src/minime/db/models.py`.
- [x] 1.4 Create Alembic revision `016_provider_efficiency_telemetry.py` for `provider_efficiency_metrics`.
- [x] 1.5 Implement repository interfaces and InMemory / PostgreSQL repository implementations in `src/minime/domain/interfaces.py` and `src/minime/db/repository.py`.

## 2. Deterministic Task Classification & Multi-Factor Provider Selection
- [x] 2.1 Implement `TaskClassifier` in `src/minime/services/task_classifier.py` for deterministic task classification.
- [x] 2.2 Implement `ProviderPolicyService` in `src/minime/services/provider_policy_service.py` enforcing Mandatory Rules A, E, F, H.
- [x] 2.3 Implement unit tests in `tests/test_provider_efficiency_and_reviewer_independence.py`.

## 3. Retry Budget, Same-SHA Anti-Loop & Lightweight Reconciliation
- [x] 3.1 Implement Mandatory Rule B (1 normal + 1 corrective retry) and Mandatory Rule C (same-SHA anti-loop suppression) in `src/minime/services/continuation_engine.py`.
- [x] 3.2 Implement `LightweightReconciliationService` in `src/minime/services/lightweight_reconciliation_service.py` for fast in-process `tasks.md` and evidence sync.
- [x] 3.3 Implement unit tests in `tests/test_provider_efficiency_and_reviewer_independence.py`.

## 4. Reviewer Independence & CHECKS_FAILED Remediation Routing
- [x] 4.1 Update `AuthorshipService` in `src/minime/services/authorship_service.py` to track candidate material authors and exclude them from review eligibility.
- [x] 4.2 Update `OrchestrationService` and `ExecutionPipelineService` to route `CHECKS_FAILED` through canonical remediation and enforce reviewer independence.
- [x] 4.3 Replace tight polling loops with async process wait and bounded backoff.
- [x] 4.4 Implement unit tests in `tests/test_provider_efficiency_and_reviewer_independence.py`.

## 5. PostgreSQL Efficiency Telemetry, API, TUI & PWA Integration
- [x] 5.1 Implement telemetry recording and aggregation logic in `ExecutionPipelineService` and `OrchestrationService`.
- [x] 5.2 Expose efficiency endpoints in `src/minime/api/app.py` and update `DashboardService`.
- [x] 5.3 Implement compact Provider Efficiency view in Textual TUI (`src/minime/tui/client.py`).
- [x] 5.4 Implement Provider Efficiency telemetry panel and CSS styles in PWA (`src/minime/static/js/components/efficiency_panel.js`).
- [x] 5.5 Implement contract and integration tests in `tests/test_provider_efficiency_and_reviewer_independence.py`.

## 6. Verification & Proving Pilot
- [x] 6.1 Execute full test suite (`pytest`) and ChecksRunner across all tests.
- [x] 6.2 Execute live proving pilot verifying hard efficiency gates (0 AG routine implementations, 0 unreasoned AG assignments, 0 same-SHA duplicate retries, 0 bookkeeping LLM retries, 0 reviewer-independence violations, >= 75% Codex productive ratio, >= 60% self-hosting native).
- [x] 6.3 Verify telemetry persistence in PostgreSQL and visual presentation in TUI and PWA.
- [x] 6.4 Mark Stage 018.1 complete and gate 018.2.
