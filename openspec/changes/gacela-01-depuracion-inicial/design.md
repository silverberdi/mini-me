## Context

See [proposal.md](proposal.md) for motivation and the three delta specifications for behavioral commitments. The `2b76c592` baseline contains a legacy control plane whose responsibilities overlap OpenSpec and the ticket source. The F1 implementation must be a deletion-led change: it may add only the smallest explicit unavailable boundary, the new Alembic revision, and proof fixtures required to retire code safely.

### Observed responsibility and consumer inventory

| Responsibility today | Concrete owners and direct consumers | F1 classification |
| --- | --- | --- |
| Semantic creation of proposal/design/spec/task Markdown | `OpenSpecGenerator`; `IntakeService._load_or_generate_openspec`; `IntakeReconciliationService`; intake workspace publishing and generator-specific tests | **REMOVE**. Native agent `openspec-propose` is the semantic authority; F3 will connect it. No Python replacement. |
| Semantic merge and archive of OpenSpec | `OpenSpecSyncService.sync_change_specs/archive_change`; `PostMergeReconciliationService`; `ControlPlaneService`, `RecoveryConvergenceService`, `SchedulerService`; post-merge/lifecycle tests | **REMOVE**. F3 will invoke native sync/archive. Preserve only non-semantic Git/worktree identity checks where separately useful. |
| Semantic completion/transition substitute | `VerifyGate`, `ExecutionPipelineService`, `OrchestrationService`, `NativeOpenSpecApply`, `implementer_runner`, reviewer/auditor prompt runners and their API/CLI dispatches | **REMOVE/DISABLE** where the responsibility is legacy workflow execution. F3 owns the replacement flow; no dispatch, provider spend, or candidate mutation in F1. |
| Local ticket intake, backlog projection, priority and autonomous admission | `IntakeService`, `ReadinessService`, `WorkDiscoveryService`, `SchedulerService`, `classification_rules`, `TaskClassifier`, `TaskComplexityRiskClassifier`; scheduler observer; queue endpoints/commands/UI | **REMOVE/DISABLE**. GitHub will be the F2 ticket source; F1 has no ticket selection or autonomous start. |
| Durable recovery/sagas/claims and external action retries | `RecoveryConvergenceService`, `SagaEngine`, `RestartRecoveryService`, `PostMergeReconciliationService` | **RESERVE F3** after real process/DB evidence distinguishes minimal continuation from legacy execution. Do not delete merely because it is complex. It must not drive retired paths in F1. |
| Native OpenSpec integration reusable by F3 | Installed official OpenSpec skills, `OpenSpecAdapter`, CLI status/instructions/structural validation, `OpenSpecIntegrity` read-only callers, repository/worktree binding and candidate/evidence identity records with retained consumers | **CONSERVE** subject to focused tests. Preserve skills and the non-semantic dispatch/identity/evidence boundary needed to invoke and evidence a future native workflow; it may inspect native artifacts and CLI results but SHALL NOT generate, merge, archive, infer or mutate their semantic content. |
| Project identity, repository safety and worktree isolation | project/binding services, `GitHubAdapter`, `repository_identity`, `WorkspaceGuard`, `WorktreeManager`, managed repository/worktree ownership | **CONSERVE** subject to focused tests. They protect the future F2/F3 flow and do not author OpenSpec semantics. |
| Auth and secrets | FastAPI auth middleware, `AuthService`, authorized operators/sessions/audit tables | **CONSERVE**. |
| Preview, dashboard/PWA/TUI operator surfaces | preview/validation/dashboard/control-plane services and static/TUI clients | **RESERVE F5**, except remove widgets/routes exclusively showing retired queue/lifecycle actions; do not build the new UI now. |
| Provider-specific capacity, budgets, review/audit and efficiency engines | provider health/budget/reviewer/audit/efficiency services and their models | **RESERVE F3/F4/F6** until the configured-role policy is implemented. Disable only callers exclusively reached from removed legacy execution. |

### Persistent-state inventory

The implementation phase must regenerate this ledger from source references, database constraints and a representative populated PostgreSQL backup before destructive DDL. Initial candidates are:

