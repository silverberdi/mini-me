# Spec: Projection Purity and API Command/Query Separation (CQS)

## ADDED Requirements

### Requirement: Pure HTTP GET/HEAD Endpoint Purity and Non-Locking Reads

The system SHALL enforce that all HTTP GET and HEAD endpoints operate strictly as side-effect-free Queries, SHALL execute zero database inserts, updates, deletes, or event emissions, and SHALL NOT request write-intent database locks (`SELECT ... FOR UPDATE` or `get_for_update()`).

#### Scenario: HTTP GET budget usage returns metrics without acquiring write lock
GIVEN a client requesting HTTP GET `/budget/usage` or GET `/projects/{project_id}/budget`
WHEN the API processes the request
THEN it SHALL fetch budget policy and usage metrics using non-locking read queries
AND SHALL NOT call `get_for_update()` or execute `SELECT ... FOR UPDATE`
AND the database state SHALL remain unchanged.

#### Scenario: HTTP GET openrouter status evaluates status without write lock
GIVEN a client requesting HTTP GET `/providers/openrouter/status`
WHEN the API processes the request
THEN it SHALL query policy and headroom using standard read operations
AND SHALL NOT acquire write-intent row locks on `OpenRouterBudgetPolicy`.

#### Scenario: HTTP GET health endpoint checks database without mutating catalog
GIVEN a client requesting HTTP GET `/health` or HEAD `/health`
WHEN the health endpoint checks database connectivity
THEN it SHALL execute a read-only probe (`SELECT 1`)
AND SHALL NOT attempt schema migration, state repair, or record insertion.

---

### Requirement: Side-Effect-Free Query Services and Zero Transitive Mutation

All query service methods and read-model projections SHALL be transitively pure, and calling a top-level query method SHALL NOT trigger nested database writes, event emissions, or transaction commits.

#### Scenario: Reading scheduler status emits no mode change events
GIVEN `CapacityLifecycleService.get_scheduler_status()` called from a query path or GET endpoint
WHEN the scheduler mode is evaluated
THEN it SHALL return the computed `SchedulerStatus` DTO
AND SHALL NOT persist a `SCHEDULER_MODE_CHANGED` event to PostgreSQL
AND SHALL NOT invoke `uow.commit()`.

#### Scenario: Listing provider health does not insert missing records on read
GIVEN `ProviderHealthService.list_all_health()` called for tracked providers
WHEN a provider has no existing persisted `ProviderHealth` row in PostgreSQL
THEN the query service SHALL return an unpersisted health DTO representing its default state or `UNKNOWN`
AND SHALL NOT insert a new row into PostgreSQL or commit a transaction.

#### Scenario: Dashboard overview query executes zero transitive mutations
GIVEN `OperationsDashboardService.get_overview()` invoked via GET `/dashboard`
WHEN the dashboard overview response is constructed across capacity, provider health, projects, and runs
THEN the entire transitive call graph SHALL execute only read queries
AND before/after database state comparison SHALL be field-for-field identical.

---

### Requirement: Service Decomposition of Mixed Readiness and Evaluation Operations

Operations that combine evaluation logic with durable persistence SHALL be decomposed into pure query calculations and explicit persistence commands, ensuring GET endpoints and read projections never trigger automatic state persistence.

#### Scenario: Pure change readiness evaluation returns result without persistence
GIVEN a request to evaluate change readiness for a change
WHEN `ReadinessService.evaluate_change_readiness_pure()` is invoked
THEN it SHALL calculate DoR checks and return a `ReadinessEvaluation` DTO
AND SHALL NOT write or save `Change`, `Event`, or `MetricFact` records
AND SHALL NOT call `uow.commit()`.

#### Scenario: Command readiness evaluation explicitly persists DoR outcome
GIVEN an intentional command to evaluate and persist change readiness
WHEN `ReadinessService.evaluate_and_persist_change_readiness()` is invoked
THEN it SHALL compute DoR checks, save updated readiness fields to `Change`, emit a `READINESS_EVALUATED` event, persist a `MetricFact`, and commit the unit of work.

---

### Requirement: Projection Status Boundary and Non-Resurrection Invariant

Derived display and projection status values SHALL be strictly decoupled from canonical domain lifecycle status, and calculating a projection DTO SHALL NEVER alter canonical domain state or resurrect terminal work.

#### Scenario: Reconciled backlog projection returns display status without domain mutation
GIVEN `IntakeService.reconcile_backlog_projections()` projecting backlog item states
WHEN calculating derived item execution states
THEN it SHALL return derived display items
AND SHALL NOT invoke `LifecycleTransitionAuthority`
AND SHALL NOT alter `BacklogItem.status` or `Change.status` in PostgreSQL
AND SHALL NOT transition a `COMPLETED` or `CANCELLED` item out of its terminal state.

#### Scenario: Terminal change status remains authoritative during dashboard rendering
GIVEN a Change record in terminal state `DONE` or `CANCELLED`
WHEN `OperationsDashboardService.get_change_detail()` renders the change detail projection
THEN the returned DTO status SHALL accurately reflect terminal status
AND NO background reconciliation on read SHALL modify the canonical `Change` row in PostgreSQL.

---

### Requirement: Query Failure Representation without Repair Side Effects

When a query encounters an unobservable or missing external dependency (Git, GitHub, filesystem, or provider), it SHALL return an explicit `UNKNOWN`, `UNAVAILABLE`, or error state without attempting state repair, automatic retry, or canonical state modification.

#### Scenario: Unavailable Git repository returns explicit unavailable state on query
GIVEN a query observing Git repository status when the underlying directory is missing or unreadable
WHEN the query evaluates workspace isolation
THEN it SHALL report `is_runtime_isolated = False` with an explicit diagnostic reason
AND SHALL NOT attempt directory creation, git checkout, or database repair.

#### Scenario: Remote GitHub API error returns explicit unobservable status
GIVEN a query verifying GitHub Issue binding during readiness calculation
WHEN the remote GitHub API returns an error or HTTP timeout
THEN the query SHALL mark the readiness check as failed with an unobservability reason
AND SHALL NOT create synthetic GitHub issues or modify durable bindings.

---

### Requirement: Observational Adapter Purity for Filesystem, Git, GitHub, and Providers

All adapter methods invoked from query paths SHALL use non-mutating observational APIs and SHALL NOT perform filesystem writes, Git refs mutations, GitHub state changes, or expensive LLM provider inference.

#### Scenario: Filesystem inspection from query uses read-only operations
GIVEN an OpenSpec adapter inspecting change artifacts during a query
WHEN checking proposal, design, tasks, or spec files
THEN it SHALL use read-only inspection methods (`stat`, `exists`, `read_text`)
AND SHALL NOT create, modify, unlink, or archive files.

#### Scenario: Git inspection from query uses non-mutating commands
GIVEN a Git adapter helper invoked during a query
WHEN observing repository identity or HEAD commit
THEN it SHALL execute observational commands (`git rev-parse`, `git status`, `git merge-base`)
AND SHALL NOT execute mutating commands (`git fetch`, `git checkout`, `git reset`, `git worktree add`).

#### Scenario: Provider status query reads persisted state without inference probe
GIVEN a query inspecting provider health or OpenRouter status
WHEN evaluating provider status for display
THEN it SHALL read persisted health records and budget policies
AND SHALL NOT dispatch expensive LLM inference probes or consume API quota.
