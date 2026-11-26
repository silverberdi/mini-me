## Why

Runs can stop on technical or procedural blockers that an authorized, bounded recovery path could resolve, while the current autonomy telemetry does not preserve a distinct, append-only account of those interventions. This Change makes such recoveries observable and reusable without transferring the operator's authority over product, security, exceptional cost, destructive actions, or implementation merge.

## What Changes

- Define the SRE Unblocker as a configured, narrowly scoped role invoked by the existing Watchdog/orchestration flow for eligible technical blockers.
- Seed its skill with three bounded playbooks: verified non-blocking PF-03 fallback/precondition warnings, configured OAuth refresh after a classified MCP 401, and removal of a proven orphan lock in the exact managed worktree.
- Permit only evidence-backed, idempotent actions through existing native CLI, recovery, and fencing authorities; keep ambiguous or reserved decisions at the current human gate.
- Preserve the complete original OpenSpec question and options at business, cost, or scope gates, adding the Unblocker's diagnosis as separate context.
- Persist each intervention as an immutable PostgreSQL fact and expose its outcome in autonomy telemetry, distinguishing clean runs, autonomously recovered runs, and runs needing an operator.
- Feed supported recurrence-prevention proposals into the existing Mejora Continua flow without creating GitHub Issues autonomously.
- Update the governing contract and metrics documentation to describe these boundaries and evidence semantics.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `run-stall-watchdog`: add bounded SRE Unblocker invocation and immutable intervention evidence while preserving existing recovery authority and escalation rules.
- `temporal-multiseries-telemetry`: classify completed runs using intervention facts and expose the three requested outcomes without fabricating incomplete evidence.
- `continuous-improvement-feed`: accept evidence-linked recurrence proposals from SRE interventions through the existing operator-controlled feed.

## Impact

Affected areas include Watchdog/orchestration services and configured agent skills, the existing append-only PostgreSQL orchestration stage-event ledger, temporal telemetry/dashboard projections, the existing Mejora Continua feed, and `docs/CONTRATO_RECTOR.md` / `docs/METRICS.md`. Reuse `watchdog_diagnoses` for mutable diagnosis state and stage events for immutable intervention facts; no new table is presumed. No new scheduler, autonomous Issue creation, unrestricted remediation channel, or provider hardcoding is introduced.
