# Local validation evidence

Candidate branch: `proposal/control-center-ux-convergence`.

## Focused Control Center validation

- Dashboard/PWA/systemd/TUI focused group: 81 passed; the first consolidated run exposed a test-fixture issue in the new authentication-expiry case (the shared browser session had already been revoked by another test). The test now creates and revokes its own session.
- Real Chrome browser suite after that correction: 12 passed, including all five viewport captures, offline/reconnect, auth expiry, service-worker cache inspection and two-operator cache isolation.
- Earlier API/systemd/service-worker/layout targeted set: 40 passed.
- Ruff check over all `src` and `tests`: passed.
- Ruff format check over changed Python files: passed.
- `openspec validate pwa-control-center-ux-convergence --strict`: passed.
- `git diff --check`: passed.

## Repository-wide validation

One full `pytest -q` run completed: 1,751 passed, 16 skipped, 54 failed. The failures span existing process-confinement, candidate checks, provider dispatch, orchestration, lifecycle, PostgreSQL integration and review tests. A representative repeated failure is `Runtime root is not an available directory` from the check/implementer runners in this macOS environment. These paths are outside this Change and were not altered to make the suite appear green. No PostgreSQL URL was configured in this shell, so the run could not connect to a remote database.

Repository-wide `ruff format --check src tests` reports 75 files requiring formatting; the touched Python files pass their scoped format check. No mass-format rewrite was performed.

## Evidence limits

The five `*-mock-seeded.png` files under `evidence/browser/` were captured by real Chrome against an in-memory test fixture at the documented viewports. They prove rendered layout and overflow checks only. They do not prove production data fidelity, comparison against all eight Stitch states, containerized preview behavior, human UX acceptance or post-deployment behavior. Those OpenSpec tasks remain pending.

The actual system D-Bus/systemd read cannot be exercised on this macOS host; the observer is covered by deterministic timeout, malformed, stale, inaccessible and state-projection tests and fails closed to `UNKNOWN` when unavailable.
