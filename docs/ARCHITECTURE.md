# Architecture

```text
                       GitHub
        repos + Issues + PRs + global Project
                         |
                         v
                  mini me daemon/API
                   Linux runtime host
                         |
       +-----------------+------------------+
       |                 |                  |
  PostgreSQL        Git/worktrees       Scheduler/Policy
       |                                    |
       |                         +----------+----------+
       |                         |          |          |
       |                       Codex    Antigravity DeepSeek Direct
       |                         |          |          |
       |                         +-----+----+          |
       |                               |               |
       |                        OpenRouter drain        |
       |                        (model A != B)          |
       |                                               |
       +---------------- durable evidence -------------+
```

## Core boundaries
### Daemon/core
Owns scheduling, policy, state transitions, recovery, provider orchestration, Git workspace lifecycle and integration workflows.

### PostgreSQL
Stores current state plus immutable/auditable events and attempt evidence. External side effects that require reliable eventual synchronization should use an outbox/reconciliation pattern.

### OpenSpec adapter
Reads proposal/specs/design/tasks and validates readiness. Runtime state such as quota, process IDs, retry counters, preview status and human decisions never belongs in OpenSpec.

### Provider adapter
Vendor syntax and output parsing remain behind adapters. Core receives normalized provider/capacity results.

### Git workspace manager
One isolated worktree/branch per active change. Base SHA, candidate head SHA and repository identity are persisted. One active implementation per project in MVP.

### Check runner
Runs configured deterministic commands with timeout and captures command, exit code, duration and bounded/redacted output references.

### GitHub integration
Synchronizes Issues/Project/PR state but is not authoritative for runtime execution location. Failures should be recoverable by durable reconciliation.

### Deployment adapter
Invokes project-owned container/Compose build/up/health/down contracts. mini me orchestrates; each repo declares how it runs.

## Data model direction
Core entities include `projects`, `project_bindings`, `changes`, `jobs`, `job_attempts`, `provider_health`, `capacity_windows`, `check_runs`, `reviews`, `findings`, `audits`, `human_decisions`, `validation_sessions`, `validation_scenarios`, `deployments`, `artifacts`, `events`, `outbox`, `budget_usage`, and `metrics_facts`.

## API principle
TUI and future PWA consume a stable API; they do not invoke agents, Git or deployments directly.
