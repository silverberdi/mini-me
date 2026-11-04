## Why

Issue #262 reports that Trabajo actual can show a resolved proposal-review question after the Run reaches a later human gate, leaving the operator without the current decision or its choices. Each gate must publish and display its own durable question and options so the operator can respond to the decision that is actually blocking the Run.

## What Changes

- Persist the current question and options whenever the scoped human gates are reached: review escalation, Apply escalation, PR1 merge acknowledgement, and physical validation.
- Make the current gate payload authoritative for the Run projection and for the PWA; a payload from a prior gate must not be used as a fallback.
- Preserve the existing human gates, response authority, and response workflow.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-orchestration-continuity`: require each scoped gate to persist its current question and options as the active human request.
- `pwa-runs-and-pipeline-observability`: require Trabajo actual to show the active gate payload and keep the existing response path available.

## Impact

- Backend gate producers and Run serialization in `src/minime/services/orchestration_coordinator.py` and `src/minime/api/app.py`.
- Existing PostgreSQL `orchestration_runs.stop_details` JSON storage; no new durable entity is proposed.
- Human-gate rendering and payload selection in `frontend/src/app/features/trabajo-actual/trabajo-actual.component.ts`.
- Focused orchestration/API/PWA tests covering gate transitions and response behavior. No unrelated workflow stages or attention-inbox redesign.