| Structures | Evidence and F1 action |
| --- | --- |
| `backlog_items`; project backlog/roadmap/context-source fields introduced in `019_work_intake_and_backlog_items` | Used by Intake/Readiness/Discovery/Scheduler and backlog API. **REMOVE** only after all such callers and public surfaces are retired; GitHub remains source of tickets. Export/classify rows before DDL; preserve binding fields still required by project registration. |
| `work_queue_snapshots`, `scheduler_decision_records` (`014_autonomous_queue_work_selection`) | Repository owners are `PostgresWorkQueueRepository`/`PostgresSchedulerDecisionRepository`; production behavior is `SchedulerService`. **REMOVE** after scheduler/queue surfaces are gone and no foreign-key or live-data dependency remains. |
| `task_classification_snapshots` plus job/change snapshot references (`024_task_classification_snapshots`) | Produced/consumed by task classifiers and legacy pipeline/orchestration. **REMOVE** if the ledger confirms no retained continuity consumer; otherwise **RETAIN-WITH-REASON** for F3/F6. |
| `provider_efficiency_metrics` and legacy efficiency fields | Dashboard/API still consume them; the new contract has no efficiency optimizer. **RESERVE F6** unless the F1 caller census proves the whole surface is exclusively retired and data retention is settled. |
| `jobs`, attempts, runs, candidates, reviews/audits, sagas, claims, external actions, worktree ownership and provider/budget records | Extensive direct consumers, foreign keys and possible continuity evidence. **RETAIN** in F1, but quarantine all legacy execution entry points. Their later minimum shape belongs to F3/F6. |
| `projects`, bindings, managed repository bindings; auth tables | Explicit contract responsibilities. **RETAIN**. |
| previews/validation/operator action tables | Still consumed by UI/control-plane and linked to F5. **RESERVE F5/F6**. |

Historical Alembic revisions are immutable. F1 adds one revision from the actual head, with `upgrade` guarded by preflight/export evidence and a tested `downgrade`/restore procedure; it does not edit previous migration files.

### F1 implementation Removal Ledger (candidate worktree)

Observed against candidate base `aac7def3855625305978ec3cd8d3bcda207a372c`, with no mini me daemon/worker process observed. PostgreSQL listeners were present on ports 5432 and 54333, so neither was treated as an application target. The only write verification used a newly created disposable database on port 54333 and removed it after the test.

| Item | Callers/writers verified | Decision and F1 result |
| --- | --- | --- |
| `OpenSpecGenerator`, deterministic authoring, intake reconciliation and publishing | `IntakeService`, `IntakeReconciliationService`, generator tests | **REMOVE**: generator, intake and reconciliation modules deleted. Native installed skills, `OpenSpecAdapter`, structural validation and `native_openspec_apply` identity/evidence code remain. |
| Custom sync/archive and post-merge closure | `OpenSpecSyncService`, `PostMergeReconciliationService`, scheduler/recovery/control-plane graph | **REMOVE**: modules deleted. Historical Changes remain untouched; F3 must use installed native update/sync/archive after authorization. |
| Legacy pipeline/orchestration/scheduler/discovery/readiness/classification | API, CLI groups, TUI actions, service DI and legacy queue models | **REMOVE/DISABLE**: execution modules and classifiers deleted; API returns HTTP 410 with `code=operation_unavailable`; CLI legacy groups exit 2 before DB/provider access. No scheduler is configured to run. |
| Context inspection and project/Git safety | `ContextDiscoveryService`, project onboarding, `OpenSpecAdapter`, repository/worktree binding | **RETAIN**: context inspection no longer writes a local backlog. Auth, project registration, Git/GitHub binding, worktree isolation, secret handling and candidate/evidence tables remain. |
| `backlog_items` | Local intake/context projection only | **REMOVE**: no retained F1 consumer. Revision `gacela01_retire_legacy_admission_state` drops it; restore requires the protected pre-upgrade dump. |
| `work_queue_snapshots`, `scheduler_decision_records` | Scheduler ranking/admission only | **REMOVE**: no retained F1 consumer. Same revision drops both after scheduler entry points are denied. |
| `task_classification_snapshots`, `changes.latest_classification_snapshot_id`, `jobs.classification_snapshot_id` | Candidate/run evidence and future continuity review | **RETAIN-WITH-REASON (F3/F6)**: not dropped because the references are durable evidence and no approved replacement exists. |
| runs, jobs, candidates, worktree ownership, auth, project/repository binding, provider/budget evidence | Retained safety and continuity consumers | **RETAIN-WITH-REASON (F3/F6)**. F1 makes no execution path reachable through them. |

Progress update after `cd14d1dedce16b7032bbdf2dd798601536466cb6`: the executable sentinel aliases for removed PostgreSQL models and the three corresponding repositories have been removed from `src/minime/db/repository.py`. Direct backlog/queue/scheduler handlers now deny with `410 operation_unavailable` before any UoW call; the TUI has an importable F5-unavailable boundary; and the PWA bootstrap no longer imports or caches the backlog, lifecycle, action, execution or dashboard controllers. `WorktreeManager` no longer reads a local backlog item when resolving historical intake ownership. The unrelated R01 task/skill edits found in `cd14d1d` were reverted in the F1 worktree. Focused API/auth retirement tests passed (`18 passed`), process-confinement safety passed (`10 passed`), and the post-removal full suite reached `397 passed, 13 skipped` before an unrelated confinement timing defect was corrected; a subsequent complete-suite run remains required before F1 acceptance. Remaining F1 work is explicit: delete the residual legacy API/CLI handler implementations and their domain-only types, complete historical inventory, and complete the full-suite/E2E evidence. No task is marked complete from this progress update.

