# Design

## Context

See `proposal.md` for motivation and scope. The read-only inventory before design confirms 26 files under `src/minime/tui/`, a `textual` dependency, TUI/legacy imports in CLI and API, multiple HTTP 410 handlers in `src/minime/api/app.py`, and tests importing `legacy_unavailable`. The repository also contains durable job/orchestration abstractions, so names such as `job`, `scheduler` or `orchestration` cannot be removed by textual matching alone. The existing Angular static build and active FastAPI/provider/auth paths are the preservation boundary.

## Goals / Non-Goals

**Goals:**

- Establish one evidence-backed inventory of callers, writers, imports, routes, CLI registrations, dependencies, tests, migrations and durable references.
- Remove only proven-orphaned TUI, legacy 410, OpenSpec-emulation and obsolete-test surfaces, including exclusive dependencies and registrations.
- Preserve active orchestration, worktree, provider, GitHub, auth, budget, API and Angular capabilities.
- Use conservative Alembic migrations only for schema objects proven obsolete, with database identity, backup and rollback evidence.
- Prove the retained behavior and absence of retired entrypoints after deletion against an immutable candidate SHA.

**Non-Goals:**

- No implementation of F7/F8 behavior, new scheduler/queue, second API, replacement terminal UI or new OpenSpec workflow.
- No deletion or mutation of archived OpenSpec artifacts, applied migrations, audit trails, candidate/worktree history or legitimate operational jobs.
- No production deployment, scheduler restart, paid agent invocation or remote ticket closure as part of planning or implementation evidence.

## Decisions

### Inventory before removal

The implementer SHALL build the removal ledger from static imports/references, package metadata, route/CLI registration, dependency injection, configuration, migrations and tests, then supplement it with focused runtime checks for dynamic/reflection/plugin paths. Every target is classified REUSE, MODIFY, REMOVE or RETAIN-WITH-REASON. The initial ledger is:

| Target | Initial action | Required proof / boundary |
| --- | --- | --- |
| `src/minime/tui/` and Textual dependency | REMOVE | No imports or supported command; Angular PWA is active UI |
| Exact CLI paths: legacy `minime run`, `minime console`/`tui`, `minime readiness`, `minime discover`, `minime providers openrouter`, and scheduler/queue/orchestrate/action groups | REMOVE where exclusive legacy | Preserve active `minime request run`, `minime providers health`, `minime serve`, and any other provider/auth/diagnostic command discovered by census; `run` alone is not a removal target |
| API 410 legacy dashboard/orchestration/control-plane/queue/scheduler/previews/validations/jobs | REMOVE where no compatibility consumer | Preserve active `/api/v1/projects`, `/requests`, `/auth`, health/status, providers/health and budget paths |
| `legacy_unavailable` | REMOVE if no retained compatibility caller | If a legitimate caller remains, keep minimal unavailable contract |
| OpenSpec generators, semantic parsers, local sync/archive/verifier flows | REMOVE if orphaned | Preserve official CLI inspection and identity/evidence handoff |
| domain/UoW/repositories and DB tables | REMOVE only when exclusive and durable-safe | Preserve jobs, claims, attempts, evidence, auth, budget and audit history used by active flows |
| tests/mocks | REMOVE if exclusive to retired surface | Keep real active contract/regression/E2E coverage |

### Preserve the native boundary

The change will use the installed OpenSpec `apply`/`verify` workflows for implementation and verification. mini me code may retain structural inspection and repository identity/evidence protection, but it will not author semantic artifacts, merge Markdown, parse requirements to generate behavior, or emulate sync/archive. This preserves the official agent-side ownership boundary.

### Retire the UI as a package, not as a compatibility shim

Once the census proves no active console consumer, remove the entire TUI package, registrations, Textual dependency, TUI-only styles/assets and tests in one coherent diff. No replacement terminal command or 410 shim will be added. The Angular build and supported FastAPI contracts remain the only operator surface.

### Remove routes only after active-route regression coverage

Before deleting API decorators, the implementer will identify active consumers and run focused retained-route checks. After deletion, route discovery and a real API flow will prove the retired paths are absent while projects, requests, auth, health/status, provider health and budget remain available. A compatibility route is retained only with an explicit consumer and reason.

### PostgreSQL is fail-closed

Schema retirement is conditional, not presumed. For each candidate table/column, inspect SQLAlchemy models, repositories, UoW wiring, migrations, fixtures, scripts and runtime writers/readers. If database identity, backup, retention obligation or rollback cannot be proven, leave the schema unchanged and record `RETAIN-WITH-REASON`; do not manufacture a destructive migration. Any approved removal is a versioned Alembic migration with upgrade, physical postcondition and downgrade/rollback evidence.

