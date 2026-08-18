# Change: Foundation and durable work binding

## Why
mini me needs a durable control plane that can identify exactly which repository/change is safe to execute, survive restart, expose status and start collecting trustworthy operational evidence before any provider implementation pipeline is added.

## What Changes
- Establish Python service/package/config foundation.
- PostgreSQL operational store with Alembic migrations.
- Durable current-state + event/evidence primitives.
- Project registry with immutable internal identity and exact repository binding.
- OpenSpec discovery + programmatic Definition of Ready evaluation.
- GitHub Issue/global-Project mapping primitives without implementing the later full PR lifecycle.
- Minimal health/status API and CLI.
- Metrics fact/attempt foundation sufficient for later stages.

## User/operator value
After this change, the owner can register mini me as a project, discover OpenSpec work, see why a change is or is not READY, restart the daemon without losing registered/discovered state, and prove that no execution target is selected from ambiguous display metadata.

## Non-goals
- No Codex/Antigravity execution yet.
- No cross-review/audit.
- No OpenRouter/Qwen execution.
- No TUI beyond minimal CLI/status surface.
- No UI preview/deployment pipeline.
- No PR/merge/production closure automation.
- No advanced scheduler/concurrency.

## Capabilities
### New
- `postgres-durable-state`
- `project-registry`
- `repository-binding`
- `openspec-readiness`
- `github-work-binding`
- `status-observability`