Progress update after `5e3d9ff7079f5d00446f3a5078a1f993396443ab`: CLI legacy command bodies were removed and replaced only by direct `exit 2` compatibility commands; retained CLI operations are project configuration, status, persisted provider/budget diagnostics and `serve`. API handlers formerly calling `ReadinessService`, `SchedulerService`, `OrchestrationService`, `OperationsDashboardService` or `ControlPlaneService` now deny directly; their `Any` aliases and intake DI were removed. The PWA uses DOM creation and `textContent` for operator identity, never interpolated `innerHTML`. `node --check`, Ruff, OpenSpec strict validation and the focused retained/denial suite passed (`32 passed, 1 warning`). A full surviving-suite attempt completed past 44% with no failure before the execution environment cut its output at 30 seconds; this is insufficient acceptance evidence, so tasks remain unchecked and no PR is authorized.

Final F1 classification update: retain FastAPI/authentication, project configuration, OpenSpec CLI adapter and structural inspection, Git/GitHub adapters, repository/worktree binding and confinement, PostgreSQL auth/project/binding/budget/evidence records, and read-only provider/budget/status diagnostics. Remove local backlog parsing and projection from context discovery; it now records only README/OpenSpec/check configuration facts and always reports zero work items. Legacy API/CLI/PWA/TUI execution surfaces remain explicit denials only. The retained verification set passed `78 passed, 1 warning`: F1 denials, Google authentication, PWA boundary, CLI diagnostics, provider/budget safety, worktree/runner confinement and API budget diagnostics. Ruff, `node --check`, and strict OpenSpec validation pass. The approved Alembic revision and its disposable-DB backup/upgrade/downgrade/restore evidence remain unchanged. Historical broad suites exclusive to scheduler, queue, intake, orchestration, dashboard and preview engines are not restored; their future replacement belongs to F2–F6. No scheduler, agent dispatch, migration or production operation was run.

Migration evidence: `.venv/bin/alembic upgrade r02_contract_review_budget_identity`, representative inserts, `pg_dump -Fc`, `.venv/bin/alembic upgrade head`, schema absence check, `.venv/bin/alembic downgrade r02_contract_review_budget_identity`, schema restoration check, database recreation and `pg_restore` all passed on `minime_gacela01_verify_18266`; that database was dropped. The protected dump is `/tmp/minime-gacela01-verify-18266.dump` and contains no credentials.

## Goals / Non-Goals

**Goals:**

- One deletion order that removes legacy writers before their consumers and database structures, leaving no silent compatibility path.
- A small fail-closed boundary for public operations whose replacement is F2/F3/F5/F6.
- Measurable preservation of FastAPI authentication, useful project/repository configuration, Git/GitHub integration, worktree isolation, secret handling and retained continuity evidence.
- An auditable reconciliation inventory for historical Changes/specs without treating their directories as active work.

**Non-Goals:**

- F2 project configuration/ticket-source implementation; F3 native lifecycle, agents, reviews, human interaction, PR and sync/archive; F4 skills; F5 UI; F6 remaining cleanup.
- New workflow engine, scheduler, recovery system, semantic verifier, queue, provider router, deployment system, API version, framework, service, or persistence abstraction.
- Applying/archiving/deleting historical Changes, starting services/jobs, running migrations, spending provider budget, deployment, or closing tickets during F1 planning or its verification setup.

## Decisions

### 1. Delete semantic writers while retaining the official read-only OpenSpec boundary

Remove the generator, sync/archive merger, their dependency injection and all callers. Replace their externally reachable behavior with a shared, minimal unavailable response where a public contract must remain temporarily recognizable; otherwise remove the endpoint/command. Preserve `OpenSpecAdapter` and structural validation only as an official-CLI/read-only integration for existing native artifacts; the ledger must demonstrate that no retained method authors, merges, archives, moves or semantically interprets OpenSpec content.

Alternative rejected: retain renamed generators or convert them into prompt templates. That still makes mini me the semantic OpenSpec author and contradicts the contract.

### 2. Quarantine the legacy execution graph before deleting durable evidence

Delete/disable in this order: (1) API/CLI/UI commands and background triggers; (2) scheduler/discovery/admission and intake generation; (3) pipeline/orchestration/gates/post-merge writers; (4) service constructors, DI/config and tests; (5) domain interfaces/repos/models; (6) database structures. Each removal step repeats reachability checks, so a table cannot be dropped while its model/repository/foreign key still serves a retained responsibility.

