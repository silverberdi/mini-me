# Proposal: Stage E — Projection Purity and API Command/Query Separation (CQS)

## Executive Summary

Stage E enforces strict Command/Query Separation (CQS) and projection purity across all API, service, and repository surfaces in mini me. Building on Stage A's single-writer lifecycle authority, Stage E extends state protection from "no lifecycle mutation on read" to **"zero durable or external side effect from any query or projection path."**

Currently, several HTTP GET endpoints, middleware components, and query services perform side-effecting operations, including:
1. `auth_middleware()` in FastAPI executing `SessionManager.validate_session()` and `AuthorizedOperatorService.evaluate_operator()`, which update `AuthSession.last_seen_at`, `ip_address`, `user_agent`, link `google_sub`, and call `uow.commit()` on every authenticated GET request;
2. HTTP GET `/budget/usage` and GET `/providers/openrouter/status` acquiring `SELECT ... FOR UPDATE` write-intent row locks;
3. HTTP GET `/scheduler/status` emitting `SCHEDULER_MODE_CHANGED` events and calling `uow.commit()`;
4. HTTP GET `/providers/health` lazily inserting missing `ProviderHealth` rows into PostgreSQL and calling `uow.commit()`;
5. HTTP GET `/dashboard` overview transitively inheriting these mutating side effects;
6. `ReadinessService.evaluate_change_readiness()` persisting `Change`, `Event`, and `MetricFact` records during DoR evaluation.

Stage E remediates these defects, establishes an explicit CQS architecture, and ensures every endpoint classified as QUERY is 100% pure, repeatable, and non-blocking, while explicitly preserving delivered Stage D command-path saga row locking.

---

## Why

In an autonomous orchestration engine, allowing queries and authentication middleware to mutate durable state, emit events, or acquire write locks creates significant risks:
- **Middleware Side-Effect Leakage:** Updating session timestamps and operator identities on every HTTP GET request mutates PostgreSQL before the route handler is even executed, corrupting audit trails and creating unnecessary database writes.
- **Deadlocks and Contention:** Executing `SELECT ... FOR UPDATE` on high-frequency HTTP GET endpoints introduces unnecessary row-locking contention and potential deadlocks with background worker transactions.
- **Unintended State Evolution:** Observing system status or health should never alter historical telemetry, record fake activity, or trigger state transitions.
- **Non-Repeatable Reads:** If a read operation modifies database records, subsequent reads observe mutated state rather than original underlying truth.

---

## Core CQS Law

> **Every endpoint classified as QUERY is side-effect-free. Ordinary resource GET/HEAD endpoints MUST be queries. Protocol-defined GET mutation endpoints (such as OAuth login and callback flows) must be explicitly enumerated and classified as commands, never hidden inside the query set.**

---

## Value Statement

By enforcing strict CQS:
- All HTTP GET/HEAD requests (except explicitly classified protocol commands) and projection services are provably side-effect-free.
- Authentication middleware evaluates session and operator validity without writing to PostgreSQL or committing transactions.
- System reads are 100% safe, non-blocking, and repeatable.
- Delivered Stage D saga-resume command locking (`get_for_update()`) is explicitly preserved.
- Operational metrics and events remain pristine, recording only intentional system mutations.

---

## Scope

1. **Finite Surface Matrix (Q01–Q25):** Auditing and enforcing CQS compliance across all 25 finite surfaces, including request authentication middleware (Q25).
2. **Authentication Middleware Purity (Q25):** Decomposing `SessionManager.validate_session()` and `AuthorizedOperatorService.evaluate_operator()` so query authentication checks perform zero DB updates or commits.
3. **Locking Remediation:** Replacing `get_for_update()` / `SELECT ... FOR UPDATE` in GET `/budget/usage` and GET `/providers/openrouter/status` with non-locking read queries.
4. **Stage D Command Locking Preservation:** Explicitly preserving `SagaEngine.resume_saga()` command row locking (`get_for_update()`) delivered in Stage D.
5. **Event & Transaction Purity:** Eliminating event emission and `uow.commit()` calls from GET `/scheduler/status`, GET `/providers/health`, GET `/dashboard`, and query services.
6. **Lazy Insertion Elimination:** Ensuring GET `/providers/health` observes existing health or returns synthesized unpersisted DTOs without inserting DB rows.
7. **Mixed Service Split:** Splitting `ReadinessService` into a pure evaluation calculation (`evaluate_change_readiness_pure`) and an explicit persistence command (`evaluate_and_persist_change_readiness`).
8. **Projection Status Boundary:** Enforcing that display/projection DTO values never feed back into canonical domain state or act as lifecycle authority.
9. **Dynamic Route Census & Protocol GET Classification:** Inspecting `app.routes` dynamically at test time to verify all resource GET/HEAD routes are pure, with explicit command classification for OAuth protocol GET endpoints.
10. **Transitive Purity Verification:** Instrumenting unit of work, sessions, fake adapters, and AST checks to guarantee end-to-end transitive purity across the entire GET call graph.

---

## Non-Goals (Out of Scope)

- **No Stage F Concurrency Redesign:** Multi-worker concurrent admission, atomic row locking for saga resume, isolation levels, and retry policies belong strictly to Stage F.
- **No UI Redesign:** API responses maintain backwards-compatible DTO structures; no user interface redesign is performed.
- **No Weakening of Security Semantics:** Expired/revoked sessions and unauthorized/disabled operators remain strictly rejected.
- **No Production Code Implementation in Contract Phase:** This change delivers the authorized OpenSpec contract only.
