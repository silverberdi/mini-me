## Why

Project execution can be paused by `execution_policy.effective_pause` or `global_pause` while `projects.status` remains `ACTIVE`. The Proyectos view currently shows only the administrative status, so operators cannot see the pause state that the existing admission logic honors.

## What Changes

- Show each project's effective execution pause separately from its administrative lifecycle status in Proyectos.
- Show a system-level global-pause indicator derived from the existing project payloads.
- Reflect updated flags through the existing project-list refresh flow.

## Capabilities

### New Capabilities

### Modified Capabilities

- `f5-projects-and-backlog`: Proyectos displays the persisted effective project and global execution-pause state.

## Impact

- Frontend: `frontend/src/app/core/models.ts`, `frontend/src/app/features/proyectos/proyectos.component.ts`, and focused frontend tests.
- Reads the existing authenticated `GET /api/v1/projects` payload, which already includes `execution_policy`; no backend or API changes.
- No change to admission, pause/resume operations, other views, or persisted state.