Alternative rejected: drop models/tables first. It risks orphaned endpoints, failed restart behavior and unclassified data loss.

### 3. Use explicit unavailable semantics, not success-shaped compatibility

For retained API paths return a machine-readable `operation_unavailable` result with the owning future phase and no mutation; retained CLI commands use a non-zero exit. Static UI/TUI elements exclusively wired to retired operations disappear or present the same unavailable state. The design intentionally does not specify a new F2/F3 API.

Alternative rejected: leave endpoints returning empty lists or `200`; this falsely represents operational capability.

### 4. Make migration evidence a prerequisite, with recoverable data handling

Before creating destructive DDL, implementation captures: schema revision, row counts, FK/index graph, production-like backup/restore proof, active durable references, and a per-structure REMOVE/MIGRATE/RETAIN-WITH-REASON decision. The migration exports only data needed for a retained legal/operational record to a protected, documented restoration path; data that is neither needed nor allowed to persist is removed only after that decision. Downgrade recreates schema safely; rollback of data follows the tested backup path rather than pretending a drop is lossless.

Alternative rejected: a migration that unconditionally drops every legacy table or rewrites historical revisions.

### 5. Historical Changes and contradictory specs are inspected, never executed or rewritten

The Removal Ledger and historical reconciliation inventory live in this `design.md`, updated during implementation with command references and candidate-bound results rather than copied into a new report. The inventory is generated from `openspec list/status`, filesystem metadata, durable DB records and process observation. It lists slug/status/conflicting authority/live-reference verdict without calling `apply`, `continue`, `archive`, or mutating directories. Historical specs remain immutable evidence; the contract rector and F1 delta specs govern contradictions. Each conflict is mapped to its owning F2–F6 phase and, once that phase is authorized, is reconciled by an agent using the installed native OpenSpec update workflow before any apply; any later sync/archive uses its native workflow after the authorized merge. F1 records that route but never invokes it. A real active external/durable operation is a blocker for any touching deletion, not authorization to advance it.

### 6. Retain the minimal F3 handoff substrate without retaining the legacy engine

Keep the installed official skills, CLI adapter/structural validation, verified repository and worktree identity, and candidate/evidence records that the Removal Ledger proves have a retained F3 consumer. Remove the legacy prompt orchestration, semantic gates and custom lifecycle behavior around them. The retained substrate does not itself dispatch an agent in F1; it only preserves the identity and evidence contract with which F3 can call the native workflow.

Alternative rejected: preserve `ExecutionPipelineService` or `OrchestrationService` wholesale as a future dispatcher. Their current semantic and lifecycle responsibilities are exactly the legacy behavior F1 is retiring.

## Risks / Trade-offs

- **Hidden dynamic caller or DI wiring** → search imports, registration/config, static JS/TUI clients, CLI commands and service construction; boot the retained app and exercise denial paths after each removal.
- **Live history or foreign keys block schema deletion** → inventory populated DB and constraints before Alembic; retain with a reason and future phase instead of guessing.
- **A disabled legacy endpoint breaks an operator** → return explicit unavailable behavior and document target phase; preserve read-only status/auth/repository diagnostics.
- **Accidental scheduler/provider activity during cleanup** → remove all trigger paths, test denial with spies/fakes, retain scheduler disabled in configuration and never invoke providers in acceptance tests.
- **Historical artifacts mistaken for active work** → distinguish filesystem presence, process state, DB active state and remote side effects; record blockers without mutation.
- **Deletion hides regressions** → retain valuable safety tests by rewriting them around denial/retained contracts; run focused regression and post-removal functional checks.

## Migration Plan

1. Capture baseline SHA, Alembic head, schema/FK/index inventory, protected backup and live-process/durable-reference observations.
2. Complete and review the Removal Ledger, including API/CLI/UI/config/test/dynamic callers and per-table data decision.
3. Implement in the dependency order above; migrate retained clients/tests to explicit unavailable or surviving read-only behavior.
4. Add and exercise the new Alembic revision against an empty database and representative populated restore. Verify `upgrade`, `downgrade`, and restore without editing historical revisions.
5. Run reachability checks plus unit/integration and real retained API/CLI functional flows after deletion. Confirm retired calls cannot enqueue, dispatch, mutate or spend.
6. Update the in-design Removal Ledger/inventory and retain candidate-bound command evidence: removal diff, symbols/callers absent, database before/after counts, migration revision, denial results, retained-capability results, and historical-change reconciliation observations. Do not create a separate bureaucratic report.

Rollback: stop at the failed migration before further deletion; use Alembic downgrade only where verified, otherwise restore the protected pre-migration backup. Revert the candidate code as one unit so no caller remains pointed at a removed schema. No production deployment is part of F1; CI/CD remains external.
