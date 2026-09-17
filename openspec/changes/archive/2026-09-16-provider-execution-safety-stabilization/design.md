# Design: Provider Execution Safety Stabilization

## Architectural Approach

Stabilize the provider execution layer without redesigning provider/model selection or the capability registry. The core principle separates *readiness* (can this CLI run, and is it authenticated?) from *capacity* (can it actually consume inference right now), and treats anything that can consume quota as an exceptional, bounded, observable event. Existing canonical enums (`ProviderHealthStatus`, `ProviderResultClass`, `CapacitySignalSource`, `ExecutionOutcome`, `EventType`) express all required states; no new domain enum is introduced.

## Key Decisions

### D1 - Readiness/capacity separation using existing enums
- `CLI_PRESENT`: the configured executable resolves via `shutil.which`. False results in health `misconfigured`/`unreachable` with NO inference probe.
- `AUTH_READY`: non-inference auth/readiness status. False results in a truthful `auth_required` outcome.
- `PROVIDER_AVAILABLE`: transport/CLI reachable (health `available`).
- `CAPACITY_AVAILABLE`: not `exhausted`.
These map onto existing `ProviderHealthStatus` values; no new domain state is introduced.

### D2 - Split the adapter probe contract
`ProviderAdapterInterface.probe_availability()` currently conflates readiness and capacity. Split it into:
- `check_cli_present() -> bool`: local and quota-free (executable resolvable).
- `check_auth_ready() -> bool`: local/non-inference where the installed CLI supports it.
- `probe_availability(...) -> bool`: capacity probe that SHALL declare an expensive classification when it can consume quota/inference.
- `probe_verifies_capacity() -> bool`: True only when a successful `probe_availability()` is valid evidence that an exhausted provider's inference capacity has actually recovered. Cheap readiness/reachability probes (`agy models`, HTTP `/models`) are False and MUST NOT promote an exhausted provider back to `available`.
Codex: implement `check_cli_present`, then investigate the installed CLI for a deterministic non-inference auth command (for example `codex login status`). Do NOT assume such a command exists - prove it during implementation. If none exists, auth readiness stays `unverified` and only the cooldown/backoff-gated capacity probe runs. Antigravity already uses `agy models` (local/auth, non-inference); that stays a cheap readiness check and is NOT an expensive probe.

### D3 - Deterministic cooldown/backoff (config-driven, no hidden magic numbers)
New explicit per-provider `probe:` configuration with documented defaults:
- `cooldown_seconds: 300` - minimum interval between probes and the first-retry timing.
- `backoff_base_seconds: 300` and `backoff_max_seconds: 3600`.
- `max_per_hour: 4` - rolling one-hour cap for expensive probes.

A probe may run only when ALL of the following hold:
1. The provider is not `available`.
2. If `capacity_reset_at` is known and in the future, `now >= capacity_reset_at`.
3. `now >= last_probe_at + cooldown_seconds`.
4. `now >= last_probe_at + backoff`, where `backoff = min(backoff_base_seconds * 2**(consecutive_probe_failures - 1), backoff_max_seconds)`.
5. Expensive probes in the trailing one hour are below `max_per_hour`.

On probe success: `consecutive_probe_failures = 0`. On probe failure: `consecutive_probe_failures += 1`. Unknown reset timing is governed by rules 3-5 alone and SHALL NEVER imply immediate probing.

This corrects the divergence in `ProviderHealthService.check_and_probe_provider`, where unknown reset currently forces `is_reset_elapsed = True` (`src/minime/services/provider_health_service.py:278-280`), which produced the production probe storm.

### D4 - Probe cadence and observability
`scheduler_service.tick()` calls `probe_unavailable_providers()` every cycle; that call becomes cheap because every provider probe is gated by the D3 rules inside the health service, so ticks while a provider is unavailable do not produce probes. Expensive probes persist an observable event (provider, kind=`expensive`, timestamp, outcome) and create no Runs/Jobs and consume no implementation retry budget.

