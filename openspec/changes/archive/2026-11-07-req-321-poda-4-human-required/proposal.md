## Why

During execution of Run `749b75de-adaf-481d-9a84-32c832934f04` on Issue #301, the mini-me control plane experienced three critical human gate breakdowns:
1. `Explore` saved a verified `HUMAN_REQUIRED` checkpoint with questions and options into `stop_details.explore_checkpoint`, but the main `orchestration_runs` table left `human_gate` and `stop_outcome` empty, causing the API to reject the operator's response with `HTTP 409 Conflict` while the UI misleadingly displayed *"Sin anomalías reportadas"*.
2. After resolving an earlier gate and transitioning to a later stage, the resolved Explore gate resurfaced as a "zombie" generic prompt in the UI.
3. In `IMPLEMENTING` (`Apply`), when recovery attempts were exhausted (`attempts=3/3, no_progress=2`), the UI surfaced an unformatted, unhelpful English error message without explaining what failed, what tasks remained pending, or what decision was required, while still claiming *"Sin anomalías reportadas"*.

This change addresses these systemic flaws by establishing a single durable source of truth in PostgreSQL for human gates across all workflow stages, providing clear, actionable Spanish explanations with full diagnostic context, and ensuring resolved gates are permanently retired without 409 rejections or zombie reappearances.

## What Changes

- **Single Durable Source of Truth for Human Gates**: Unify stage checkpoints (Explore, Propose, Apply, Verify) with `orchestration_runs.human_gate`, `stop_outcome`, and `stop_details.human_payload`. Ensure the API `/api/v1/orchestration/runs` projects the active gate accurately.
- **Accurate Gate Admission and Idempotency**: Ensure `/api/v1/projects/{project}/requests/run` (and `/api/v1/orchestration/runs/{run_id}/human-gate/response`) recognizes any valid pending human gate, accepts and persists operator responses once in PostgreSQL, and rejects with 409 only when truly no active gate exists.
- **Permanent Retirement of Resolved Gates**: When an operator response is accepted, atomically mark the gate resolved, clear pending gate state, and prevent resolved checkpoints from resurfacing after stage progression, page reloads (`F5`), or SSE reconnects.
- **Actionable Spanish Presentation in UI («Trabajo actual»)**:
  - Eliminate the contradictory *"Sin anomalías reportadas"* state when a Run is in `NEEDS_HUMAN` or blocked waiting on operator action.
  - Render an actionable Spanish explanation detailing what happened, why the run stopped, what decision is required, and the impact of each option.
  - Preserve authentic native OpenSpec questions and options verbatim; when source text is in English, provide an accompanying Spanish contextual explanation.
  - For optionless questions, supply structured, labeled agent suggestions while preserving a free-text input field so operator authority is never usurped.
  - In Apply recovery exhaustion, present the attempt count vs. ceiling (e.g. 3/3), pending task lists (e.g. 3.2, 4.1), test execution results, and candidate SHA identity. If error logs are unavailable, explicitly declare their absence rather than fabricating success.
- **Real E2E Playwright Verification**: Add real browser E2E test coverage asserting the complete `UI → FastAPI → PostgreSQL → UI` lifecycle without mocking the scheduler or agent execution loop.

## Capabilities

### Modified Capabilities
- `openspec-orchestration-continuity`: Unify stage checkpoints with durable `human_gate` in PostgreSQL, eliminate 409 rejection of valid checkpoints, ensure atomic gate resolution, and guarantee resolved gates never resurface across stage transitions or reloads.
- `pwa-runs-and-pipeline-observability`: Present actionable Spanish explanations, diagnostic context (attempts, tasks, tests, candidate identity), verbatim native options, agent suggestions, and free-text inputs in «Trabajo actual», eliminating false "Sin anomalías reportadas" messages during active human gates.

## Impact

- `src/minime/services/orchestration_coordinator.py`: Refactor checkpoint capture and response ingestion to keep `human_gate`, `stop_outcome`, and stage checkpoints strictly synchronized.
- `src/minime/api/app.py`: Ensure run projection exposes the active human payload from either the current stage checkpoint or the run record without returning ghost gates or dropping valid checkpoints.
- `src/minime/web/src/app/features/trabajo-actual/` (and related Angular components): Update human gate cards to display Spanish context, diagnostic metrics, native options, suggestions, and accurate attention states.
- `tests/test_human_gate_current_payload.py` & Playwright E2E suite: Add deterministic unit, integration, and browser tests verifying complete gate presentation, response submission, and reload persistence.
