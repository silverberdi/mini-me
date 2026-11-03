# Tasks

## 1. Baseline and removal inventory

- [ ] 1.1 Capture candidate/base SHA, repository/worktree identity and baseline retained API/CLI/UI checks; verify the evidence names the exact candidate and does not invoke paid providers.
- [ ] 1.2 Build the F12 Removal Ledger for TUI, CLI, API, static assets, legacy services, OpenSpec emulation, tests, dependencies, domain/UoW objects and DB objects; verify each item is classified REUSE, MODIFY, REMOVE or RETAIN-WITH-REASON with callers/writers and historical owners, and record the runtime trace evidence as a separate artifact reference. The concrete ledger (targets + evidence) is recorded in `design.md` → "Executed Removal Ledger".
- [ ] 1.3 Trace the Angular production build manifest and active FastAPI consumers; verify files marked legacy are not part of the active build and retained routes have identified consumers.
- [ ] 1.4 Census dynamic imports, dependency injection, configuration, scripts, migrations, fixtures, reflection and runtime route/CLI registration; verify ambiguous consumers block deletion rather than being guessed dead.
- [ ] 1.5 Instrument focused dynamic call tracing for each candidate consumer path, exercise startup, retained API journeys and supported CLI/plugin entrypoints, and correlate observed call targets with the Removal Ledger; verify no retired symbol is invoked at runtime beyond static-analysis results, with missing or ambiguous traces failing closed.

## 2. Retire terminal and legacy public surfaces

- [ ] 2.1 Remove `src/minime/tui/` and all exclusive styles/assets/imports; verify no active Python module imports `minime.tui` and the package is absent from the source tree.
- [ ] 2.2 Remove the `minime console`/`tui` command and the specified dead CLI groups only where the ledger proves they are legacy; verify CLI help and supported commands contain no retired registrations and preserved adapters still load.
- [ ] 2.3 Remove legacy static templates/scripts not used by the Angular production build; verify the Angular asset manifest/build remains complete and no active route references deleted assets.
- [ ] 2.4 Remove proven-orphaned 410 API decorators and legacy service callers, including dashboard/orchestration/control-plane/queue/scheduler/preview/validation/job paths; verify route discovery and focused API calls show absence without changing retained API behavior.
- [ ] 2.5 Remove `legacy_unavailable` and its exclusive tests only if no compatibility caller remains; otherwise retain the minimal contract and document the consumer and reason in the ledger.
- [ ] 2.6 Remove `textual` from `pyproject.toml` and any applicable lock/dependency metadata; verify no retained import, optional extra or installation path requires it.

## 3. Retire emulation, persistence and obsolete tests safely

- [ ] 3.1 Remove orphaned OpenSpec generators, semantic parsers, local verifier/sync/archive substitutes and exclusive callers while preserving official CLI structural inspection and repository/evidence identity; verify no application code authors or mutates semantic OpenSpec artifacts.
- [ ] 3.2 Remove only domain models, UoW methods, repositories and configuration proven exclusive to retired flows; verify active orchestration, jobs, attempts, claims, evidence, auth, budgets and worktree ownership still have complete readers/writers.
- [ ] 3.3 For each proven-obsolete PostgreSQL object, add a versioned Alembic migration only after authorized database identity, backup, retention and rollback are established; verify upgrade, physical postcondition and safe downgrade, or leave it RETAIN-WITH-REASON when any proof is missing.
- [ ] 3.4 Delete tests and artificial mocks exclusive to removed surfaces, preserving real active contract/regression coverage; verify the retained test selection no longer imports retired modules or asserts removed 410/TUI behavior.

## 4. Validate retained capability and retirement

- [ ] 4.1 Run formatting, lint, typing and focused unit/integration checks configured by the repository; verify exit code 0 and record failures without weakening assertions or adding synthetic skips.
- [ ] 4.2 Run real retained API journeys for projects, requests, auth, health/status, providers/health and budget with authorized test data; verify observable responses/effects and candidate SHA binding.
- [ ] 4.3 Run the applicable real Angular production build and browser/API integration checks; verify the build serves the retained PWA without legacy static dependencies.
- [ ] 4.4 Run the post-removal real E2E journey through preserved coordination, provider-adapter, Git/worktree and evidence paths as authorized; verify invocation, result and effects are observed rather than mocked.
- [ ] 4.5 Re-run static reachability, route/CLI discovery, dependency audit and retained suite after deletion; verify no retired entrypoint, import, dependency, duplicate route or fallback remains and all retained tests exit 0.
- [ ] 4.6 Produce the final Removal Ledger and evidence bundle with candidate SHA, migration revision/database identity where applicable, rollback result, retained-path effects and unresolved human gates; verify fail-closed status for any missing or ambiguous evidence.

## 5. Official workflow closure evidence

- [ ] 5.1 Execute this F12 Change through the installed native OpenSpec apply and verify workflows in the authorized mini me worktree; verify the trace identifies the agent skill/command and does not use a generator, prompt substitute or semantic verifier.
- [ ] 5.2 Verify the Change remains within F12 and does not deploy, restart a scheduler, activate F7/F8, consume unauthorized budget, merge code or close the remote Request; verify any required human authorization is recorded separately.
