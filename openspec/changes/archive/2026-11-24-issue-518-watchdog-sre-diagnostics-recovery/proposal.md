## Why

Runs can remain active without observable progress or retain stale process/worktree ownership, while operators lack one durable, cross-project explanation and safe recovery path. The existing process watchdog and canonical recovery authority provide useful pieces, but not the global operator controls, persisted run-level diagnosis, or improvement feed requested by Issue #518.

## What Changes

- Add a global Watchdog/SRE configuration for provider/model, inactivity threshold (15 minutes by default), and diagnostic-only versus explicitly enabled mechanical remediation; persist it in PostgreSQL without storing credentials.
- Detect stalled runs through the existing scheduler/reconciliation path, without adding a pipeline stage, competing scheduler, or model call for runs that are progressing.
- Persist evidence-bound diagnoses and remediation outcomes; allow only bounded, proven-safe mechanical recovery through the existing claim/fencing and worktree-ownership authorities. Escalate unresolved or ambiguous cases through the existing human-gate flow.
- Add a cross-project “Mejora Continua” view for persisted suggestions that the operator can copy as an Issue draft or discard; it never creates GitHub work autonomously.
- Enrich “Diagnóstico & Supervisión” with current run activity, Watchdog actions, and navigation to the improvement feed; add the requested autonomy trend using observed completed-run outcomes and an explicit no-data state.
- Replace the Issue's unrestricted `git checkout -- .` remediation with exact managed-worktree recovery that verifies run/Change/candidate ownership, process absence, and current fenced claim before any cleanup. Preserve ambiguous worktrees and escalate.

## Capabilities

### New Capabilities
- `run-stall-watchdog`: Global configuration, evidence-based stall diagnosis, bounded safe playbooks, durable outcomes, and operator escalation for active runs.
- `continuous-improvement-feed`: Cross-project presentation and operator handling of persisted improvement suggestions without autonomous Issue creation.

### Modified Capabilities
- `provider-model-administration-ui`: Add persisted global Watchdog role and operating controls to the existing provider/model administration view.
- `execution-operations-dashboard`: Extend the existing diagnostic/supervision and active-run projections with Watchdog context and improvement-feed navigation.
- `temporal-multiseries-telemetry`: Define autonomy as an observed aggregate share of completed runs without operator intervention, including successful Watchdog recovery; retain explicit no-data semantics and do not substitute fabricated per-run 0/100 values.
- `scheduler-and-recovery-convergence`: Route Watchdog-triggered mutations through the existing canonical recovery, claims, fencing, idempotency, and gate authority.

## Impact

Likely affected areas include the existing `scheduler_run_cmd` reconciliation path and `NativeOrchestrationCoordinator`, `ProgressWatchdog`, PostgreSQL configuration and event persistence, provider/model administration APIs, the current “Diagnóstico & Supervisión” card, dashboard temporal telemetry, and Angular navigation/views. The change may require a conservative PostgreSQL migration for global settings and durable diagnoses/suggestions. It adds no new provider credentials, pipeline stage, scheduler, parallel recovery authority, autonomous GitHub issue creation, or deployment behavior; project CI/CD remains responsible for deployment.
