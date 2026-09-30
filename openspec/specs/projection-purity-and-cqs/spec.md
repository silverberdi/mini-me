# projection-purity-and-cqs Specification

## Purpose

Enforce command/query separation so read and projection surfaces remain side-effect-free, fail closed on unavailable evidence, and preserve canonical lifecycle authority while governed command paths retain intentional mutation semantics.

## Requirements

### Requirement: Pure HTTP GET/HEAD Endpoint Purity and Non-Locking Reads

The system SHALL enforce that all HTTP GET and HEAD endpoints classified as Queries operate strictly as side-effect-free operations, SHALL execute zero database inserts, updates, deletes, or event emissions, and SHALL NOT request write-intent database locks (`SELECT ... FOR UPDATE` or `get_for_update()`).

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

### Requirement: Side-Effect-Free Authentication Middleware and Security Preservation

Request authentication and authorization middleware executing during query processing SHALL evaluate identity, session validity, allowlist status, and permissions using pure read queries, SHALL NOT update session activity timestamps or operator identities in PostgreSQL, and SHALL preserve exact security enforcement semantics.

#### Scenario: Authenticated HTTP GET produces zero session or operator mutations
GIVEN a valid authenticated session token provided on an HTTP GET request
WHEN `auth_middleware` and `get_current_operator` evaluate the request identity
THEN the system SHALL authenticate the operator successfully
AND `AuthSession.last_seen_at`, `ip_address`, and `user_agent` SHALL remain 100% unchanged in PostgreSQL
AND `AuthorizedOperator.google_sub` SHALL remain 100% unchanged
AND no database commit or update SHALL occur as a consequence of authentication.

#### Scenario: Expired or revoked session is rejected without state mutation
GIVEN an expired or revoked session token provided on an HTTP GET request
WHEN request authentication middleware executes
THEN the system SHALL reject the request with HTTP 401 Unauthorized
AND SHALL NOT mutate PostgreSQL state or update session activity timestamps.

#### Scenario: Disabled or non-allowlisted operator is rejected without state mutation
GIVEN a session token belonging to a disabled or non-allowlisted operator identity
WHEN request authorization middleware evaluates the operator
THEN the system SHALL reject the request with HTTP 403 Forbidden
AND SHALL NOT persist changes to `AuthorizedOperator` records.

---

### Requirement: Side-Effect-Free Query Services and Zero Transitive Mutation

All query service methods and read-model projections SHALL be transitively pure, and calling a top-level query method SHALL NOT trigger nested database writes, event emissions, or transaction commits.

#### Scenario: Reading scheduler status emits no mode change events
GIVEN `CapacityLifecycleService.get_scheduler_status_pure()` called from a query path or GET endpoint
WHEN the scheduler mode is evaluated
THEN it SHALL return the computed `SchedulerStatus` DTO
AND SHALL NOT persist a `SCHEDULER_MODE_CHANGED` event to PostgreSQL
AND SHALL NOT invoke `uow.commit()`.

#### Scenario: Listing provider health does not insert missing records on read
GIVEN `ProviderHealthService.list_existing_health()` called for tracked providers
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

### Requirement: Stage D Command Row-Locking Preservation

Delivered Stage D saga-resume row locking (`get_for_update()`) on command execution paths SHALL be explicitly preserved, and prohibiting write-intent locks on query paths SHALL NOT weaken or remove row locking from command execution.

#### Scenario: Saga resume command retains Stage D row-locking semantics
GIVEN an intentional operator or scheduler command to resume a saga via `SagaEngine.resume_saga()`
WHEN the saga engine acquires the durable saga record for update
THEN it SHALL call `DurableSagaRepository.get_for_update()` and execute `SELECT ... FOR UPDATE`
AND this row locking SHALL be explicitly permitted as a COMMAND operation
AND SHALL NOT be treated as a CQS violation.

---

### Requirement: Protocol GET Endpoint Classification and Command Exclusion

Endpoints using the HTTP GET method that perform protocol-mandated state mutations (such as OAuth login, code exchange callback, and logout) SHALL be explicitly classified as Commands in the system design and excluded from generic query purity test suites through an authoritative Exclusion Register.

#### Scenario: OAuth callback endpoint executes protocol command mutations
GIVEN an incoming HTTP GET request to `/api/v1/auth/google/callback`
WHEN the endpoint processes the OAuth authorization code exchange
THEN it SHALL exchange the code, create an `AuthSession`, link `google_sub`, and commit the transaction
AND this endpoint SHALL be classified as a COMMAND / PROTOCOL_MUTATION
AND SHALL be excluded from the generic HTTP query purity test suite.

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