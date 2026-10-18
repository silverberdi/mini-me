# Modular consumer parity and Removal Gate status

This record is scoped to the local continuation based on `b0110c12469674515b8fa2ed1adefe1541e20900`. It records the functional seams moved out of the former monolithic dashboard module and does **not** claim completion of tasks 5.1–5.3.

## Runtime and ownership after this continuation

`index.html` loads only `/static/js/app.js`. `app.js` guards the single DOM-ready bootstrap and imports `initDashboard` from `dashboard.js`. `dashboard.js` is the composition root; `controllers/execution_view_controller.js` owns authenticated overview/queue/provider/health state, refresh reconciliation, selected Change identity and detail request freshness. Independent domains own their behavior and listeners:

| Domain | Runtime owner | Responsibilities moved/owned | Preserved authority |
|---|---|---|---|
| Refresh/browser lifecycle | `controllers/lifecycle_controller.js` | One refresh timer; interval preference validation; manual refresh; online/offline and visibility reactions; stop on logout; one binding of each lifecycle listener | Existing authenticated no-store API reads and explicit freshness states |
| Navigation and execution selection | `controllers/navigation_controller.js` | Desktop/mobile navigation, scroll targets, view visibility, filters/search, accessible Change selection, detail tabs, candidate SHA copy | Existing view renderers and detail/read-model selection callbacks |
| Operational read models and Run/Change selection | `controllers/execution_view_controller.js` | Overview/queue/provider/health snapshots, refresh overlap coalescing, freshness rendering, selected Change identity, exact-detail request sequencing and stale response suppression | Existing authenticated API client and dashboard/queue/provider/health read models; no browser-side status or cost inference |
| Projects | `controllers/projects_controller.js` | Project list projection, selection, onboarding, context inspection, project-card actions and their listeners; clears identity-scoped data and invalidates in-flight reads on logout/auth loss | `/projects`, onboarding and context APIs; unavailable context stays unavailable |
| Backlog | `controllers/backlog_controller.js` plus `views/backlog_view.js` | Authenticated project/backlog reads, stale-project/session response suppression, admission facts, Backlog data/selection state, search/filter/list/detail projection, create/edit form state and serialization, prepare/start/save/delete/clarification/discovery controls and write reconciliation | Existing project/backlog APIs, explicit confirmation, authoritative response refresh; clarification serializes the selected question together with the answer and refreshes the list/detail; dashboard no longer owns a duplicate Backlog store or renderer |
| Governed actions | `controllers/action_controller.js` | Control Plane action discovery, one delegated toolbar listener, server-action filtering, parameter/confirmation dialog routing, optimistic-concurrency request identity, submit/result notification and read-model refresh | Existing Control Plane discovery/execute/history contracts; merge remains unavailable |
| Detail telemetry | `controllers/detail_telemetry_controller.js` and `views/detail_telemetry_views.js` | Exact Change efficiency and Run action-history reads/rendering, with selection-sequence protection against delayed results from a previously selected Change/Run | Existing efficiency and Control Plane history APIs; absent values remain unavailable rather than defaulting to fabricated zeroes |
| Run/Job detail composition | `controllers/detail_view_controller.js` plus existing evidence/preview/GitHub/timeline views | Candidate-bound identity header and composition of pipeline, overview, candidate, checks, review, audit, preview, GitHub, telemetry, timeline and governed action toolbar | Existing candidate-bound dashboard detail read model and specialized domain controllers/views |
| Preview, validation, GitHub and timeline presentation | `views/preview_view.js` and `views/github_timeline_views.js`, composed by the dashboard read-model coordinator | Candidate/base/generation/image binding, stale validation state, guided validation scenarios, safe URL display, lifecycle event rendering | Existing preview, validation, GitHub and timeline read models; operations remain in the existing preview controller/API |
| Preview/validation | `controllers/preview_controller.js` | Preview operations and exact candidate/image-bound validation submission | Existing preview and validation authorities; authenticated identity is server-derived |
| Rendering | `controllers/detail_view_controller.js`, `views/*`, existing `components/*` | Overview, Projects, Backlog, Runs, pipeline, operational panels and candidate/check/review/audit evidence; domain view entrypoints live outside the shared coordinator | Backend-provided values only; missing/invalid evidence remains unavailable |

The Service Worker allowlist includes each imported controller module and excludes retired unused modules. `dashboard.js` no longer registers view, refresh, Backlog, Projects, filter, selection, tab, or action-toolbar listeners; it composes domain controllers, owns shared DOM element references and project/session wiring, and retains only small navigation/project/backlog adapters and safe display utilities.

