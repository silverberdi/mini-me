# Proposal: Execution Operations Dashboard

## Why

mini me's autonomous orchestration pipeline coordinates complex multi-stage delivery lifecycles (readiness, execution, deterministic checks, complementary review, DeepSeek Direct audit, and GitHub PR integration). However, operating and monitoring the system currently requires direct PostgreSQL inspection, parsing CLI terminal output, or manually reconstructing orchestration history from raw event tables.

To make mini me accessible and maintainable as an autonomous software delivery system, operators need a dedicated, real-time, desktop-first operational dashboard. This dashboard must expose the exact execution state, pipeline phase progress, candidate authority, deterministic check diagnostics, complementary review findings, DeepSeek audit risks, and human attention blockers without leaking secrets or introducing heavy runtime dependencies.

## What Changes

This change introduces a comprehensive, read-only operational dashboard for mini me:

- **Backend Read-Model / Query Service (`OperationsDashboardService`)**:
  - Projections of durable PostgreSQL entities (projects, changes, orchestration runs, jobs, attempts, check runs, reviews, audits, candidate manifests, evidence diagnostics, blocker claims, and event logs) into unified, secret-redacted dashboard DTOs.
  - Optimized queries preventing N+1 query overhead.
  - Strict candidate authority isolation ensuring historical reviews/audits are never displayed as current candidate approvals.
- **Dashboard REST API Endpoints**:
  - `GET /api/v1/dashboard/overview`: High-level operational state, active runs, items requiring attention, and recent completions.
  - `GET /api/v1/dashboard/changes/{project_id}/{change_name}`: Deep inspection of a specific change and its latest/selected run.
  - `GET /api/v1/dashboard/runs/{run_id}`: Dedicated run-specific operational projection.
  - `GET /api/v1/dashboard/events`: Chronological, filterable lifecycle event timeline.
- **Operator-Facing Web Interface**:
  - Served directly by FastAPI daemon at `/` and `/dashboard` with static assets mounted at `/static/`.
  - Self-contained vanilla HTML5, modern CSS3 (with dark/light mode, CSS custom properties, responsive desktop-first layout, and accessible badges/icons), and vanilla ES JavaScript.
  - Visual pipeline progress stepper across all 6 core phases: Readiness, Implementation, Deterministic Checks, Complementary Review, DeepSeek Audit, and PR/Merge.
  - Prominent Attention / Blocker banner for `NEEDS_HUMAN`, `WAITING_CAPACITY`, and `RECOVERY_BLOCKED` states with root cause and remediation guidance.
  - Detail panels for deterministic check diagnostics, complementary review findings, DeepSeek audit security ratings, candidate manifest differences, and chronological stage transition history.
  - Auto-refresh mechanism (configurable interval with progress countdown) and manual refresh trigger.
- **Security & Secret Redaction**:
  - Comprehensive scrubbing of all API tokens, DB passwords, GitHub private keys, and environment variables across diagnostics and event summaries.

## Capabilities

### New Capabilities
- `execution-operations-dashboard`:
  - Operational overview and real-time execution state projection.
  - Multi-phase pipeline progress tracking (readiness -> implementation -> checks -> review -> audit -> PR/merge).
  - Attention callout for human gates, quota waits, and recovery blockers.
  - Candidate generation and authority binding with stale evidence isolation.
  - Secret-redacted check diagnostics, review findings, and audit summaries.
  - Chronological transition and event timeline drill-down.
  - Standalone, self-contained web interface served by the daemon.

### Modified Capabilities
- None.

## Non-Goals (Read-Only MVP)

- Mutating orchestration state, triggering jobs, or reassigning agents directly from the UI.
- Resolving `NEEDS_HUMAN` gates or overriding provider policies through web forms.
- Introducing WebSockets, SSE, or heavy JavaScript client frameworks (React, Vue, Next.js).
- Replacing or modifying existing CLI commands or domain persistence abstractions.

## Impact

- `src/minime/services/dashboard_service.py` added for query projections.
- `src/minime/api/app.py` updated with dashboard routes and static file mounting.
- `src/minime/static/` directory created with `index.html`, `css/dashboard.css`, and `js/dashboard.js`.
- Automated test suite expanded with unit, API, security, and UI integration tests.
