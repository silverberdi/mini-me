## Context

See `proposal.md` for the incident and intended behavior. The current runs endpoint already projects inactive runs as `COMPLETED` unless a persisted human signal overrides the status. Its `is_human_required` predicate excludes terminal markers but not `is_active=false`. In Trabajo actual, the default selector checks active runs first, then accepts matching statuses or the first run without requiring activity. The existing explicit `?run=` selection is separate from that fallback.

## Goals / Non-Goals

**Goals:**
- Make active state a necessary condition for the API's `HUMAN_REQUIRED` projection.
- Keep Trabajo actual's default selection within active runs; select no default when there is no active run.
- Preserve the current explicit run selection and all active human-gate behavior.

**Non-Goals:**
- Changing durable run state, human-gate resolution, issue status, Request admission/reactivation, or production data.
- Redesigning historical run navigation or other run projections.

## Decisions

- Add `r.is_active` to the existing `is_human_required` guard. This is the narrowest backend correction: the endpoint's existing fallback already reports an inactive run as `COMPLETED`, so stale gate fields no longer override it.
- Remove inactive status/first-run fallbacks from `targetRun`; when no explicit run is selected, resolve to an active run or `null`. This prevents stale API labels or residual gate details from making an inactive run the default current work.
- Keep the explicit `?run=` selection path unchanged. The backend projection for an inactive run is now non-human, and the frontend's existing terminal-state guard suppresses the human gate for that selected run.
- Add a backend regression for an inactive non-terminal run with residual `NEEDS_HUMAN`, plus a frontend regression for a run list with no active run. Verify the normal active human-gate path remains intact and run the frontend production build to catch TypeScript errors.

## Risks / Trade-offs

- [Risk] A caller may have relied on Trabajo actual's implicit selection of the newest historical run when no run is active → return the existing empty-state view instead; explicit `?run=` navigation remains available.
- [Risk] Backend and frontend fixes could diverge → tests cover each observable behavior, and the frontend build verifies the component compiles.
