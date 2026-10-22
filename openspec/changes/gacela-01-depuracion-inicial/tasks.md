## 1. Baseline and removal ledger

- [x] 1.1 Capture the candidate base SHA, Alembic head, configured scheduler state, process observation, and PostgreSQL schema/FK/index/row-count inventory without invoking agents or changing runtime state; save redacted evidence.
- [x] 1.2 Produce the F1 Removal Ledger for every identified writer, caller, DI/config registration, API/CLI/UI entry point, test, package dependency, model, repository, table, column, index and foreign key; mark REMOVE, MIGRATE, RETAIN-WITH-REASON, or F2–F6 reservation with evidence.
- [ ] 1.3 Update the historical reconciliation inventory and Removal Ledger in `design.md` with every non-archived Change/spec, its slug, filesystem status, durable/external reference, contract conflict and owning F2–F6 phase; record the future native OpenSpec update/sync/archive route without invoking it, retain command output as evidence without creating a separate report, and stop for human direction if a live process or external operation is found.
- [x] 1.4 Take and verify a protected representative PostgreSQL backup/restore before any destructive migration; document the recovery owner and the exact restoration command without storing secrets.

## 2. Retire OpenSpec emulations and legacy execution graph

- [x] 2.1 Remove `OpenSpecGenerator`, its deterministic artifact writers and all Intake/Reconciliation/publishing callers, generator-specific fixtures and dependencies; preserve installed official OpenSpec skills, `OpenSpecAdapter`/official CLI status and structural validation, and the ledger-backed repository/worktree/candidate/evidence identity substrate needed by F3, without retaining a semantic dispatcher. Evidence: removed generator/intake call graph; retained `OpenSpecAdapter` read-only integrity route and repository/worktree protections; F1 denial regression passes.
- [x] 2.2 Remove `OpenSpecSyncService` semantic merge/archive behavior and `PostMergeReconciliationService` consumers that write OpenSpec/closure state; retain separately justified Git/worktree safety checks without semantic replacement. Evidence: service modules and callers removed; no native Change directory is mutated by F1 tests or API/CLI boundaries.
- [x] 2.3 Remove or disable legacy verify, apply, pipeline, orchestration, recovery and prompt-runner paths that advance or emulate OpenSpec workflow stages; ensure no provider invocation, candidate mutation or spending path remains reachable through them. Evidence: direct 410 API routes and exit-2 CLI boundaries contain no retired service construction; `tests/test_f1_legacy_retirement.py` passes.
- [ ] 2.4 Remove obsolete service wiring, domain interfaces/models, imports, tests and dependencies made exclusively unreachable by 2.1–2.3; preserve useful regression coverage by converting it to retained/denial contracts.
- [ ] 2.5 Add focused tests proving that proposal preparation, apply/verify/orchestration, sync and archive requests cannot create semantic OpenSpec artifacts or report synthetic success, and that read-only artifact/repository inspection still works.

## 3. Retire duplicate admission and public surfaces

- [x] 3.1 Remove local backlog projection/intake generation, discovery, queue, scoring, classification and scheduler behavior after all callers have moved to explicit disabled outcomes; do not introduce a replacement queue or scheduler. Evidence: context discovery is read-only and reports zero discovered work items; scheduler config stays disabled and queue API/CLI deny.
- [x] 3.2 Remove or convert affected FastAPI endpoints, CLI commands, background hooks, PWA/TUI actions and dashboard projections so every retained legacy operation returns a machine-readable unavailable result (API) or non-zero actionable failure (CLI), naming the owning future phase. Evidence: API direct 410 responses, CLI exit 2, importable TUI denial, and transition-only PWA test pass.
- [x] 3.3 Preserve and regression-test FastAPI authentication, useful project registration/configuration, Git/GitHub bindings, worktree isolation, authorization/secret boundaries and retained read-only diagnostics. Evidence: focused retained suite (`78 passed, 1 warning`) includes Google auth, budget/provider diagnostics, worktree/runner confinement and project-facing API contracts.
- [x] 3.4 Verify with focused static and runtime reachability checks that scheduler ticks, fresh admission, ranking, agent dispatch, historical Change execution and provider spend cannot be triggered after retirement. Evidence: final symbol search finds no executable legacy service callers; F1 API/CLI denial tests and provider diagnostics run without dispatch.

## 4. PostgreSQL retirement and recovery

- [ ] 4.1 Reconcile the preflight ledger against representative populated PostgreSQL data and constraints; approve exact F1 drop candidates (`backlog_items`, queue/decision structures, classification snapshots and related fields only when proven) and record all retained/reserved structures with reasons.
- [ ] 4.2 Implement one new Alembic revision from the real head that removes only approved obsolete tables/columns/indexes/foreign keys, migrates or safeguards required data, and leaves historical migrations untouched.
- [ ] 4.3 Exercise upgrade, downgrade and protected-backup restoration on empty and representative populated PostgreSQL databases; prove retained auth/project/repository/worktree records remain valid and dropped structures have no live repository/model caller.

## 5. Post-retirement acceptance evidence

- [x] 5.1 Run Ruff, relevant type/static checks, and the focused unit/integration suites after all removals; record commands, revisions and failures/resolution against the candidate SHA. Evidence: `ruff check src/minime tests`, `node --check src/minime/static/js/dashboard.js`, and focused retained suite passed before final commit.
- [ ] 5.2 Run a real local API/CLI functional scenario with authentication and retained project/repository diagnostics, plus denied invocations of each retired API/CLI operation; prove no job, run, queue item, agent call or external side effect is created.
- [ ] 5.3 Run the runnable application in its supported local/container test environment and verify UI/TUI surfaces neither expose active legacy execution controls nor claim unavailable operations succeeded; no production deployment is performed.
- [ ] 5.4 Complete the Removal Ledger and reconciliation inventory in `design.md`, with references to final symbol/caller searches, before/after database evidence, Alembic revision, test results, candidate SHA and any approved RETAIN-WITH-REASON exceptions; retain execution evidence without creating a separate report.
