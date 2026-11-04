## Context

See `proposal.md` for motivation. `GET /api/v1/projects` already returns each project's `execution_policy`; the existing refresh service periodically replaces the PWA's project list with this response. `effective_pause` is project-specific, while `global_pause` is present in project policy payloads when the system-wide pause is active. The existing project `status` represents administrative lifecycle state and can remain `ACTIVE` while execution is paused.

## Goals / Non-Goals

**Goals:** Present the two existing pause flags in Proyectos and let the existing refresh update their displayed values.

**Non-Goals:** Change pause/resume controls, backend or admission behavior, persistence, or other views.

## Decisions

- Extend the frontend project policy type with the optional boolean pause fields and read them directly from `execution_policy`. This models the API's existing payload without adding client-owned state.
- Render a per-project “Pausado” indicator from `effective_pause`, independent of administrative `status`.
- Render a distinct system-level global pause indicator when any current project payload has `global_pause === true`. This uses the existing refreshed project collection and avoids a second request or a new state source. If no project payload reports the flag, no global pause indicator is shown.
- Keep the existing refresh service and its timing unchanged. Its replacement of the project collection naturally causes the indicators to reflect updated payload values.
- Add focused frontend coverage for true/false flags, administrative status remaining independent, global pause, and updated values after refresh; run the frontend test suite and production build as verification.

## Risks / Trade-offs

- [The global flag is not present in any returned project payload] → No global indicator can be derived from this API response; confirm the existing endpoint propagates `global_pause` and cover the populated-payload case. This change does not add a backend source.
- [A project's administrative status is mistaken for execution pause] → Render execution pause from the policy flags in a separate indicator and preserve the existing status display.

## Migration Plan

No data migration is required. Deploy the frontend change; rollback consists of reverting the frontend commit.
