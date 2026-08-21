# Tasks: 005-provider-resilience-and-exhaustion

## 1. Database Schema & Persistence Models

- [ ] 1.1 Add domain enums (`SchedulerMode`, `ProviderHealthStatus`, `ProviderResultClass`, `CapacitySignalSource`) and models in `src/minime/domain/`
- [ ] 1.2 Add SQLAlchemy ORM models for `provider_health` and `capacity_windows` in `src/minime/db/models.py`
- [ ] 1.3 Create versioned Alembic migration `005_provider_resilience` (revising `004_deepseek_audit`) with upgrade and downgrade logic
- [ ] 1.4 Implement database repository methods for provider health, capacity window recordings, enforcing primary-provider set (`codex`, `antigravity`), and query functions in `src/minime/db/repository.py`
- [ ] 1.5 Unit test database models, repository queries, and migration upgrade/downgrade

## 2. Primary Provider Health & Capacity Tracking

- [ ] 2.1 Implement structured provider outcome parser conforming to `schemas/provider-result.schema.json` distinguishing transport health from domain verdicts (`CHANGES_REQUIRED` as `success`) in `src/minime/services/provider_outcome_parser.py`
- [ ] 2.2 Implement `ProviderHealthService` for primary providers (`Codex`, `Antigravity`), tracking failure thresholds, retry-after durations, and capacity reset timestamps
- [ ] 2.3 Implement verified capacity reset probing logic requiring positive probe evidence before transitioning from exhausted to `available`
- [ ] 2.4 Unit test outcome classification (quota limits, rate limits, transient network errors, domain verdicts) and health probing (elapsed reset + still exhausted, elapsed reset + probe failure, elapsed reset + verified available)

## 3. Primary-Driven Scheduler Capacity Lifecycle (RUN, DRAIN, WAIT)

- [ ] 3.1 Implement `CapacityLifecycleService` managing `RUN`, `DRAIN`, and `WAIT` state transitions driven strictly by primary providers (Codex and Antigravity)
- [ ] 3.2 Update `ReadinessService` and `ExecutionPipeline` to enforce complete-pair admission gating (new `READY` work admitted only when complete primary pair is available in `RUN`, blocked in `DRAIN` and `WAIT`)
- [ ] 3.3 Ensure DeepSeek Direct audit failures remain isolated to the 004 audit lifecycle and do not drive scheduler `RUN`/`DRAIN`/`WAIT` transitions
- [ ] 3.4 Define abstract fallback eligibility interface seam in `src/minime/domain/interfaces.py` (defaulting to no fallback in 005)
- [ ] 3.5 Unit test scheduler mode transitions, primary-pair admission gating, and non-impact of audit failures on scheduler mode

## 4. In-Flight Job Preservation & WAITING_CAPACITY

- [ ] 4.1 Update `ExecutionPipeline` to transition jobs to `WAITING_CAPACITY` when a required primary provider is unavailable
- [ ] 4.2 Implement complementary pairing invariant guards preventing self-review or reviewer replacement during capacity shortages
- [ ] 4.3 Unit test `WAITING_CAPACITY` transitions, checkpoint preservation, and pairing invariant enforcement

## 5. Daemon Crash Recovery & Safe Git Lock Reconciliation

- [ ] 5.1 Implement `RestartRecoveryService` to scan for non-terminal jobs on startup and reconcile interrupted attempts with `DAEMON_RESTARTED` events without inferring unevidenced completion
- [ ] 5.2 Implement checkpoint preservation ensuring completed checks, reviews, and audits are not re-executed upon recovery
- [ ] 5.3 Implement safe worktree Git lock recovery: remove `.git/index.lock` only if within a managed worktree with no active owning process, failing closed to `RECOVERY_BLOCKED` otherwise
- [ ] 5.4 Integrate restart recovery into application lifespan startup in `src/minime/api/app.py`
- [ ] 5.5 Unit test restart recovery, checkpoint preservation, and Git lock safety (stale lock in managed worktree -> recovered; active/uncertain lock -> `RECOVERY_BLOCKED`; lock outside managed worktree -> never removed)

## 6. Observability API & CLI

- [ ] 6.1 Add FastAPI REST routes for `GET /scheduler/status` and `GET /providers/health` in `src/minime/api/routes.py`
- [ ] 6.2 Update `GET /jobs/{job_id}` to include `WAITING_CAPACITY` blockage details, expected reset timestamps, and `RECOVERY_BLOCKED` lock diagnostics
- [ ] 6.3 Add CLI commands `minime scheduler status` and `minime providers health` in `src/minime/cli/`
- [ ] 6.4 Integration test API endpoints and CLI commands with secret redaction

## 7. End-to-End Verification & Validation

- [ ] 7.1 Execute full test suite (`pytest`) covering primary provider resilience, rate-limits, reset probes, crash recovery, lock safety, and capacity wait states
- [ ] 7.2 Run code linting (`ruff check .`), verify OpenSpec consistency with `openspec validate 005-provider-resilience-and-exhaustion --strict`
