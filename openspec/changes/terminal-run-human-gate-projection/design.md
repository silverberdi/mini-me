## Context

`GET /api/v1/orchestration/runs` normalizes each run's stage and gate fields in `list_orchestration_runs`. It currently marks a run human-required from the current payload, `human_gate`, or `stop_outcome` without first excluding terminal runs. The endpoint already chooses its non-human status in the existing branch after this calculation.

## Goals / Non-Goals

**Goals:**
- Ensure terminal outcomes and completed stage take precedence over stale human-gate signals in the endpoint's `is_human_required` calculation.
- Preserve current gate behavior for non-terminal runs.
- Cover the reported completed-run regression with focused endpoint tests.

**Non-Goals:**
- Clearing or migrating stale values in persisted Run records.
- Changing payload filtering, status mapping, human-gate response behavior, dashboard/PWA code, or other run projections.

## Decisions

- Compute terminality locally in `list_orchestration_runs` from `stop_outcome` in `COMPLETED`, `FAILED`, `CANCELLED`, or `current_stage == COMPLETED`.
- Gate the existing `bool(human_payload) or human_gate == NEEDS_HUMAN or stop_outcome == NEEDS_HUMAN` expression with `not is_terminal`. This preserves the non-terminal semantics and changes only precedence for terminal records.
- Extend focused API projection coverage in `tests/test_human_gate_current_payload.py`, where current payload and resolved-checkpoint behavior are already exercised. Include the reported completed/stale-gate combination and terminal variants from the spec; retain existing tests that assert genuine non-terminal HUMAN_REQUIRED behavior.

Alternative: clear stale `human_gate` in storage. Rejected because Issue #285 explicitly limits the fix to projection and excludes database housekeeping.

## Risks / Trade-offs

- `[A terminal record with a stale current-stage payload remains visible in stop_details]` → Its status is still non-human-required; payload cleanup is deliberately outside this projection-only change.
- `[An unlisted terminal outcome could still be treated as non-terminal]` → The terminal set is explicit in the spec and covered by focused tests.
