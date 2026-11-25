# Tasks

## 1. Backend payload contract

- [x] 1.1 Inventory the current `NativeOrchestrationCoordinator` and Runs projection writers/consumers for `stop_details["human_payload"]`, and record the exact response/redaction boundary in the implementation diff; verify no second payload authority is introduced.
- [x] 1.2 Implement bounded Spanish enrichment for active `proposal_feasibility` and `apply_escalation` gates with `summary_es`, parsed `pending_items`, and `options_es`, while preserving original question/option values and fail-closed behavior; verify with focused assertions in `tests/test_native_propose_lifecycle.py` and `tests/test_human_gate_current_payload.py`.
- [x] 1.3 Verify explicitly that `summary_es`, every `pending_items` entry, and every `options_es` value/description pass through `NativeOrchestrationCoordinator._safe_human_payload` and the existing `minime.logging.redact_secrets` filter: inject secret-like values, assert the raw values are absent and the established redaction markers are present in both durable `stop_details["human_payload"]` and the Runs projection; verify with focused assertions in `tests/test_native_propose_lifecycle.py` and `tests/test_human_gate_current_payload.py`.
- [ ] 1.4 Cover malformed, ambiguous and legacy payload inputs without fabricated decisions or transitions; verify the relevant focused backend tests pass with `python -m pytest tests/test_native_propose_lifecycle.py tests/test_human_gate_current_payload.py tests/test_human_gate_current_payload_postgres_e2e.py`.

## 2. Trabajo actual presentation

- [x] 2.1 Add a small frontend normalizer for enriched and legacy Human Gate payloads that splits and cleans semicolon-delimited strings without mutating response values; verify unit cases for empty, malformed and historical payloads.
- [x] 2.2 Replace the monolithic Human Gate rendering in `frontend/src/app/features/trabajo-actual/` with the Spanish summary, titled warning bullets, action-oriented option cards and collapsed `Detalles técnicos y auditoría` disclosure; verify the primary DOM hides raw audit data until expansion and preserves gate identity/context.
- [x] 2.3 Preserve the existing response handler, optimistic feedback, action identifiers and refresh/SSE reconciliation; verify focused frontend unit coverage for option rendering and response-state behavior.
- [x] 2.4 Remove the superseded monolithic rendering branch after parity is covered, retain historical compatibility parsing and document the final Removal Ledger evidence; verify static search finds no orphaned active caller or duplicate presentation authority.

## 3. Real browser and response integration

- [ ] 3.1 Add or update an isolated Playwright fixture/spec for a structured Human Gate in Trabajo actual, covering both technical disclosure and Spanish option presentation; verify with `npm --prefix frontend run test:e2e -- e2e/human-gate-structured-presentation.spec.ts` against the served Angular/FastAPI stack and configured Chromium.
- [ ] 3.2 In that real-browser scenario, select and submit an option and observe the existing response request plus the refreshed authoritative Run outcome; verify no simulated DOM-only transition is used and the backend state transition remains unchanged.
- [x] 3.3 Run focused frontend unit checks for the new normalizer/component behavior with `npm --prefix frontend run test -- tests/human-gate-structured-presentation.test.mjs tests/human-gate-current-payload.test.mjs` and retain the observable command output as candidate evidence.

## 4. Change verification

- [x] 4.1 Verify the delta against the exact candidate SHA with `openspec validate --change req-539-presentacion-clara-estructurada-y-en-esp --strict` and inspect the generated artifact/status output; correct only issues within this Change through the native workflow.
- [ ] 4.2 Verify the bounded backend tests, frontend unit tests and real-browser Playwright scenario after retirement of the old rendering path; record invocation, exit status, candidate SHA and observable UI/backend effects, failing closed if any required evidence is absent.
