# Baseline implementation inventory

Captured during OpenSpec Apply before application changes.

## Candidate identity and environment

- Change: `pwa-control-center-ux-convergence`
- Branch: `proposal/control-center-ux-convergence`
- Baseline head: `7df73fe3f556cc47e58e002226247eba8f37e5a6`
- Base: `8564afc51069bd334a67fd19a2a4f51cc0659f5e` (`git merge-base origin/main HEAD`)
- Runtime environment: macOS development host; no production service or database accessed.
- The eight approved PNGs are tracked at `docs/design/01-...png` through `08-...png`; each was visually inspected before implementation.

## HTTP, schema and authentication inventory

FastAPI serves the existing static page from `/` and `/dashboard`, mounts `/static`, and serves `/sw.js`. Relevant existing authenticated read contracts found in OpenAPI:

| Surface | Existing contract | Authority / treatment |
|---|---|---|
| Overview and exact detail | `GET /api/v1/dashboard/overview`, `/api/v1/dashboard/changes/{project_id}/{change_name}`, `/api/v1/dashboard/runs/{run_id}`, `/api/v1/dashboard/events` | `DashboardOverviewResponse`, `DashboardChangeDetailResponse`, event DTOs in `services/dashboard_service.py` |
| Queue and scheduler | `GET /api/v1/queue`, `/api/v1/queue/{change_name}/explain`, `/api/v1/scheduler/status`, `/scheduler/status` | Scheduler/queue read models; logical mode is not systemd process state |
| Providers and cost | `GET /providers/health`, `/budget/usage`, `/projects/{project_id}/budget`, efficiency routes | Existing provider/budget/efficiency projections; unavailable values must stay unavailable |
| Runs and actions | `GET /api/v1/orchestration/runs`, Control Plane action discovery/execute/history | Existing action descriptors and authorization/concurrency authority |
| Preview and validation | preview lifecycle/build/start/teardown and validation scenarios/authority/submit routes | Existing preview and candidate-bound validation authorities |
| Authentication | `GET /api/v1/auth/me`, `POST /api/v1/auth/logout` | Existing operator session. Middleware uses the `minime_session` cookie or Bearer token; static assets and listed auth bootstrap routes are exempt, operational routes are protected when auth is enabled. |

OpenAPI generation reports pre-existing duplicate operation-ID warnings for `/health`, `/dashboard`, and `/`; no schema was changed during baseline capture.

## Static entrypoints, imports and event/API ownership

- `index.html` loads `css/pwa.css` and `css/dashboard.css`, manifest and icon; at its end it loads classic `js/dashboard.js` and module `js/app.js`.
- `dashboard.js` is a ~2,500-line IIFE. It owns login/logout, theme, project selection/onboarding/context, Backlog list/detail/DoR and mutations, dashboard/detail tabs, action discovery/confirmation/execution/history, preview/validation, efficiency, polling/countdown, visibility refresh and most DOM listeners.
- `app.js` is a second module bootstrap. It owns `AppState`, subscriptions, overview/queue/scheduler/runs/providers fetch and rendering, another polling interval, refresh/auto-refresh/interval/scroll/visibility listeners, offline display and service-worker registration.
- The two entrypoints both read authentication/overview and register refresh/visibility paths. `app.js` subscribes to state twice (queue and telemetry); `dashboard.js` separately calls its initializer on `DOMContentLoaded`.
- Existing modules under `js/components`, `js/views`, `js/services` and `js/state` range from render helpers to one-line wrappers. Imports are native ES modules; no bundler is configured. `components/queue_table.js` re-exports from `app.js`, creating a reverse component-to-coordinator dependency.
- Existing CSS: `tokens.css`, `layout.css`, `components.css` imported through `pwa.css`, plus `dashboard.css`; both token/layout layers affect the same document and require selector/token parity review before removal.

## Service worker baseline

`sw.js` uses cache `minime-pwa-shell-v1`, includes both entrypoints and a static shell list, but its fetch handler stores `/api/*` responses and may return a cached API response after a network error. For other GET requests it can cache arbitrary same-origin routes. Activation claims clients but does not retire only its owned prior shell-cache versions. This violates the approved static-only policy.

## Test and tooling baseline

- Baseline focused regression set: **34 passed**: dashboard UI/assets/contract, dashboard API/service/security/stale-isolation, queue API and Control Plane API.
- One pre-existing Starlette/httpx deprecation warning was reported by TestClient.
- Python 3.14 was used from a temporary venv because this host had no repository venv or `pytest`; the package declares Python `>=3.12`.
- No system Chromium/Chrome executable was found in the host search paths at baseline; existing `tests/test_pwa_real_browser.py` uses a local Chromium/CDP executable. Real-browser requirements remain unverified until a supported browser runtime is available.
- No systemd D-Bus connection is available on macOS. The Linux observer must fail closed to `UNKNOWN` here; Linux integration behavior cannot be claimed from unit tests alone.

## Scope/retirement baseline

No application changes had been made at this capture. The migration candidate is the duplicate runtime path (`app.js` plus legacy `dashboard.js`) and service-worker cache policy; no code is classified as removable solely from this inventory. Detailed call-graph parity and post-removal evidence are required before deleting any live consumer.
