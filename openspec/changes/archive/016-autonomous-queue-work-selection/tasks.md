# Tasks: Autonomous Queue + Work Selection

## 1. Domain Models, Enums & Interfaces
- [x] 1.1 Add `QueuePriority`, `AdmissionDecision`, `AdmissionRefusalCode`, and `SchedulerMode` enums to `src/minime/domain/enums.py`.
- [x] 1.2 Add `WorkQueueItem`, `SchedulerDecisionRecord`, `QueueExplainReport`, and `SchedulerStatusView` models to `src/minime/domain/models.py`.
- [x] 1.3 Add repository interfaces `WorkQueueRepositoryInterface` and `SchedulerDecisionRepositoryInterface` to `src/minime/domain/interfaces.py`.
- [x] 1.4 Write unit tests for domain models, validation, and immutability in `tests/test_queue_domain.py`.

## 2. Persistence & Alembic Migration
- [x] 2.1 Create SQLAlchemy models `WorkQueueSnapshotModel` and `SchedulerDecisionRecordModel` in `src/minime/db/models.py`.
- [x] 2.2 Implement SQLAlchemy and InMemory repositories for queue snapshots and scheduler decisions in `src/minime/db/repositories.py` and `tests/conftest.py`.
- [x] 2.3 Create Alembic migration `014_autonomous_queue_work_selection.py` preserving single linear head.
- [x] 2.4 Verify offline static SQL generation and model metadata integrity in `tests/test_queue_persistence.py`.

## 3. Work Discovery Service
- [x] 3.1 Implement `WorkDiscoveryService` in `src/minime/services/discovery_service.py` to discover project backlog items via `GitHubAdapter`.
- [x] 3.2 Implement durable `ProjectBinding` reconciliation and OpenSpec change mapping.
- [x] 3.3 Implement duplicate discovery filtering, new item detection, and restart safety.
- [x] 3.4 Write comprehensive tests for discovery, filtering, and reconciliation in `tests/test_work_discovery.py`.

## 4. Prioritization & Roadmap Governance
- [x] 4.1 Implement deterministic scoring engine in `SchedulerService` (`src/minime/services/scheduler_service.py`) combining base priority, aging bonus, and roadmap precedence.
- [x] 4.2 Implement canonical roadmap sequence enforcement (`ROADMAP_PREDECESSOR_INCOMPLETE`).
- [x] 4.3 Implement dependency resolution and cycle detection.
- [x] 4.4 Implement deterministic tie-breaking and explainability reporter (`explain_item_priority`).
- [x] 4.5 Write unit tests for prioritization, roadmap gating, starvation aging, and tie-breaking in `tests/test_scheduler_prioritization.py`.

## 5. Admission Control & Concurrency Governance
- [x] 5.1 Implement admission evaluator enforcing DoR readiness, scheduler mode (`RUN`/`DRAIN`/`WAIT`), provider capacity, global concurrency (`max_global_jobs`), and per-project exclusivity.
- [x] 5.2 Implement atomic transactional admission with database concurrency guards to prevent duplicate admissions across concurrent ticks.
- [x] 5.3 Implement immutable `SchedulerDecisionRecord` logging for all evaluated items.
- [x] 5.4 Write unit tests for admission gating, capacity checks, and concurrency limits in `tests/test_admission_control.py`.

## 6. Implementer Selection & Native Worktree Startup
- [x] 6.1 Implement deterministic implementer selection respecting provider health, configured roles, and model independence.
- [x] 6.2 Implement native candidate startup in `SchedulerService`: automatically creates `OrchestrationRun`, allocates isolated worktree via `WorktreeManager`, instantiates `Job`, and triggers execution pipeline.
- [x] 6.3 Ensure complete idempotency so repeated ticks for admitted items never create duplicate worktrees or jobs.
- [x] 6.4 Write integration tests verifying autonomous candidate/worktree startup in `tests/test_autonomous_worktree_startup.py`.

## 7. Scheduler Loop, CLI & REST API
- [x] 7.1 Implement scheduler daemon loop with configurable intervals and one-shot `tick` mode in `SchedulerService`.
- [x] 7.2 Implement failure isolation: single malformed item does not abort scheduler execution.
- [x] 7.3 Add CLI commands: `minime scheduler tick`, `minime scheduler run`, `minime scheduler status`, `minime queue list`, `minime queue explain <item>` in `src/minime/cli/main.py`.
- [x] 7.4 Add REST API endpoints in `src/minime/api/app.py`: `GET /api/v1/queue`, `GET /api/v1/queue/{change_name}/explain`, `GET /api/v1/scheduler/status`, `POST /api/v1/scheduler/tick`.
- [x] 7.5 Write CLI and API tests in `tests/test_scheduler_cli_and_api.py`.

## 8. TUI Queue & Scheduler Observability
- [x] 8.1 Implement TUI Queue View (`src/minime/tui/views/queue.py`) displaying queue depth, ready/blocked counts, ranked candidate table, next-to-admit spotlight, and decision history.
- [x] 8.2 Add scheduler status indicator to TUI header / overview.
- [x] 8.3 Implement interactive actions: manual tick (`t`), refresh (`r`), view explainability details (`enter`).
- [x] 8.4 Support responsive layouts across narrow (80-100 cols), normal (120-160 cols), and wide (>170 cols) viewports.
- [x] 8.5 Write visual acceptance tests in `tests/tui/test_queue_tui.py`.

## 9. Real Scheduler Acceptance & Self-Hosting Pilot
- [x] 9.1 Run real scheduler acceptance scenario with multiple eligible and blocked items verifying ranking, capacity gating, and idempotent repeated ticks.
- [x] 9.2 Execute real self-hosting pilot: create a safe pilot work item, allow mini me scheduler to autonomously discover, evaluate READY, rank, admit, create worktree, and start the canonical pipeline natively.
- [x] 9.3 Record verifiable pilot execution evidence and compute native self-hosting phase metrics.

## 10. Canonical Checks, Review, Audit, PR & Archive
- [x] 10.1 Run full check suite: pytest, Ruff lint & format, git diff check, OpenSpec strict validation, Alembic head check.
- [x] 10.2 Freeze candidate and perform complementary review.
- [x] 10.3 Perform DeepSeek independent audit.
- [x] 10.4 Prepare PR on GitHub and authorize merge upon passing all gates.
- [x] 10.5 Post-merge: sync OpenSpec, update roadmap docs, archive 016, and cleanup.