### D5 - Remove the OpenRouter fake candidate
Remove placeholder-candidate creation in the OpenRouter success branch of `src/minime/services/execution_pipeline.py` (currently writes `# OpenRouter fallback candidate artifact` into `candidate_impl.py` and commits it). When OpenRouter - or any provider - is selected as implementer but has no real repository-editing harness, the pipeline SHALL return a truthful governed outcome (`ExecutionOutcome.EVIDENCE_INSUFFICIENT` or `PROVIDER_FAILURE`; orchestration stop `FAILED` or `WAITING_EXTERNAL`), with no repository mutation, no candidate commit, no implementation-success claim, and no false progress event. The budget reservation is settled as unresolved/refunded because no work materialized. `MockImplementerRunner` placeholder behavior is test scaffolding, NOT a production defect; it is unchanged unless a specific regression test justifies a test-only adjustment.

### D6 - Candidate truth invariant
A candidate may exist only when real repository files were materially changed for the requested task, the changes are candidate-bound, candidate integrity is verifiable, and the implementation can be reviewed against the requested change. This relies on the existing fail-closed completion verification in `agent-execution-outcome-governance` plus candidate-integrity verification. Once the fake OpenRouter path is removed, placeholder-only or non-materialized diffs fail closed as `NO_PROGRESS` or `EVIDENCE_INSUFFICIENT`.

### D7 - Headless CLI proving and preflight flag validation
Add deterministic compatibility tests that prove the configured invocations are accepted by the installed CLIs when present:
- Codex implementer `codex exec - --approve-for-me --ephemeral` (stdin transport).
- Codex reviewer `codex review -` (stdin transport). The prior `codex exec - --sandbox read-only --ask-for-approval never --ephemeral` form was corrected during proving: codex-cli 0.147.0 has no `--ask-for-approval`, and `codex review` is the non-interactive read-only reviewer.
- Antigravity implementer `agy --mode accept-edits --dangerously-skip-permissions --print-timeout 1h --print={prompt}` (argument transport).
- Antigravity reviewer `agy --mode plan --dangerously-skip-permissions --print-timeout 1h --print={prompt}` (argument transport).
Tests SKIP when the CLI is absent and FAIL FAST when an installed CLI rejects a configured flag. Preflight validates the invocation before a full attempt so unsupported/deprecated flags never consume a full implementation attempt or implementation retry budget.

### D8 - Process safety (preserve and prove)
`CliImplementerRunner` and `CliReviewerRunner` already provide asyncio subprocess execution, `start_new_session`, configurable timeout, SIGTERM with bounded grace then SIGKILL, process-group isolation, and bounded/redacted output. Preserve these properties and add deterministic tests proving: timeout terminates the process group, and cancellation leaves no orphan subprocesses. Timeout/cancellation results remain truthful (never reported as success).

## Persistence / Migration
Add probe-attempt state to `provider_health` through a versioned Alembic migration: `last_probe_at` (nullable timestamptz) and `consecutive_probe_failures` (integer, default 0). Probe events reuse existing `EventType` values where they fit, with `kind=expensive` metadata on expensive probes; if no existing event value cleanly expresses an executed probe, one explicit event kind may be added. Runtime probe/quota/backoff counters remain operational data in PostgreSQL, never OpenSpec content.

## Operational Proving Requirements
- The production scheduler remains disabled/inactive throughout implementation and deployment proving and is re-enabled only after post-merge proving completes and the operator explicitly decides to.
- Proving runs on the Mac development repository and, where required, an isolated containerized preview; no production server state is modified.
- Deterministic evidence (test output, probe-count assertions, CLI version/flag acceptance) is recorded before any closure claim.

## Non-Goals
OpenCode integration, `ai-provider-model-capability-selection` redesign, effectiveness-telemetry redesign, provider/model capability-registry redesign, adaptive/telemetry-based routing, new autonomous merge authority, and scheduler restart/reboot policy beyond provider-execution safety are explicitly out of scope.

## Rollback
This change is reversible: revert config defaults, the health-service cooldown/backoff gate, the adapter probe split, the removed OpenRouter placeholder branch, and the probe-state migration (down-revision). It introduces no irreversible external side effects.
