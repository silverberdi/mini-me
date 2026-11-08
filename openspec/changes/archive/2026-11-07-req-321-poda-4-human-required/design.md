## Context

See `proposal.md` for background and problem motivation.

In the current codebase, orchestration runs store state in the PostgreSQL `orchestration_runs` table (`human_gate`, `stop_outcome`, and `details` JSONB column). When a stage completes with `HUMAN_REQUIRED`, the coordinator records stage-specific dictionary structures (such as `details["explore_checkpoint"]`, `details["propose_human_required"]`, or `details["apply_attempt"]`). In Run `#301`, the Explore stage populated `details["explore_checkpoint"]["human_payload"]` but left `orchestration_runs.human_gate` and `stop_outcome` as `NULL`. 

Consequently:
- `GET /api/v1/orchestration/runs` projected the run as `RUNNING` with no active human gate, causing the frontend to report *"Sin anomalías reportadas"*.
- `POST /api/v1/projects/{project}/requests/run` checked `run.human_gate == HumanGate.NEEDS_HUMAN`, found `NULL`, and rejected the valid operator response with `HTTP 409 Conflict: There is no current human gate to answer`.
- When an earlier checkpoint resolved, residual stage JSON keys remained in `details`, causing subsequent stages or reloads to resurrect stale gate questions ("zombie gates").
- Apply recovery exhaustion emitted raw English strings without actionable Spanish context or task diagnostics.

## Goals / Non-Goals

**Goals:**
- Provide a single canonical authority for active human requests across all workflow stages (Explore, Propose, Apply, Verify).
- Synchronize PostgreSQL `human_gate`, `stop_outcome`, and `details.human_payload` atomically upon any `HUMAN_REQUIRED` outcome.
- Ensure the API projection and response endpoint treat any verified active stage checkpoint as valid, eliminating 409 false rejections.
- Atomically record accepted responses into an audit trail (`details["resolved_human_gates"]`) and clear active gate fields so resolved gates can never resurface.
- Present actionable Spanish context, verbatim native options, distinct agent suggestions, free-text inputs, and diagnostic metrics (attempts, pending tasks, candidate SHA, test results) in «Trabajo actual».
- Verify the complete end-to-end lifecycle in real Playwright browser tests against FastAPI and PostgreSQL.

**Non-Goals:**
- Creating new database tables or altering table schemas (existing `human_gate`, `stop_outcome`, and `details` JSONB are fully sufficient).
- Changing external LLM agent behaviors or OpenSpec CLI binaries.
- Implementing automated auto-approval of human-reserved decisions.

## Decisions

### Decision 1: Unified Active Gate Resolver in Coordinator and Run Entity
- **Approach**: Define a single method/helper `get_active_human_payload(run)` that evaluates the run's current stage and status. If the run is active and either has `human_gate == NEEDS_HUMAN` or its current stage checkpoint (Explore, Propose, Apply, Verify) holds an unresolved `HUMAN_REQUIRED`, it returns the canonical gate payload.
- **Resolution Handling**: When `register_operator_response` or `execute_project_request` accepts an operator input:
  1. The response is appended to `details["resolved_human_gates"]` with timestamp, stage, and operator identity.
  2. The active checkpoint status is marked `RESOLVED`.
  3. `run.human_gate` and `run.stop_outcome` are reset to `NULL` (or transitioning status).
  4. The changes are committed atomically to PostgreSQL.
- **Alternatives Considered**: Creating a separate `human_gates` relational table. Rejected under KISS/YAGNI because `orchestration_runs` already owns run lifecycle and JSONB transactions ensure atomic consistency.

### Decision 2: API Run Projection and Response Alignment
- **Approach**: In `src/minime/api/app.py`:
  - `list_orchestration_runs` projects `human_gate = "HUMAN_REQUIRED"` and `status = "PAUSED"` if `get_active_human_payload(run)` returns an active payload.
  - The request response endpoint checks `get_active_human_payload(run) is not None` rather than strictly requiring a legacy enum match.
  - If no active payload exists, it returns 409; if an active payload exists, it accepts the response and continues the coordinator workflow.

### Decision 3: Actionable Spanish Presentation and Diagnostic Details in UI
- **Approach**: In `frontend/src/app/features/trabajo-actual/`:
  - When `run.human_gate === 'HUMAN_REQUIRED'`, render a dedicated attention banner suppressing any "Sin anomalías" status.
  - Display the Spanish explanation and preserve verbatim OpenSpec options.
  - In Apply recovery exhaustion, display the attempts counter (e.g. `3/3`), the hard ceiling, the list of pending tasks (e.g. `3.2, 4.1`), test results, and candidate commit SHA.
  - If error logs are missing, explicitly render a disclaimer that diagnostics are absent rather than offering a blind "Continuar" action.

### Decision 4: Playwright E2E Suite Integration
- **Approach**: Add Playwright E2E tests validating:
  1. Active Explore `HUMAN_REQUIRED` rendering with Spanish explanation and options in Chromium headless.
  2. Successful option selection and submission.
  3. Verification of PostgreSQL state and immediate gate clearance.
  4. Verification that page reload (`F5`) does not resurrect the answered gate.

## Risks / Trade-offs

- **[Risk] Existing unit tests relying on separate gate field state** → Update focused tests in `tests/test_human_gate_current_payload.py` to assert the unified active payload contract.
- **[Risk] Frontend bundle size limit in Angular build** → Use native HTML/CSS and lightweight components without introducing heavy third-party UI dependencies.
- **[Risk] Reconnection / SSE race conditions** → Ensure the frontend optimistic response state reconciles with the authoritative backend projection on SSE push.
