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

## Fundamental execution ownership
mini me is an **orchestrator/control plane**. It must never reimplement the agent-side OpenSpec workflows or author specs/implementation through deterministic mini me template generators. Real Codex/Antigravity agents load installed OpenSpec skills/commands, reason, edit code and verify. mini me owns bounded context/tool selection, durable stage/claim policy, workspaces, quota/permissions/guards, checks/evidence, GitHub/human gates and rollout. DeepSeek/OpenRouter are explicit authorized fallback only after dual-primary exhaustion; provider availability never substitutes for tool capability.

A valid change is an entire vertical outcome: all relevant backend/DB/UI/security/skill/hook/harness/specs, real stage E2E, complete-value E2E and postdeployment observation. See [CHANGE_DELIVERY_CONTRACT](CHANGE_DELIVERY_CONTRACT.md).

## Core boundaries
### Daemon/core
Owns scheduling, policy, state transitions, recovery, per-stage agent/provider orchestration, capability discovery, Git workspace lifecycle, bounded tool invocations, preflight, evidence and integration workflows **without writing project code or semantically generating OpenSpec artifacts**.

### PostgreSQL
Stores current state plus immutable/auditable events and attempt evidence. External side effects that require reliable eventual synchronization should use an outbox/reconciliation pattern.

### OpenSpec adapter
Reads proposal/specs/design/tasks and validates readiness, status and structure via official OpenSpec CLI. The **agent** invokes installed agent-side OpenSpec workflows propose/update/continue/apply/verify/sync/archive. Runtime state such as quota, process IDs, retry counters, preview status and human decisions never belongs in OpenSpec. Do not generate specs with custom deterministic Python or merge specs with custom code.

### Provider adapter
Vendor syntax and output parsing remain behind adapters. Core selects roles **per stage** and normalizes provider/capacity results. The harness proves the agent actually loaded a compatible OpenSpec skill/command; a plain prompt or raw LLM API response does not count as successful OpenSpec execution.

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
