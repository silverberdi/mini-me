# Local validation evidence

Candidate branch: `proposal/control-center-ux-convergence`.
Starting candidate HEAD for this continuation: `b0c798233142681119f004c3fe039fea838d6473`.
Test host: macOS / Python 3.14.5. Test runtime: `/tmp/minime-pwa-test-runtime` via `MINIME_RUNTIME_ROOT`; no production service or database was accessed.

## Continuation from `b0110c12469674515b8fa2ed1adefe1541e20900`

The order-sensitive Chrome failure was traced to test fixture lifecycle, not application behavior: `test_real_browser_api_cache_isolation_across_operator_sessions` logs out and revokes the module-scoped fixture's initial session, while later browser tests reused that revoked token. The dashboard correctly hid operational rows and displayed its unauthenticated placeholder. The logout/cache test now issues a new session using the real `SessionManager` after completing its revocation assertions and updates the shared fixture token for subsequent cases. No auth guard or assertion was weakened.

Ordered reproduction:

```text
tests/test_pwa_real_browser.py -k 'api_cache_isolation_across_operator_sessions or selected_change_renders_candidate_bound_preview_and_detail_tabs'
2 passed, 20 deselected in 10.89s
```

Final consolidated affected group after the correction:

```text
tests/test_pwa_real_browser.py tests/test_pwa_service_worker.py tests/test_pwa_assets.py
tests/test_pwa_contract.py tests/test_dashboard_ui.py tests/test_dashboard_api.py
tests/test_dashboard_security.py tests/test_dashboard_stale_isolation.py
tests/test_dashboard_service.py tests/test_preview_api_endpoints.py
tests/test_control_plane_api.py tests/test_control_plane_service.py
tests/test_pwa_desktop_layout.py tests/test_systemd_scheduler_observer.py
109 passed, 4 warnings in 81.37s
```

The four warnings are existing Starlette/httpx deprecation and duplicate FastAPI OpenAPI operation IDs. The action-controller, detail-telemetry, preview-view, GitHub and timeline migrations were part of this run. This is a focused affected-group result, not a post-correction repository-wide pytest run.

## Focused validation after implementation fixes

Consolidated affected group:

```text
MINIME_RUNTIME_ROOT=/tmp/minime-pwa-test-runtime pytest -q \
  tests/test_pwa_real_browser.py tests/test_dashboard_ui.py \
  tests/test_pwa_service_worker.py tests/test_pwa_assets.py \
  tests/test_pwa_contract.py tests/test_dashboard_api.py \
  tests/test_dashboard_security.py tests/test_dashboard_stale_isolation.py \
  tests/test_control_plane_api.py tests/test_dashboard_service.py \
  tests/test_systemd_scheduler_observer.py tests/test_pwa_desktop_layout.py
```

Result: **59 passed, 4 warnings**. This includes real-Chrome tests at the five required viewport sizes, offline/reconnect, auth expiry, cache inspection and two-operator cache isolation; PWA/API/Control Plane regressions; systemd projection and observer timeout/freshness/fail-closed cases. A separate baseline/current comparison subset passed the five order-sensitive full-suite failures when run together on the current candidate. The focused systemd/OpenSpec contract follow-up passed **11 passed**. After extracting Backlog and candidate/review/check evidence rendering to live view modules, focused Chrome rendering, assets/import-graph, service-worker and PWA contract checks passed **11 passed**.

The test census surfaced two stale static PWA assertions that still expected scheduler and stage labels to live in the old dashboard module. They were updated to assert the modular API/view contracts and the backend's actual six pipeline phases. `tests/test_pwa_contract.py`: **3 passed** after correction.

## Follow-up: tablet layout and desktop preference proof

At commit `eae8e6e` plus the read-model follow-up, the affected group was rerun after adding tablet navigation/queue styling, browser evidence for desktop preferences, and repository binding identity projection:

```text
tests/test_pwa_real_browser.py tests/test_pwa_desktop_layout.py
tests/test_dashboard_ui.py tests/test_pwa_assets.py tests/test_pwa_contract.py
tests/test_pwa_service_worker.py tests/test_dashboard_api.py tests/test_dashboard_security.py
tests/test_dashboard_stale_isolation.py tests/test_control_plane_api.py
tests/test_dashboard_service.py tests/test_systemd_scheduler_observer.py
63 passed, 4 warnings in 65.03s
```

