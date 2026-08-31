# Proposal: Autonomous Queue + Work Selection

## Why

mini me currently possesses canonical project bindings, OpenSpec-driven Definition of Ready (DoR) evaluation, durable run and job state machines, provider resilience and capacity tracking (RUN / DRAIN / WAIT), multi-stage orchestration, candidate remediation, deterministic checks, complementary review, independent DeepSeek audit, container preview / guided UI validation, and an interactive Operator Control Plane.

However, an external operator or orchestrator must still manually select which change to run and trigger execution (`minime orchestrate start` or `minime run`). In addition, worktrees and initial candidate setups are manually created outside mini me before the pipeline runs, capping native self-hosting delivery phases at 40% (6/15 phases).

Stage 016 gives mini me the native responsibility to **discover candidate work, evaluate readiness, evaluate roadmap and dependency graphs, apply capacity and concurrency policies, deterministically prioritize and admit eligible work, atomically create runs and jobs, select implementers, and create isolated candidate worktrees to start the canonical delivery pipeline autonomously**.

This directly increases native self-hosting from 40% to >=60% (targeting 67%+), eliminating external orchestration dispatching for ordinary READY backlog work.

## What Changes

This change delivers:

- **Autonomous Work Discovery (`src/minime/services/discovery_service.py`)**:
  - Automatically queries the canonical GitHub Project (#2) for items associated with registered projects/repositories.
  - Reconciles project bindings, detects newly assigned or modified items, ignores unrelated items, and remains restart-safe and idempotent.
  - Retains GitHub Project + Issues as canonical product work intent while persisting discovery snapshots in PostgreSQL.

- **Queue Read Model & Decision Taxonomy (`src/minime/domain/models.py`, `src/minime/domain/enums.py`)**:
  - `WorkQueueItem` / `QueueCandidate`: Represents evaluated backlog items with project ID, issue number, change name, readiness state, declared priority, roadmap stage, dependency graph status, blocked reasons, and evaluation timestamps.
  - `AdmissionDecision` / `QueueDecisionRecord`: Immutable records capturing admission evaluations (`ADMITTED`, `NOT_READY`, `ROADMAP_BLOCKED`, `DEPENDENCY_BLOCKED`, `PROVIDER_DRAIN`, `PROVIDER_WAIT`, `PROVIDER_UNAVAILABLE`, `BUDGET_BLOCKED`, `GLOBAL_CONCURRENCY_LIMIT`, `PROJECT_CONCURRENCY_LIMIT`, `CHANGE_ALREADY_ACTIVE`, `ALREADY_ADMITTED`, `INVALID_BINDING`, `SPEC_INVALID`).
  - Explainable selection rationale persisted in PostgreSQL for complete auditability.

- **Deterministic Prioritization & Roadmap Governance (`src/minime/services/scheduler_service.py`)**:
  - Priority ordering based on: (1) Roadmap stage ordering (stage N must complete before stage N+1); (2) Explicit priority level (`CRITICAL` > `HIGH` > `NORMAL` > `LOW`); (3) Dependency readiness; (4) Bounded starvation prevention / aging; (5) Provider compatibility; (6) Deterministic tie-breaking by discovery timestamp and issue number.
  - Purely algorithmic and deterministic; no opaque LLM authority in scheduling or ranking.

- **Admission Control & Concurrency Governance (`src/minime/services/scheduler_service.py`)**:
  - Enforces `max_global_jobs`, `one_active_implementation_per_project`, and same-change exclusivity.
  - Provider-aware admission respecting `RUN`, `DRAIN`, and `WAIT` modes. In `DRAIN` or `WAIT`, stops admitting new work.
  - Atomic transactional admission using database locks/constraints to prevent race conditions or duplicate runs/jobs across concurrent scheduler ticks.

- **Implementer Selection & Autonomous Worktree Startup (`src/minime/services/scheduler_service.py`, `src/minime/services/worktree_manager.py`)**:
  - Automatically selects the primary implementer based on project configuration, provider health, role eligibility, and historical review independence.
  - Natively initializes the candidate branch/ref, isolated worktree, baseline SHA verification, and orchestration run/job records, advancing directly into the implementation pipeline without manual developer worktree setup.

- **Daemon & Scheduler CLI (`src/minime/cli/main.py`, `src/minime/services/scheduler_service.py`)**:
  - `minime scheduler run` (background polling loop), `minime scheduler tick` (deterministic one-shot tick), `minime scheduler status`, `minime queue list`, and `minime queue explain <item>`.

- **TUI Queue & Scheduler Observability (`src/minime/tui/`)**:
  - New Queue / Work Selection view displaying scheduler mode, queue depth, READY count, blocked count, ranked candidates with explainable reasons, blocker breakdowns, active admissions, and manual tick trigger.
  - Responsive across narrow (80-100 cols), normal (120-160 cols), and wide (>170 cols) terminals.

- **Database Persistence & Alembic Migration**:
  - PostgreSQL schema additions for `work_queue_snapshots` and `scheduler_decision_records` via a linear migration.

## Capabilities

### New Capabilities
- `autonomous-work-discovery`: Periodic and on-demand discovery of GitHub Project items for registered repositories, binding reconciliation, and idempotency.
- `queue-prioritization-and-admission`: Deterministic ranking, roadmap stage enforcement, dependency resolution, starvation aging, concurrency limits, RUN/DRAIN/WAIT gating, and atomic admission.
- `autonomous-worktree-startup`: Native creation of candidate branches, isolated worktrees, base SHA binding, and pipeline startup upon admission.
- `scheduler-tui-observability`: Textual TUI widgets and views for queue monitoring, next-work inspection, blocker diagnostics, and scheduler controls.

## Non-Goals (Scope Boundaries)

- PWA Control Center web interface (deferred to 017).
- Full end-to-end zero-human SDLC auto-merge completion (deferred to 018).
- Autonomous AI-generated roadmap generation or arbitrary backlog mutation.
- Multi-project optimization beyond registered single-installation projects.
- Cost-learning or dynamic LLM model-selection engine.

## Impact

- `src/minime/domain/`: Added `WorkQueueItem`, `AdmissionDecision`, `QueueDecisionRecord`, `QueuePriority`, `AdmissionRefusalCode`.
- `src/minime/db/`: Added SQLAlchemy models and repositories for queue snapshots and scheduler decisions.
- `alembic/versions/`: Added linear Alembic migration `014_autonomous_queue_work_selection.py`.
- `src/minime/services/`: Added `WorkDiscoveryService`, `SchedulerService`; enhanced `OrchestrationService` and `WorktreeManager` for native candidate startup.
- `src/minime/cli/main.py`: Added `queue` and `scheduler` command trees.
- `src/minime/tui/`: Added Queue View and Scheduler status widgets.
- `docs/CANONICAL_DECISIONS.md`, `docs/ROADMAP.md`: Updated with 016 delivered scope.
