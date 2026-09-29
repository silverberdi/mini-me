# Proposal: Stage E — Projection Purity and API Command/Query Separation (CQS)

## Executive Summary

Stage E enforces strict Command/Query Separation (CQS) and projection purity across all API, service, and repository surfaces in mini me. Building on Stage A's single-writer lifecycle authority, Stage E extends state protection from "no lifecycle mutation on read" to **"zero durable or external side effect from any query or projection path."**

Currently, several HTTP GET endpoints and query services perform side-effecting operations, including:
1. HTTP GET `/budget/usage` and GET `/providers/openrouter/status` acquiring `SELECT ... FOR UPDATE` write-intent row locks;
2. HTTP GET `/scheduler/status` emitting `SCHEDULER_MODE_CHANGED` events and calling `uow.commit()`;
3. HTTP GET `/providers/health` lazily inserting missing `ProviderHealth` rows into PostgreSQL and calling `uow.commit()`;
4. HTTP GET `/dashboard` overview transitively inheriting these mutating side effects;
5. `ReadinessService.evaluate_change_readiness()` persisting `Change`, `Event`, and `MetricFact` records during DoR evaluation.

Stage E remediates these defects, establishes an explicit CQS architecture, and ensures every GET/HEAD endpoint and read model is 100% pure, repeatable, and non-blocking.

---

## Why

In an autonomous orchestration engine, allowing queries to mutate durable state, emit events, or acquire write locks creates significant risks:
- **Deadlocks and Contention:** Executing `SELECT ... FOR UPDATE` on high-frequency HTTP GET endpoints introduces unnecessary row-locking contention and potential deadlocks with background worker transactions.
- **Unintended State Evolution:** Observing system status or health should never alter historical telemetry, record fake activity, or trigger state transitions.
- **Side-Effect Leakage:** Transitive calls from overview dashboards down into mutating service helpers break auditability and cause side effects merely because an operator opened a UI screen.
- **Non-Repeatable Reads:** If a read operation modifies database records, subsequent reads observe mutated state rather than original underlying truth.

---

## Value Statement

By enforcing strict CQS:
- All HTTP GET/HEAD requests and projection services are provably side-effect-free.
- System reads are 100% safe, non-blocking, and repeatable.
- Query failures return explicit `UNKNOWN` / `UNAVAILABLE` observations without repairing canonical state.
- Operational metrics and events remain pristine, recording only intentional system mutations.

---

## Scope

1. **Finite Surface Matrix (Q01–Q24):** Auditing and enforcing CQS compliance across all 24 finite surfaces.
2. **Locking Remediation:** Replacing `get_for_update()` / `SELECT ... FOR UPDATE` in GET `/budget/usage` and GET `/providers/openrouter/status` with non-locking read queries.
3. **Event & Transaction Purity:** Eliminating event emission and `uow.commit()` calls from GET `/scheduler/status`, GET `/providers/health`, GET `/dashboard`, and query services.
4. **Lazy Insertion Elimination:** Ensuring GET `/providers/health` observes existing health or returns synthesized unpersisted DTOs without inserting DB rows.
5. **Mixed Service Split:** Splitting `ReadinessService` into a pure evaluation calculation (`evaluate_change_readiness_pure`) and an explicit persistence command (`evaluate_and_persist_change_readiness`).
6. **Projection Status Boundary:** Enforcing that display/projection DTO values never feed back into canonical domain state or act as lifecycle authority.
7. **Transitive Purity Verification:** Instrumenting unit of work, sessions, fake adapters, and AST checks to guarantee end-to-end transitive purity across the entire GET call graph.

---

## Non-Goals (Out of Scope)

- **No Stage F Concurrency Redesign:** Multi-worker concurrent admission, isolation levels, advisory locks, and transaction retry policies belong strictly to Stage F.
- **No UI Redesign:** API responses maintain backwards-compatible DTO structures; no user interface redesign is performed.
- **No Production Code Implementation in Contract Phase:** This change delivers the authorized OpenSpec contract only. Implementation is executed in subsequent authorized steps.
