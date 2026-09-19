# Specification: Codex Provider Health Probe Safety

## ADDED Requirements

### Requirement: Gated Expensive Background Probing
1. The system MUST NOT execute an expensive inference probe (`probe_is_expensive = True`) during periodic background scheduler ticks unless there is at least one actionable `READY` work queue item waiting specifically for that provider's role (`implementer` or `reviewer`).
2. When no actionable `READY` work exists, `ProviderHealthService.check_and_probe_provider()` MUST return `False` without invoking `codex exec`.
3. When actionable `READY` work exists, provider CLI availability, non-inference auth readiness, cooldown/backoff windows, and probe reservation locks MUST be verified prior to initiating the expensive probe.

#### Scenario: Background scheduler tick with no actionable READY work
- **GIVEN** `codex` health is `TEMPORARILY_UNAVAILABLE`
- **AND** there are 0 actionable `READY` work items in the queue for project `mini-me`
- **WHEN** `ProviderHealthService.probe_unavailable_providers()` or `check_and_probe_provider('codex')` executes during a background tick
- **THEN** `check_and_probe_provider('codex')` returns `False` immediately without running `codex exec - --ephemeral`
- **AND** zero paid API quota is consumed.

#### Scenario: Background scheduler tick with actionable READY work
- **GIVEN** work item `001-ready-task` is in `ReadinessState.READY` with implementer `codex`
- **AND** `codex` CLI is present and `codex login status` returns exit code 0
- **AND** cooldown backoff permits probing
- **WHEN** `ProviderHealthService.check_and_probe_provider('codex')` executes
- **THEN** an expensive capacity probe reservation is attempted
- **AND** `codex exec - --ephemeral --skip-git-repo-check` is executed to verify capacity.

### Requirement: Auth Failure Classification & Operational Response
1. Provider probes or readiness checks returning HTTP status `401`, `token_expired`, `Failed to refresh token`, `Please log out and sign in again`, or authentication errors MUST be classified as `ProviderResultClass.AUTH_ERROR`.
2. The provider's health status MUST transition to `ProviderHealthStatus.AUTH_REQUIRED`.
3. An expired token response MUST NOT be classified as `UNKNOWN_ERROR`, `TEMPORARILY_UNAVAILABLE`, `RATE_LIMIT`, or `QUOTA_LIMIT`.
4. When a project's configured implementer or reviewer has status `AUTH_REQUIRED`, `SchedulerService.evaluate_admission()` MUST return operational decision `NEEDS_HUMAN` with block condition `AUTH_REQUIRED`.
5. Providers in `AUTH_REQUIRED` state MUST NOT trigger repeated automatic background expensive probes.

#### Scenario: Probe fails with token expired 401 error
- **GIVEN** `codex exec` probe returns exit code 1 with output containing `HTTP 401 Unauthorized` and `token_expired`
- **WHEN** `ProviderHealthService` processes the probe result
- **THEN** result class is classified as `ProviderResultClass.AUTH_ERROR`
- **AND** provider health status for `codex` transitions to `ProviderHealthStatus.AUTH_REQUIRED`
- **AND** subsequent background ticks return `NEEDS_HUMAN` without re-executing `codex exec`.

### Requirement: Safe Probe Command Execution Context
1. All execution-capacity probes dispatched via `CodexProviderAdapter` MUST include `--skip-git-repo-check` (or execute within an explicitly verified trusted repository context).
2. Failure due to untrusted directory policies (`Not inside a trusted directory`) MUST NOT be interpreted as provider capacity loss or network error.

#### Scenario: Ephemeral probe executed outside trusted repository
- **GIVEN** `CodexProviderAdapter.probe_availability()` is called in any working directory
- **WHEN** the subprocess `codex exec - --ephemeral` is spawned
- **THEN** the command arguments include `--skip-git-repo-check`
- **AND** untrusted repository warnings do not cause spurious exit code 1 failures.

### Requirement: Preservation of Converged Scheduler Policy Invariants
1. The scheduler operational decision taxonomy MUST remain strictly `RUN`, `DRAIN`, `WAIT`, `NEEDS_HUMAN`.
2. `UNKNOWN` capacity MUST fail closed (`NEEDS_HUMAN`).
3. `DRAIN` mode MUST apply strictly to eligible in-flight continuations and never admit fresh READY work.
4. `EVIDENCE_INSUFFICIENT` MUST evaluate to `NEEDS_HUMAN` with no automatic retries.
5. No alternate provider pair search or OpenRouter fresh-admission fallback shall be invoked.

#### Scenario: Admission evaluation when implementer is AUTH_REQUIRED
- **GIVEN** project implementer `codex` is in `ProviderHealthStatus.AUTH_REQUIRED`
- **WHEN** `SchedulerService.evaluate_admission()` is called for a READY work item
- **THEN** the result decision is `AdmissionDecisionKind.NEEDS_HUMAN`
- **AND** block condition is `AdmissionBlockCondition.AUTH_REQUIRED`
- **AND** no alternate implementer is substituted.