Chrome exercises an authenticated two-operator session: keyboard resize respects 240px/70% pane bounds; only a digest namespace and `{version, ratio, collapsed}` are persisted; a malformed second-account preference falls back to default; first-account collapse survives reload; resetting the second account preserves the first preference; tablet/mobile do not inherit desktop width/collapse and mobile remains detail-first. This supports task 7.3, not eight-state visual acceptance.

The browser cache/session security subset was then extended and rerun after adding an authenticated Control Plane POST, explicit 401/403 observations and logout response synchronization:

```text
tests/test_pwa_real_browser.py::test_real_browser_api_cache_isolation_across_operator_sessions
tests/test_pwa_real_browser.py::test_real_browser_auth_expiry_hides_operational_state
tests/test_pwa_real_browser.py::test_real_browser_offline_state_and_reconnection_refresh
tests/test_pwa_service_worker.py
6 passed
```

The authenticated Control Plane POST is rejected by request validation without executing an action; revoked sessions receive 401 and a session for a non-allowlisted identity receives 403. After logout, CacheStorage still contains no `/api/*` resources; login as a different authorized operator updates the visible operator identity. The route behavior uses the isolated in-memory UOW and local test server only.

## Follow-up: exact repository identity in the Run/Job read model

Task 2.3 required a backend-authoritative repository identity in the contextual drawer; the prior detail DTO exposed project/change/Run/Job/candidate IDs but not the exact bound repository. `DashboardChangeDetailResponse` now projects the matching durable `ProjectBinding` as `repository_identity` only when the row is valid, has no mismatch reasons and contains a non-empty repository. Invalid bindings expose state `INVALID` but suppress their raw repository value; absent bindings remain `UNKNOWN`. The UI displays this projection from `renderDetail`; there is no repo inference from project display name or Change text.

Focused API, stale-candidate isolation, dashboard security, browser detail binding, and PWA contract group: **19 passed, 4 warnings in 7.60s**. This includes exact valid binding, invalid binding suppression, OpenAPI schema, stale Review/Audit generation isolation and browser drawer rendering. No DB schema change or migration was required.

## One repository-wide test run and attribution

One full `pytest -q` run, with the isolated runtime root configured, completed before the final small corrections to stale PWA assertions and contradictory systemd-state validation:

```text
1797 passed, 16 skipped, 10 failed in 855.01s (0:14:15)
```

Failure census:

| Failure group | Evidence / disposition |
|---|---|
| Two `tests/test_pwa_contract.py` assertions | Stale expectations against the old controller/stage vocabulary; corrected to the current modular API/read-model contracts. The file now passes 3/3. |
| `test_process_safety::test_timeout_sends_sigterm_and_process_exits_gracefully` | Reproduced on base SHA `8564afc51069bd334a67fd19a2a4f51cc0659f5e` under the same runtime. The one-second watchdog wins before the child writes its SIGTERM marker; captured logging also reports a closed stream. Pre-existing timing/environment failure. |
| `test_project_onboarding::test_onboard_new_project_success` | Reproduced on the same base/runtime. Its fixture repository and worktree parent are outside its configured trusted root and onboarding correctly fails closed before mutation. Pre-existing fixture/topology mismatch. |
| `test_stage_c_isolation::test_onboard_project_rejects_runtime_collision` | Reproduced on the same base/runtime. Validation stops earlier because the fixture lacks its OpenSpec path and is outside the trusted root; the asserted collision diagnostic is never reached. Pre-existing fixture/precondition mismatch. |
| Two N01 reconciliation tests, two orchestration API tests, and one Codex account-model dispatch test | They failed only in the monolithic run. The exact five nodes passed together on the candidate (5/5); the same nodes also passed on base. This is order-sensitive suite state/interaction, not attributed to this UI change; underlying global test-order isolation remains unresolved. No N01 data or service was touched. |

The five order-sensitive nodes passed again in an isolated targeted group. Do not interpret that as eliminating their monolithic-run instability. The full suite was not rerun after the final targeted corrections; there is one full-suite result, not a post-correction full-suite PASS.

## Tooling and browser evidence

