# Modular consumer parity and Removal Gate status

This record is scoped to the local continuation based on `b0110c12469674515b8fa2ed1adefe1541e20900`. It records the functional seams moved out of the former monolithic dashboard module and does **not** claim completion of tasks 5.1–5.3.

## Runtime and ownership after this continuation

`index.html` loads only `/static/js/app.js`. `app.js` guards the single DOM-ready bootstrap and imports `initDashboard` from `dashboard.js`. `dashboard.js` remains the single shared operational state/read-model coordinator, while the following independent domains now own their behavior and listeners:

| Domain | Runtime owner | Responsibilities moved/owned | Preserved authority |
|---|---|---|---|
| Refresh/browser lifecycle | `controllers/lifecycle_controller.js` | One refresh timer; interval preference validation; manual refresh; online/offline and visibility reactions; stop on logout; one binding of each lifecycle listener | Existing authenticated no-store API reads and explicit freshness states |
| Navigation and execution selection | `controllers/navigation_controller.js` | Desktop/mobile navigation, scroll targets, view visibility, filters/search, accessible Change selection, detail tabs, candidate SHA copy | Existing view renderers and detail/read-model selection callbacks |
| Projects | `controllers/projects_controller.js` | Project list projection, selection, onboarding, context inspection, project-card actions and their listeners | `/projects`, onboarding and context APIs; unavailable context stays unavailable |
| Backlog | `controllers/backlog_controller.js` | Backlog search/filter/list selection, prepare/start/edit/save/delete/clarification/discovery controls and write reconciliation | Existing project/backlog APIs, explicit confirmation, authoritative response refresh |
| Governed actions | `controllers/action_controller.js` | Control Plane action discovery, one delegated toolbar listener, server-action filtering, parameter/confirmation dialog routing, optimistic-concurrency request identity, submit/result notification and read-model refresh | Existing Control Plane discovery/execute/history contracts; merge remains unavailable |
| Preview/validation | `controllers/preview_controller.js` | Preview operations and exact candidate/image-bound validation submission | Existing preview and validation authorities; authenticated identity is server-derived |
| Rendering | `views/*`, existing `components/*` | Overview, Projects, Backlog, Runs, pipeline, operational panels and candidate/check/review/audit evidence | Backend-provided values only; missing/invalid evidence remains unavailable |

The Service Worker allowlist includes each imported controller module. `dashboard.js` no longer registers view, refresh, Backlog, Projects, filter, selection, tab, or action-toolbar listeners; it composes domain controllers and still owns the shared data/read-model state and multiple detail renderers.

## Deterministic parity evidence

The latest consolidated affected group passed **108 tests** (4 existing deprecation/OpenAPI warnings). It includes real Chrome tests for selected Change/candidate/preview identity, Projects navigation and project-to-Backlog transition, lifecycle listener uniqueness, offline/reconnect, authenticated cache/session separation, viewport shell behavior, and the API/service contracts below. The selected-Change browser test initially failed in sequence because an earlier logout test revoked the shared module-scoped fixture token. The fixture now issues a fresh session through `SessionManager` after logout; the revocation assertions remain intact. The two-test ordered reproduction passed 2/2, followed by the consolidated 108-test pass. The action-controller browser test additionally proves one delegated toolbar listener, server-action merge filtering and a stale discovery response for another Run being ignored.

- `tests/test_pwa_real_browser.py::test_real_browser_projects_domain_navigation_and_context_use_authoritative_api`
- `tests/test_pwa_real_browser.py::test_real_browser_lifecycle_controller_has_one_refresh_and_listener_owner`
- `tests/test_pwa_real_browser.py::test_real_browser_selected_change_renders_candidate_bound_preview_and_detail_tabs`
- `tests/test_pwa_real_browser.py::test_real_browser_action_controller_refreshes_the_selected_snake_case_identity`
- `tests/test_pwa_real_browser.py::test_real_browser_preview_controller_requires_exact_preview_and_records_completed_scenarios`
- `tests/test_control_plane_service.py::test_optimistic_concurrency_rejection`
- `tests/test_control_plane_service.py::test_idempotent_duplicate_request`
- preview API authenticated-operator binding and `tests/test_pwa_service_worker.py` static/cache policy checks.

The projects browser test uses an isolated seeded UOW; it verifies displayed repository and project identity and the transition from the authoritative project card to Backlog. It does not establish production or Linux integration. Lifecycle testing uses fake event targets/timers inside real Chrome to prove single-owner binding and stop/start behavior; offline/reconnect behavior is separately exercised against the local test server.

## Remaining call-graph parity before removal

Task 5.1 remains open. `dashboard.js` is now a native ES module coordinator, not a second classic-script IIFE, and `index.html` loads only the guarded `app.js` bootstrap. It still owns authentication/session projection, shared response state, overview/change-detail fetch and substantial detail rendering, efficiency/action-history/preview/GitHub/timeline rendering, action descriptor parameter dialogs, backlog detail/form composition, and cross-domain orchestration. The module/test matrix is not yet complete for every consumer, onboarding writes, clarification, all confirmation/403/stale browser scenarios, accessibility, or eight approved visual states.

Consequently:

- Task 5.2 is intentionally blocked on the remaining domain migration and before/after parity matrix. No executable legacy controller or consumer is being deleted by this continuation.
- Task 5.3 is pending: its post-removal regression condition cannot be met before 5.2.
- No code path is removed or declared obsolete based only on line-count reduction.
- Human visual approval, Linux system-bus observation and post-merge/deploy verification remain external gates.