## Deterministic parity evidence

The operational Control Center shell and read-model binding are now evidenced for tasks 2.1 and 2.2: the authenticated landing defaults to the execution center with unobserved project policy set to UNKNOWN, the existing Projects/Backlog path remains reachable, and overview/queue/provider/health/detail activity is rendered from existing authenticated APIs with source freshness or explicit unavailability. The latest Chrome/API group includes these tests and passed 113/113; visual acceptance against all eight reference states is tracked separately and remains open.

After migrating Backlog reads/selection/detail form, Run/Job detail composition and operational read-state/selection, and removing six unreferenced state/presentation modules plus owned Service Worker entries, the consolidated affected group most recently passed **113 tests, 4 warnings in 81.64s**. It includes real Chrome cases for selected Change/candidate/preview identity, stale detail and telemetry response suppression, Backlog form submission, selected-question/answer serialization and controller refresh, Projects navigation, safe toast text/timer ownership, lifecycle listener uniqueness, offline/reconnect, authenticated cache/session separation and viewport shell behavior, as well as the API/service contracts below. The selected-question test uses an intercepted transport to verify frontend contract only. An exploratory attempt against the shared seeded UOW reached the backend answer route but failed closed at the expected missing `ProjectManagedRepositoryBinding` during re-preparation; no fake binding was added, and full lifecycle/managed-repository E2E remains pending. A prior selected-Change browser case failed in sequence because an earlier logout test revoked the shared module-scoped fixture token. The logout test now issues a fresh session through `SessionManager` after asserting the old session's protected state was cleared; revocation assertions remain intact. The ordered logout/detail reproduction passed 2/2 before the later clarification correction. The action-controller browser test proves one delegated toolbar listener, merge filtering and stale discovery for another Run being ignored. Detail telemetry tests prove late responses cannot overwrite a new selection.

- `tests/test_pwa_real_browser.py::test_real_browser_projects_domain_navigation_and_context_use_authoritative_api`
- The same real Chrome flow also logs out after visiting Projects/Backlog and verifies project selection/cards and Backlog detail are cleared before another session.
- `tests/test_pwa_real_browser.py::test_real_browser_lifecycle_controller_has_one_refresh_and_listener_owner`
- `tests/test_pwa_real_browser.py::test_real_browser_selected_change_renders_candidate_bound_preview_and_detail_tabs`
- `tests/test_pwa_real_browser.py::test_real_browser_execution_view_controller_ignores_stale_change_detail_response`
- `tests/test_pwa_real_browser.py::test_real_browser_action_controller_refreshes_the_selected_snake_case_identity`
- `tests/test_pwa_real_browser.py::test_real_browser_preview_controller_requires_exact_preview_and_records_completed_scenarios`
- `tests/test_control_plane_service.py::test_optimistic_concurrency_rejection`
- `tests/test_control_plane_service.py::test_idempotent_duplicate_request`
- preview API authenticated-operator binding and `tests/test_pwa_service_worker.py` static/cache policy checks.

The projects browser test uses an isolated seeded UOW; it verifies displayed repository and project identity and the transition from the authoritative project card to Backlog. It does not establish production or Linux integration. Lifecycle testing uses fake event targets/timers inside real Chrome to prove single-owner binding and stop/start behavior; offline/reconnect behavior is separately exercised against the local test server.

## Remaining call-graph parity before removal

Task 5.1 remains open. The old classic-script include/IIFE and duplicate app bootstrap are absent; `index.html` loads only the guarded `app.js` entrypoint. `dashboard.js` (495 lines) is now a native module composition root; operational read state is in `execution_view_controller.js`, while Backlog/Projects/actions/preview/lifecycle/navigation and detail projection belong to their domain modules. Full consumer/import/DOM/listener/API parity is not yet established for every dynamic path, onboarding writes, clarification, all confirmation/403/stale browser scenarios, accessibility, and the eight approved visual states.

Consequently:

- Task 5.2 is intentionally incomplete pending the remaining domain migration and full before/after parity matrix. This continuation removed only the proven orphan `AppState` and five unreferenced presentation helpers (and owned cache entries where present); no user-facing behavior or active legacy consumer was deleted.
- Task 5.3 is pending: its post-removal regression condition cannot be met before 5.2.
- No code path is removed or declared obsolete based only on line-count reduction.
- Human visual approval, Linux system-bus observation and post-merge/deploy verification remain external gates.