- `ruff check src tests`: passed after the final observer/test changes.
- Scoped Ruff format check over all changed Python files: passed after formatting only the two changed files Ruff identified. Repository-wide `ruff format --check src tests` reports unrelated pre-existing formatting findings; no broad formatting was applied.
- `openspec validate pwa-control-center-ux-convergence --strict`: passed after task/evidence updates.
- `git diff --check`: passed after task/evidence updates.
- Real Chrome captured five fixture-seeded viewport screenshots under `evidence/browser/*-mock-seeded.png`. They are seeded test fixtures, not production-state evidence or human visual approval. They do not establish visual parity against all eight Stitch states.
- The eight approved Stitch PNGs remain the visual baseline. Human comparison/acceptance and the remaining three-state visual evidence are pending.
- Tablet now uses a compact icon rail, a wrapping status/action toolbar at narrow tablet widths, structured queue cards, and master-detail at both tablet target sizes; browser checks assert no horizontal page overflow. Visual acceptance remains pending: mobile retains more KPI/detail density than the approved supervision-first references, desktop hierarchy does not yet match all reference states, and only the active mock-seeded state is captured at five sizes.

## Scheduler observation limits

The fixed-target read-only D-Bus observer is deterministic-test verified for active/enabled, inactive/disabled, unknown/unsupported, stale/future, unavailable, malformed, timeout and contradictory active/substate combinations. Logical admission mode is projected independently. `tests/test_systemd_scheduler_observer.py` and `tests/test_pwa_contract.py`: **11 passed** in the follow-up check. This macOS host cannot exercise the Linux system bus; a Linux integration gate remains pending. No `systemctl`, scheduler control operation, added privilege or production access was used.

## Remaining implementation / acceptance limits

- Frontend convergence/removal was incomplete at the prior recorded checkpoint; the current continuation migrates execution reads/selection and Backlog/detail rendering and removes proven orphan modules. Full consumer parity and legacy-removal proof are still not established. Do not mark tasks 5.1–5.3 complete or claim architectural convergence.
- The five viewport checks do not complete the eight approved visual states, keyboard/accessibility audit, or human validation. Task 7.3 is now verified; tasks 4.1, 4.2, 7.2 and human visual acceptance remain open.
- Authenticated preview/container E2E, governed action lifecycle E2E, complete-value states (including an authoritative deliberate PAUSED source), post-merge/deployment verification, and real Linux systemd observation remain pending.
- No task requiring human approval, merge or deployment is complete.

## Continuation from PR #156 `f4147eae044149775e7034d159b4967dc132d72b`

This continuation was performed on the same isolated branch/worktree. `src/minime/static/js/dashboard.js` is now 495 lines and serves as native ES-module composition root imported by the single guarded `app.js` bootstrap, not the former classic IIFE. The new `controllers/execution_view_controller.js` owns operational overview/queue/provider/health snapshots, refresh and selected Change identity; this is not complete consumer convergence because cross-domain composition and some session/project identity wiring remain in the root module.

Additional migrations in this continuation:

- Backlog controller now owns authenticated project/backlog reads, project-scoped stale-response suppression, Backlog item/selection state, admission-fact projection, detail/table selection rendering, form serialization and existing mutations. The dashboard retains only the shared project identity and provides coordinator callbacks.
- `controllers/detail_view_controller.js` owns exact Run/Job identity header and composes evidence, candidate-bound preview, GitHub, telemetry, timeline and action-toolbar modules.
- `controllers/execution_view_controller.js` owns overview/queue/provider/health read-model snapshots, overlap-coalesced refresh, exact Change selection, detail response identity validation and stale response suppression.
- `components/toast.js` now owns the accessible text-only toast surface and single dismissal timer.
- An initial source/import census found `state/store.js` (`AppState`) had no consumers. It was removed with its owned Service Worker asset entry; a later census found and removed five additional unreferenced presentation helpers, described in the final continuation check below.

The post-retirement consolidated affected validation was first run with **110 passed / 1 failed** because `tests/test_pwa_assets.py` still required the now-retired unreferenced `state/store.js`. That asset expectation was corrected to match the runtime import/cache inventory and the same consolidated command was rerun once:

```text
tests/test_pwa_real_browser.py
tests/test_pwa_service_worker.py
tests/test_pwa_assets.py
tests/test_pwa_contract.py
tests/test_dashboard_ui.py
tests/test_dashboard_api.py
tests/test_dashboard_security.py
tests/test_dashboard_stale_isolation.py
tests/test_dashboard_service.py
tests/test_preview_api_endpoints.py
tests/test_control_plane_api.py
tests/test_control_plane_service.py
tests/test_pwa_desktop_layout.py
tests/test_systemd_scheduler_observer.py
111 passed, 4 warnings in 79.32s
```

The four warnings are one pre-existing Starlette/httpx deprecation and three duplicate FastAPI OpenAPI operation IDs. At this point in the work the consolidation was post-`AppState` removal; a later post-orphan-removal 112-test consolidation is recorded below. Neither run is post-removal of the legacy dashboard coordinator; neither satisfies task 5.3. The earlier full repository result remains the sole full-suite run (**1797 passed, 16 skipped, 10 failed**, before later targeted corrections); no post-checkpoint full-suite PASS is claimed.

Static validation was rerun after the final orphan retirement: `ruff check src tests` PASS; Ruff format check for the changed Python tests PASS; Node syntax checks for changed modules and service worker PASS; `openspec validate pwa-control-center-ux-convergence --strict` PASS; `git diff --check` PASS.

The same previously recorded limits remain: call-graph and before/after behavior parity for every listed consumer is incomplete, so tasks 5.1–5.3 remain open; the complete eight-state visual comparison and human sign-off, preview/action full-value E2E, Linux D-Bus observation, accessibility audit, full suite after final migration, merge/deployment and post-deployment gates remain pending. No production, N01 or scheduler state was accessed or changed.

## Final convergence continuation from `9b4fc3add06b5354c163f83f67818bc2531bf2a4`

This section supersedes the earlier implementation-status statements above for the consumer-parity/removal tasks only; it does not change historical run results or external/human gates.

- A deterministic consumer/owner/API/browser matrix was completed in `evidence/module-parity.md`. The native ES-module `dashboard.js` composition root remains intentionally retained; it is not the former classic IIFE and it owns no feature event listeners or independent refresh loop. The retired classic include/IIFE remains absent.
- After source/import census, ten proven orphan JavaScript modules across the Change and their owned cache paths were removed. Static tests assert one guarded `app.js` bootstrap, no active classic dashboard path, every remaining JS asset reachable from the module graph and allowed by the static cache, and no orphan paths. Existing browser/API security checks preserve session isolation, no API CacheStorage, and server-side Control Plane authorization.
- The real-Chrome disposable onboarding path now follows the canonical topology: a physical local bare Git origin, service-created managed repo/binding/ownership marker under the trusted root, verification through `ManagedWorkspaceGuard`, and authenticated Backlog create/list. Persistence is the explicit in-memory test UOW and GitHub transport is an offline stub; no PostgreSQL or GitHub App integration is claimed. The adjacent onboarding unit fixture was corrected to place its repo under the trusted root, provide an observable `origin`, and use canonical roadmap syntax. No guard or parser was relaxed.
- The post-removal consolidated affected command passed **134 passed, 4 warnings in 98.38s**. It covered real Chrome, the five target viewport checks, navigation/status/candidate/preview/actions, onboarding and Backlog, service-worker security, dashboard/API/Control Plane/security/stale isolation, desktop layout and deterministic systemd observer. Warnings: one Starlette `httpx` deprecation and three duplicate FastAPI OpenAPI operation IDs.
- The immediately preceding consolidated attempt had 132 passing and 2 failing onboarding tests. Both failures were fixture-contract mismatches (repo outside its declared trusted root / missing `origin`, plus non-canonical roadmap syntax) and were addressed in tests without changing authority logic; the two corrected cases then passed together (`2 passed in 7.64s`) before the successful consolidated run.
- Task 3.2's new hostile-status Chrome assertion, keyboard tab/focus/name/reduced-motion browser test, and the corrected onboarding flow were all included in the successful 134-test run. Native dialog focus containment and Escape return-focus coverage was added afterward and passed separately (`1 passed in 5.60s`).
- Therefore tasks 5.1–5.3 now have post-removal deterministic parity evidence and are marked complete in `tasks.md`. This is technical/browser fixture evidence, not live GitHub App/production E2E.
- The full repository suite has not yet been rerun on this final continuation candidate. The previous full suite result (`1797 passed, 16 skipped, 10 failed`) is historical and predates these changes; baseline-attributed failures remain as previously documented. No full-suite PASS is claimed until the single final run.
- Tasks 4.1 and 4.2 remain open: the eight approved Stitch states have not all been visually matched, and dialog focus management, complete contrast/reflow audit, and human visual validation are not yet evidenced. Task 6.6 remains open pending human merge and deployment authorization. Linux system-bus integration and real post-deployment E2E remain external gates. No production, N01, scheduler, PR #160, or user-owned untracked design input was accessed or changed.