For every approved Alembic retirement, collect backup and rollback evidence in the candidate evidence bundle before changing the database: record the immutable candidate SHA and migration revision, capture `SELECT current_database(), current_user, inet_server_addr(), version(), current_setting('server_version_num')` plus the relevant schema/search path, create a PostgreSQL custom-format `pg_dump` of the identified database, and record its SHA-256 checksum and `pg_restore --list` manifest without exposing credentials. Apply the migration in an isolated disposable database restored from that dump, capture `alembic current`, catalog queries proving the intended object is absent, and the command exit status. Then run the tested Alembic downgrade in that disposable database, capture its exit status and catalog queries proving the rollback postcondition, and retain the dump checksum, command logs and database identity alongside the before/after schema manifests. If restore, upgrade, downgrade, identity matching or postcondition evidence is missing or non-zero, classify the object `RETAIN-WITH-REASON` and do not apply the retirement migration to the candidate database.

### Removal Ledger and evidence

The implementation evidence will record: replaced behavior; exact old entrypoints/writers; reachability/consumers; historical owners and data not removed; new authority; action; static and dynamic evidence; candidate SHA; tests before/after removal; dependency metadata and lockfile evidence; and final no-caller/no-duplicate state. This ledger is the traceability mechanism for the retirement requirements and does not replace OpenSpec validation.

### Executed Removal Ledger

The census produced this concrete ledger, applied in one coherent diff:

| Surface | Action | Evidence / boundary |
| --- | --- | --- |
| `src/minime/tui/` (53 files) | REMOVE | `git rm -r`; `grep -rn "minime.tui" src/` returns no remaining import |
| `textual>=0.70.0` in `pyproject.toml` | REMOVE | dependency line removed; no retained `import textual` |
| Legacy CLI stubs in `src/minime/cli/main.py`: `run`, `readiness`, `discover`, `tui`, `providers openrouter`, `scheduler status\|tick`, `queue list\|explain`, `orchestrate *`, `action *` | REMOVE | `minime scheduler run` (live daemon), `minime providers health`, `minime serve`, `minime request *` preserved; CLI imports clean |
| 41 standalone API `410 Gone` routes in `src/minime/api/app.py` plus the middleware legacy-path map (`LEGACY_UNAVAILABLE_PREFIXES`, `_legacy_operation_for_path`) | REMOVE | `grep unavailable_payload\|HTTP_410_GONE src/minime/api/app.py` returns none; active `/api/v1/projects`, `/requests`, `/auth`, `/health`, `/status`, `/providers/health`, `/budget` preserved |
| `src/minime/services/legacy_unavailable.py` | REMOVE | last consumer removed; no remaining `unavailable_payload` reference |
| Obsolete tests: 13 functions across `test_google_auth`, `test_no_query_write_locks`, `test_resilience_observability`, `test_status_observability`, `test_orchestration_continuity`, plus `test_preview_api_endpoints.py` | REMOVE | retained suite no longer asserts removed 410/TUI behavior |

**Proof artifacts**: `import minime.api.app` and `import minime.cli.main` succeed; full suite is 981 passed with only pre-existing failures unrelated to F12; no retired symbol is invoked at runtime beyond static results.

## Risks / Trade-offs

- **Dynamic import or reflection is missed** → inspect DI/configuration/plugin paths and run retained startup/API/CLI journeys before deletion; fail closed on ambiguity.
- **A durable job/history table is mistaken for dead state** → require writers/readers, migration and retention census; preserve audit/candidate/attempt/worktree data unless rollback and ownership are explicit.
- **Removing 410 routes breaks an undocumented client** → verify active frontend/API callers and retain only a proven compatibility contract with a recorded reason.
- **Angular static assets are confused with legacy templates** → trace the production build manifest and serve path before deleting any static file.
- **Tests pass only because mocks hide a regression** → distinguish unit mocks from integration/E2E, run retained real interfaces after deletion, and fail closed for missing evidence.
- **Large cleanup obscures unrelated changes** → keep the Change to the listed F12 targets, preserve unrelated dirty work, and use the exact candidate SHA for review.

## Migration Plan

1. Freeze the candidate identity and capture the pre-change inventory and baseline retained-path checks.
2. Implement the ledger, remove proven-orphaned code/dependencies/tests/routes, and add only required conservative Alembic migration(s).
3. Run static reachability/dependency checks, focused unit/integration tests, retained API/CLI journeys and applicable real E2E checks.
4. Re-run the same evidence after removal, verify no retired entrypoint remains, and record any `RETAIN-WITH-REASON` blocker.
5. Rollback application changes through Git candidate replacement; rollback database changes through the tested Alembic downgrade validated from the checksummed PostgreSQL dump and catalog postconditions. If the dump restore, database identity, downgrade or postcondition evidence is not proven, do not apply the migration.

## Open Questions

None. Any newly discovered material consumer, database identity ambiguity or compatibility obligation requires an OpenSpec update or human decision before implementation proceeds.
