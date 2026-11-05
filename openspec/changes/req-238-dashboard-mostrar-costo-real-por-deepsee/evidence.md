# Implementation evidence

## Candidate identity

- Git HEAD: `c163d374f75d910019d0a7f912380de9e9ae5d49`
- Candidate worktree fingerprint recorded with the PostgreSQL E2E: `61f47a1ffa317e94fce4e6463f3707e82eee8975c5b61f892589edd6a80f35b0`
- Structured database/API/UI capture: `evidence/dashboard-cost-postgres-e2e.json`
- Captured rendered DOM: `evidence/dashboard-cost-browser-dom.html` (SHA-256 `a3af5103b7f5e9e7569a369ca1a9793683267004e0cedb807dd9ff23b3d91942`)

## Focused regression (task 4.3)

Commands recorded by the final capture:

```text
MINIME_TEST_DATABASE_URL=$MINIME_DATABASE_URL python -m pytest -q -rs tests/test_dashboard_cost.py tests/test_dashboard_cost_postgres_e2e.py tests/test_dashboard_security.py tests/test_dashboard_stale_isolation.py tests/test_dashboard_ui.py
npm --prefix frontend test
npm --prefix frontend run build
```

Observed results in the capture: backend `11 passed` (including the PostgreSQL E2E; no skip), frontend `28 passed`, and Angular build exit code `0`. The build emitted the recorded NG8107 and bundle-budget warnings (517.52 kB against a 512 kB budget); they did not fail the build. `git diff --check` and `openspec validate req-238-dashboard-mostrar-costo-real-por-deepsee --strict` both recorded exit code `0`.

## PostgreSQL-to-Dashboard-to-UI E2E (tasks 4.1–4.2)

The captured E2E records four settled ledger rows observed in PostgreSQL before the Dashboard request, dated August 1, 2026: DeepSeek Direct at `0.123456` USD, OpenRouter at `1.200000` USD, and two OpenRouter rows with missing/unrecognized models totaling `0.020000` USD. The authenticated Dashboard endpoint returned HTTP `200`; its payload retained both provider identities, model detail, exact USD precision, and source timestamps. The unknown OpenRouter model amounts remained in the provider total under `Modelo no identificado`.

The Angular production build was rendered in Chrome headless at 1280×900 using the captured Dashboard response unchanged. The recorded DOM contains both provider labels, the exact amounts and model labels, the unidentified-model bucket, and the SVG chart polyline. The capture records browser-render exit code `0` and the DOM SHA-256 above.

The E2E fixture cleanup recorded zero remaining project, job, ledger, reservation, and OpenRouter pricing-snapshot rows for its test data. The PostgreSQL E2E did execute successfully; the earlier note saying it was skipped and tasks 4.1–4.2 remained pending was stale and is superseded by this final capture.