### One full-suite run for the continuation candidate

Command: `MINIME_RUNTIME_ROOT=/tmp/minime-pwa-test-runtime /tmp/minime-pwa-venv/bin/pytest -q`. No `MINIME_DATABASE_URL` was configured; local PostgreSQL at `/tmp:5432` was not accepting connections. The suite used its isolated test fixtures; no production DB URL was supplied.

Result: **1824 passed, 16 skipped, 7 failed, 8 warnings in 870.54s**. Failure identities and observed attribution:

| Test | Observed result / attribution |
|---|---|
| `tests/test_n01_main_advancement_reconciliation.py::test_cli_start_resolves_active_owner_through_p2_readiness_admission_and_handoff` | N01/intake reconciliation test failed in the monolithic order; its detailed run showed `Configured implementer 'codex' is unknown` before the test's expected handoff. This is outside the PWA diff. |
| `tests/test_n01_post_ready_saga_authority_postgres.py::test_post_ready_main_advancement_reaches_readiness_admission_and_job_handoff` | N01 durable saga/recovery test failure; outside the PWA diff. |
| `tests/test_orchestration_api_and_cli.py::test_api_admit_and_status` | Admission integration failure; outside the PWA diff. |
| `tests/test_orchestration_api_and_cli.py::test_api_admit_run_records_scheduler_decision` | Admission/scheduler-decision integration failure; outside the PWA diff. |
| `tests/test_stage_dispatch_integration.py::test_rejection_of_model_absent_from_codex_account_fails_closed_before_runner` | Test expected `NEEDS_HUMAN`, observed `WAITING_CAPACITY`; the upstream capacity gate prevented reaching the absent-model assertion. No provider was invoked. This is an existing agent-capability test path, not touched by this PWA continuation. |
| `tests/test_process_safety.py::test_process_ignoring_sigterm_is_sigkilled` | One-second timeout/process teardown test failed with a 1.1s observation. The same timeout sensitivity was previously reproduced on base SHA `8564afc51069bd334a67fd19a2a4f51cc0659f5e`; no confinement guard was changed here. |
| `tests/test_stage_c_isolation.py::test_onboard_project_rejects_runtime_collision` | Its fixture observed “outside trusted managed root” before the intended runtime-collision condition because the global test `MINIME_RUNTIME_ROOT` overrode its local service path. The fixture was corrected after the full run to explicitly set its runtime root inside its trusted root; focused rerun passed `1 passed in 0.52s`, plus Ruff check/format. The full suite was not repeated. |

Earlier work recorded that the five N01/orchestration/account-model tests pass as a focused group on current and base and that the process timeout is baseline-reproducible; the single monolithic run still failed those identities and they remain visible rather than being called PASS. The full run preceded only the Stage C fixture correction and its focused confirmation; it is not a green full-suite result for the exact final tree.

Warnings: Starlette/httpx deprecation, three duplicate FastAPI OpenAPI operation IDs, Alembic `path_separator` deprecation, and async-mock coroutine warnings in pre-existing Stage C tests. The 134-test post-removal PWA regression remains separately green; the additional native-dialog focus test passed separately. Global checks were run before the Stage C fixture-only correction; the corrected Stage C file then passed its own Ruff check and format check. OpenSpec strict, Node syntax, and `git diff --check` passed before that test-only correction.

## Final continuation check after operational controller extraction and orphan retirement

After discovering that the Backlog clarification frontend omitted the required `question` field from the existing API request, the controller now submits both the currently selected human question and the operator answer, clears the form target after success, and refreshes the authoritative item. The real-Chrome controller test passed alone (1 passed in 5.14s). A shared-fixture attempt to exercise the full API answer→re-prepare lifecycle correctly failed closed because its seeded project has no canonical `ProjectManagedRepositoryBinding`; no fixture authority was fabricated. The consolidated affected group was rerun after the code correction and passed **113 passed, 4 warnings in 81.64s**. It includes all prior PWA/API/Control Plane/security/systemd observer tests plus the clarification serialization test.

