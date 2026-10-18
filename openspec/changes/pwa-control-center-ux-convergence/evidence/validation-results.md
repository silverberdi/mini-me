# Local validation evidence

Candidate branch: `proposal/control-center-ux-convergence`.
Starting candidate HEAD for this continuation: `b0c798233142681119f004c3fe039fea838d6473`.
Test host: macOS / Python 3.14.5. Test runtime: `/tmp/minime-pwa-test-runtime` via `MINIME_RUNTIME_ROOT`; no production service or database was accessed.

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

- Frontend convergence/removal is incomplete: `dashboard.js` remains a large coordinator (2,029 lines after Backlog/evidence view extraction) and owns significant UI workflows. Modules extracted so far are live imports, but complete consumer parity and Removal Ledger proof are not established. Do not mark tasks 5.1–5.3 complete or claim architectural convergence.
- The five viewport checks do not complete the eight approved visual states, keyboard/accessibility audit, or human validation. Task 7.3 is now verified; tasks 4.1, 4.2, 7.2 and human visual acceptance remain open.
- Authenticated preview/container E2E, governed action lifecycle E2E, complete-value states (including an authoritative deliberate PAUSED source), post-merge/deployment verification, and real Linux systemd observation remain pending.
- No task requiring human approval, merge or deployment is complete.
