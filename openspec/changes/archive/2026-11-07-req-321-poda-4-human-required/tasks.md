## 1. Backend and Durable State Unification

- [x] 1.1 Implement unified active gate resolver `get_active_human_payload(run)` across all stages (Explore checkpoint, Propose clarification, Apply recovery exhaustion, review escalation, PR1 acknowledgement).
- [x] 1.2 Synchronize PostgreSQL `human_gate`, `stop_outcome`, and `details.human_payload` atomically whenever any stage yields `HUMAN_REQUIRED`.
- [x] 1.3 Update response admission in coordinator and API (`POST /api/v1/projects/{project}/requests/run`) to recognize any active stage gate and accept valid operator responses without HTTP 409 Conflict.
- [x] 1.4 Implement atomic gate resolution: record operator answer into `details["resolved_human_gates"]`, mark the checkpoint resolved, and clear active gate fields so past gates never resurface.
- [x] 1.5 Enrich Apply recovery exhaustion payload with structured diagnostic context (attempts vs. ceiling, pending tasks list, test execution result, candidate SHA) and actionable Spanish explanation.

## 2. Frontend and Observability («Trabajo actual»)

- [x] 2.1 Update «Trabajo actual» and Dashboard attention cards to suppress "Sin anomalías reportadas" whenever a Run has an active `HUMAN_REQUIRED` gate.
- [x] 2.2 Render actionable Spanish explanations, verbatim native OpenSpec options, clearly labeled agent recommendations, and free-text response inputs.
- [x] 2.3 Render diagnostic details for exhausted Apply recovery: attempt count/ceiling, pending tasks, candidate commit SHA, and explicit disclosure when execution logs are unavailable.
- [x] 2.4 Verify optimistic response submission, progress indication, and reconciliation with authoritative backend state upon reload (`F5`) or SSE update.

## 3. Verification and Real E2E Evidence

- [x] 3.1 Update and run focused unit and integration test suite (`tests/test_human_gate_current_payload.py`) asserting multi-stage gate projection, response idempotency, and elimination of 409 errors.
- [x] 3.2 Implement and execute real browser E2E test in Playwright (`frontend/tests/`) verifying complete `UI → FastAPI → PostgreSQL → UI` interaction: prompt display, response submission, database update, and reload stability.
- [x] 3.3 Run PR validation suite and confirm all CI checks, typing, and tests pass with zero regressions.
