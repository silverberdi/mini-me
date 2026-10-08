## Context

Roadmap headings are canonical stage projections. Subordinate prose bullets are not independently executable unless they carry an explicit numeric/stage-prefixed key. Existing intake sweep selection does not distinguish roadmap planning projections from local backlog work.

## Decisions

1. List keys require a digit-led canonical identity (`022`, `021-work-intake`, `018.2-something`). Headings remain unchanged.
2. `IntakeService.sweep_unprepared_backlog_items` obtains a pure roadmap projection map and excludes ROADMAP items unless the currently observed projection is `READY`; completed and blocked projections are excluded. Non-ROADMAP selection is unchanged.
3. A narrow `reconcile_abandoned_intake(project_id, item_key, disposition)` command accepts only `INVALID_DISCOVERY` and `DEFERRED_ROADMAP`. It acquires a fresh recovery claim, proves the exact active/blocking INTAKE saga/action/path/issue identity, then performs lifecycle transitions and saga cancellation atomically.
4. Invalid discovery transitions PREPARING→CANCELLED and DISCOVERED→CANCELLED. Deferred roadmap transitions PREPARING→BLOCKED and DISCOVERED→BLOCKED with `ROADMAP_NOT_PREPARATION_ELIGIBLE`; it retains the planning identity.
5. Issue close uses a saga-owned `ISSUE_CLOSE` action with observe-before-repeat. Artifact removal is confined to the binding-derived managed path, requires guard authorization, rejects symlinks/tracked/unexpected content, and records evidence.

## Risks

Filesystem and GitHub mutation are fail-closed. Any mismatched binding, claim, action, ownership, tracked content, or unexpected artifact leaves state/files untouched. No generic path deletion or lifecycle mutation API is introduced.
