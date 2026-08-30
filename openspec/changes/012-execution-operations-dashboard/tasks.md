# Tasks: Execution Operations Dashboard

## 1. Backend Read Model and Service
- [x] 1.1 Define dashboard DTO domain models in `src/minime/services/dashboard_service.py` (`DashboardOverviewResponse`, `DashboardChangeDetailResponse`, `PipelinePhaseStatus`, `CandidateAuthorityDTO`, `TimelineEventDTO`).
- [x] 1.2 Implement `OperationsDashboardService.get_overview()` to aggregate system status, attention items, active executions, and change summaries.
- [x] 1.3 Implement `OperationsDashboardService.get_change_detail()` to project 6-phase pipeline state, candidate authority, check results, review findings, audit findings, and blockers for a change.
- [x] 1.4 Implement `OperationsDashboardService.get_run_detail()` to project state for an exact orchestration run.
- [x] 1.5 Implement `OperationsDashboardService.get_events_timeline()` to construct a chronological, sanitized event sequence.
- [x] 1.6 Implement stale-evidence isolation logic ensuring prior-generation review and audit results are never treated as valid approvals of the current candidate.
- [x] 1.7 Apply `redact_secrets()` to all projected diagnostics, summaries, error messages, and timeline details.

## 2. Dashboard REST API Endpoints
- [x] 2.1 Add `GET /api/v1/dashboard/overview` endpoint in `src/minime/api/app.py`.
- [x] 2.2 Add `GET /api/v1/dashboard/changes/{project_id}/{change_name}` endpoint in `src/minime/api/app.py`.
- [x] 2.3 Add `GET /api/v1/dashboard/runs/{run_id}` endpoint in `src/minime/api/app.py`.
- [x] 2.4 Add `GET /api/v1/dashboard/events` endpoint with optional filtering by `project_id`, `change_name`, and `run_id`.
- [x] 2.5 Mount static assets directory and serve `index.html` at `/` and `/dashboard`.

## 3. Self-Contained Web Interface (UI/UX)
- [x] 3.1 Create `src/minime/static/index.html` with semantic structure: navigation header, status banner, overview KPI cards, attention banner, changes data table, and selected change detail drawer.
- [x] 3.2 Create `src/minime/static/css/dashboard.css` with CSS custom properties for dark/light themes, typography, compact grid layouts, status badges, and 6-phase pipeline stepper styling.
- [x] 3.3 Create `src/minime/static/js/dashboard.js` with pure vanilla ES logic for fetching API state, rendering UI components, handling filter/search, rendering modal/detail views, and controlling auto-refresh (with interval countdown).
- [x] 3.4 Ensure full responsiveness and accessibility across desktop and tablet viewports.

## 4. Automated Testing and Acceptance
- [x] 4.1 Create `tests/test_dashboard_service.py` covering overview aggregation, change details, pipeline phase mapping, empty states, and blocker classification.
- [x] 4.2 Create `tests/test_dashboard_api.py` validating all `/api/v1/dashboard/*` endpoints with TestClient.
- [x] 4.3 Create `tests/test_dashboard_stale_isolation.py` proving that historical candidate reviews and audits are not confused with current candidate authority.
- [x] 4.4 Create `tests/test_dashboard_security.py` verifying that credentials, private keys, and environment secrets are sanitized.
- [x] 4.5 Create `tests/test_dashboard_ui.py` verifying static asset serving, HTML routes, and content integrity.

## 5. Verification, Review, Audit, and Closure
- [x] 5.1 Run full safe test suite (`pytest`) and code formatting/linter (`ruff check .`).
- [x] 5.2 Validate OpenSpec strict schema (`openspec validate --all --strict`).
- [x] 5.3 Freeze authoritative candidate and record manifest.
- [x] 5.4 Execute complementary review and resolve any material findings.
- [x] 5.5 Run DeepSeek Direct audit and verify zero material findings.
- [x] 5.6 Perform authorized merge, verify main ancestry, synchronize OpenSpec, archive change 012, and push clean main.
