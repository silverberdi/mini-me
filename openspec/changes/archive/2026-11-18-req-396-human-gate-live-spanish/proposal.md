## Why

During the Boxio Run recorded in Issue #396, the durable human gate became visible in the PWA only after a manual reload, and its question and choices were shown in English. Issue #366 delivered the PostgreSQL-to-API SSE bridge for stage changes, but the current notifier does not publish when a gate is created, replaced, or resolved without a stage change. This Change extends that same path for gate lifecycle changes and completes the Spanish presentation so operators can see and respond to the current gate without changing its meaning or authority.

## What Changes

- Present the current human gate's question and actionable choices in clear Spanish while preserving the original question, native options, source, and stable response values as auditable data.
- Ensure choosing a Spanish display label submits the original option response value; translated display text SHALL NOT become authorization input.
- Keep a pending gate visible from the authoritative Run projection through navigation, reconnection, and refresh until the backend durably confirms that exact gate's resolution.
- Extend Issue #366's transactional PostgreSQL notification trigger to also publish the existing compact Run notification when the active gate is created, replaced, or resolved, even if the workflow stage is unchanged; reuse its authenticated SSE stream, `run.transition`/`run.resync` handling, and authoritative Run API projection. Do not add another event broker, event stream, polling loop, translation service, or durable state store.
- Add real integration/browser evidence for a scheduler-originated `HUMAN_REQUIRED` transition, Spanish presentation, exact response submission, reconnect recovery, and durable resolution.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `pwa-capacity-cards-and-reactive-state`: specify timely display and recovery of a durable human gate through the existing SSE and Run projection path, including retention until durable resolution.
- `openspec-orchestration-continuity`: specify Spanish operator-facing gate text alongside the verbatim original question/options and require responses to preserve the original option value and authorization semantics.

## Impact

- Backend: existing human-gate payload construction and Run projection in `orchestration_coordinator.py` and `api/app.py`; the canonical PostgreSQL Run writers and Issue #366 notification adapter must publish a compact refresh hint for gate lifecycle changes without leaking gate text.
- Frontend: existing `RefreshService` and `TrabajoActualComponent` gate rendering and option selection.
- Persistence: reuse the existing `stop_details.human_payload` JSON and resolved-gate audit; no new table or migration is expected.
- Verification: focused payload/selection tests and a PostgreSQL-backed E2E with separate scheduler and API processes plus a browser client, exercising the already merged Issue #366 bridge. No Boxio Run mutation or production deployment is part of this Change.
