## 1. Run API projection

- [x] 1.1 Gate `HUMAN_REQUIRED` projection on `is_active` in `list_orchestration_runs`, preserving the existing `COMPLETED` projection for inactive runs.
- [x] 1.2 Add a focused backend regression in `tests/test_human_gate_current_payload.py` for `is_active=false`, a non-terminal stage, and residual `NEEDS_HUMAN`; assert `COMPLETED`/not `HUMAN_REQUIRED` and preserve coverage that an active current gate remains `HUMAN_REQUIRED`.
- [x] 1.3 Run `python -m pytest -q tests/test_human_gate_current_payload.py` — 15 passed; the `pytest` executable was not on PATH, so Python module invocation was used.

## 2. Trabajo actual selection

- [x] 2.1 Change the default `targetRun` fallback to select only an active run and return no run when none is active; keep explicit `?run=` selection behavior unchanged.
- [x] 2.2 Add a focused frontend regression proving an inactive run with stale `HUMAN_REQUIRED` data is not selected as the default current run when there is no active run.
- [x] 2.3 Run `npm --prefix frontend test` (26 passed) and `npm --prefix frontend run build` (exit 0; Angular production build and TypeScript compilation passed).

## 3. OpenSpec validation

- [x] 3.1 Run `openspec validate inactive-run-human-gate-projection --strict`; validation passed.
