## 1. Gate payload and presentation

- [x] 1.1 Trace every active human-gate producer, serializer, current-gate resolver, API projection, and UI consumer; identify which producers supply native options and which create system options.
- [x] 1.2 Extend the existing transactional Run notification from both canonical persistence writers to fire on stage changes and active-gate creation, replacement, or resolution even when the stage is unchanged; keep the compact payload unchanged, emit only after commit, and emit nothing for rollback or no-op writes.
- [x] 1.3 Extend the active `human_payload` contract with Spanish question/option presentation while preserving exact source wording, option source, stable IDs, and original response values; do not add a table or migration.
- [x] 1.4 Update gate-producing workflows to provide faithful Spanish presentation in the same handoff for every gate type; preserve native OpenSpec questions/options unchanged and do not add a translation-agent invocation.
- [x] 1.5 Update `Trabajo actual` to render Spanish question and choices, show the exact original text when it differs, and submit only the original stable response value; remove the raw-only display/selection path.
- [x] 1.6 Keep the current gate available across navigation, reload, and stale refresh; clear it only after a successful authoritative API projection confirms that exact gate is resolved.

## 2. Focused regression coverage

- [x] 2.1 Add PostgreSQL repository/integration tests proving stage-unchanged gate creation, replacement, and resolution publish the existing bounded notification after commit, while rollback and no-op writes publish none.
- [x] 2.2 Add backend tests proving gate payload construction and API projection preserve original question/options/source and carry the Spanish presentation without changing response values or resolved-gate audit history.
- [x] 2.3 Add frontend tests proving Spanish text is displayed, source text remains available when different, option selection submits the original value, and stale/resolved gates are not shown as current.
- [x] 2.4 Retire or update only tests for the replaced raw-only gate rendering and selection behavior; retain coverage for native option fidelity, authorization, idempotency, and gate resolution.

## 3. Real integration and browser E2E

- [x] 3.1 Using PostgreSQL test infrastructure, run the scheduler and API as separate processes; persist a real test Run gate to `HUMAN_REQUIRED` without changing `current_stage` and observe the committed notification, authenticated SSE event, and authoritative Runs API projection.
- [x] 3.2 Run browser E2E with an authenticated operator view; prove the same-stage gate appears within five seconds without manual reload, displays Spanish and exact original source text, and survives SSE reconnect/navigation while still pending.
- [ ] 3.3 Select a Spanish-rendered native option in the browser; observe that the exact original response value reaches the API, the gate is durably resolved, and the resolved gate does not reappear after refresh. Operator deferred this validation until production deployment; verify the deployed candidate before closure.
- [ ] 3.4 Capture the invocation, PostgreSQL/SSE/API/browser results, effects, relevant test suites, strict OpenSpec validation, and immutable candidate SHA; do not describe mocked event tests as E2E evidence.