After the Projects/Backlog browser test was extended to verify logout clears its project and detail state, one consolidated run exposed that the test also revoked the module-scoped session token used by a later selected-Change browser case. The test now creates a fresh session only after the logout-clearing assertions; it does not weaken revocation or cache-isolation checks. The ordered pair passed **2 passed in 10.33s**, followed by the complete affected group:

```text
112 passed, 4 warnings in 85.35s
```

The four warnings remain the known Starlette/httpx deprecation and three duplicate FastAPI OpenAPI operation IDs. This result is the latest affected-group run.

A source/import/asset census also proved no runtime or test consumer for these obsolete files: `components/attention_banner.js`, `components/efficiency_panel.js`, `components/runs_table.js`, `views/history_view.js`, and `views/settings_view.js`. The retired efficiency helper had unsupported fallback values (`100%` and zero counts); it was not used by the active, API-backed telemetry path. Those five files and the Service Worker cache entries for the two cached modules were removed. Static regression asserts the obsolete paths are absent and not cached. No active renderer, API contract, permission gate, or operator-visible behavior was removed.

After this retirement, the changed controller wiring, and adding the Chrome stale-detail response test, the final consolidated affected group passed:

```text
tests/test_pwa_real_browser.py
tests/test_pwa_service_worker.py
tests/test_pwa_assets.py
tests/test_pwa_contract.py
tests/test_dashboard_ui.py
tests/test_dashboard_api.py
tests/test_dashboard_security.py
tests/test_dashboard_stale_isolation.py
tests/test_dashboard_service.py
tests/test_preview_api_endpoints.py
tests/test_control_plane_api.py
tests/test_control_plane_service.py
tests/test_pwa_desktop_layout.py
tests/test_systemd_scheduler_observer.py
112 passed, 4 warnings in 89.02s
```

This is the post-orphan-removal regression group; it is not the full repository suite and does not complete tasks 5.1–5.3 because the complete consumer matrix and legacy-coordinator removal have not occurred. Latest static checks were run before this final small orphan retirement; they must be rerun on the candidate before commit. The earlier full suite result and its baseline attribution remain unchanged and are not represented as post-change PASS.

## Continuation from `bf0e29cf6534ddc9500bcfac08034f95fe383975`

This later continuation preserves the subsequently accepted completion evidence for 5.1–5.3 recorded in `tasks.md` and the Removal Gate section; the preceding paragraph is a historical checkpoint note and is superseded for the current Change status.

The eight approved reference images were visually re-inspected against five mock-seeded real-Chrome captures plus the desktop running-drawer capture. `evidence/visual-comparison.md` records all eight independently. Three states remain unavailable for ethical/authenticity reasons: intentional `PAUSED`, `READY_FOR_HUMAN_MERGE`, and tablet human-review evidence do not exist in the disposable backend. The two desktop and tablet active states and mobile active supervision are only partial visual matches; no screenshot literals were used as application facts. Tasks 4.1 and 6.3 remain open.

Real Chrome found and drove four scoped UX corrections: tablet master list compacting extended through 1199px; mobile pipeline labels converted from a compressed horizontal row to a readable vertical list; mobile status filters wrap rather than requiring hidden horizontal scrolling; desktop drawer width bounded to 54vw/780px. The real browser also checks essential-text clipping, viewport overflow, keyboard/dialog focus, both themes, contrast tokens, reduced motion, names/landmark and touch targets. After these final corrections, the combined viewport/accessibility/keyboard set passed **3 passed in 13.85s**. Global `ruff check src tests`, scoped `ruff format --check tests/test_pwa_real_browser.py`, `openspec validate pwa-control-center-ux-convergence --strict`, and `git diff --check` passed. Repository-wide `ruff format --check src tests` still reports 75 files outside the targeted changed Python test; no unrelated mass formatting was applied.

A separate authenticated Chrome test ran the containerized preview against the loopback-only disposable PostgreSQL database `minime_pwa_e2e` (schema verified at Alembic head). It demonstrated exact persisted project/change/Run/Job reads, absent candidate as absent, unauthenticated 401, non-allowlisted 403, a server-discovered and confirmed Control Plane CANCEL, durable action result with matching cancelled Run/Job, and denial of a stale competing action. This establishes task 6.2; the exact final-commit image digest/rerun is pending. The test owns unique disposable `qa-pwa-*` records and tears down the app container. It does not access production, N01, scheduler or PR #160.

Task 6.1 remains open until the disposable-preview run also demonstrates stale, malformed and offline degradation end-to-end; related real-Chrome unit/fixture cases do not replace that preview-level evidence. Task 6.4's candidate-bound human checklist is prepared in `evidence/human-validation-checklist.md`, but the exact committed head/image digest and owner's actual result remain pending. Task 6.6 remains strictly post-merge/deployment and unexecuted. The prior full suite and its 7 failures are historical; the single full suite for this continuation is recorded below and will not be repeated here.

### Single full-suite run for commit `19a1e9031493046701c51dde13da528f756ff94d`

Command:

```text
env -u MINIME_DATABASE_URL -u MINIME_TEST_DATABASE_URL -u MINIME_TEST_POSTGRES_CONTAINER \
  MINIME_RUNTIME_ROOT=/tmp/minime-pwa-final-runtime-19a1 \
  MINIME_PWA_EVIDENCE_DIR=/tmp/minime-pwa-final-evidence-19a1 \
  /tmp/minime-pwa-ux-20261018/bin/pytest -q
```

Result: **1777 passed, 17 skipped, 55 failed, 8 warnings in 989.05s**. This is not a PASS. Two validation-environment preconditions were wrong: `/tmp/minime-pwa-final-runtime-19a1` did not exist, so confined subprocess/check runners returned `Runtime root is not an available directory` / `ENVIRONMENT_UNAVAILABLE`; and no test PostgreSQL URL was supplied, intentionally preventing any test from selecting an unverified database. Consequently confinement/check-runner/process tests and PostgreSQL integration cases lacked valid prerequisites. Their failures cannot be attributed to this PWA Change or called pre-existing from this run. Other failures surfaced in N01/orchestration, legacy candidate resolution and review paths; those remain unresolved/unattributed and were not changed here. The final pytest summary names failures across candidate-manifest/remediation, check-runner safety, CLI preflight, DeepSeek audit, execution pipeline, human/legacy candidate resolution, N01 reconciliation, orchestration admission/coordinator, process safety, PWA desktop-layout preferences, review pipeline, scheduler recovery, stage dispatch, waiting capacity, and worktree/runner tests. No second full-suite run is planned in this intervention.

The targeted runs remain valid and separately reported: final real-Chrome viewport/accessibility/keyboard set **3 passed in 13.85s**; exact-commit containerized authenticated preview/control-plane test **1 passed in 11.10s**. The latter built `minime-pwa-e2e:19a1e9031493`, image ID `sha256:952a981cd4d3fefa60f678480d18d022e6991f21d22849b997ba6ea43af86e72`, running as non-root `minime`, against loopback-only disposable PostgreSQL `minime_pwa_e2e` at Alembic head. Preview container teardown succeeded; only the disposable PostgreSQL container remains active.

### Desktop preference regression found by the single suite

The full run's `tests/test_pwa_real_browser.py::test_real_browser_desktop_layout_preferences_are_bounded_and_operator_scoped` failure was reproduced once as a focused real-Chrome test: **1 failed**. At 1440×900, the authenticated page and `#viewExecutions` have nonzero width, but `#viewExecutions .content-split` computes to `display: contents` with a zero-width box. The final desktop CSS cascade also hides `.pane-divider`; the layout initializer consequently cannot size the splitter. This is an implementation/verification contradiction in the candidate, not an environment or N01 failure. No dashboard controller refactor was started, and this intervention does not mark 7.3 complete; `tasks.md` reopens it with the exact observed cause. The UI requirement must be resolved before implementation-ready status.

The full suite was not compared with base `8564afc51069bd334a67fd19a2a4f51cc0659f5e` under an equivalent configured runtime/database: the candidate invocation accidentally omitted a disposable test database URL and named a runtime root that did not exist. Therefore none of its non-environment failures is attributed to baseline or to this Change on that run. We did not run the full suite again; the missing runtime-directory and DB prerequisites are recorded as execution-environment errors, while the desktop preference regression is separately reproduced. The previously reported N01/orchestration failures remain untouched and unattributed here.
