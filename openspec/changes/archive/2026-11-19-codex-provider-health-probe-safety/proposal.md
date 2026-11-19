# Proposal: Codex Provider Health Probe Safety

## Executive Summary
This OpenSpec change addresses critical defects in the Codex provider health probing lifecycle:
1. **Unthrottled Quota Consumption:** Automatic background scheduler ticks currently execute real inference commands (`codex exec - --ephemeral`) to probe provider health even when no actionable `READY` work requires Codex execution.
2. **Auth Failure Misclassification:** Expired access/refresh tokens (`HTTP 401 Unauthorized`, `token_expired`, `Failed to refresh token`, `Please log out and sign in again`) are misclassified as generic `UNKNOWN_ERROR` or `TEMPORARILY_UNAVAILABLE`, triggering repeated failed background probes and misleading operational metrics.
3. **Untrusted Working Directory Failures:** The availability probe command lacks `--skip-git-repo-check`, causing probes to fail with exit code 1 whenever the working directory is not explicitly trusted by Codex CLI, misrepresenting CLI configuration issues as provider capacity loss.

This change establishes safe probe gating (requiring actionable `READY` work before executing expensive probes), accurate `AUTH_REQUIRED` failure classification, robust CLI probe command flags, and a documented canonical operator recovery procedure for the `minime` service identity.

## Problem Statement
Production diagnosis on host `192.168.0.194` revealed that:
* `codex login status` returns exit code 0 when local credential files exist, but actual API calls fail with `HTTP 401 Unauthorized` (`token_expired`) because the OAuth token cannot be refreshed.
* The scheduler's automatic health probing loop invokes `CodexProviderAdapter.probe_availability()` via `codex exec - --ephemeral`. Because `probe_is_expensive = True`, periodic background ticks execute real inference turns, consuming paid API quota continuously without any pending work.
* `codex exec` fails with exit code 1 (`Not inside a trusted directory and --skip-git-repo-check was not specified`) when run in untrusted directories, causing `ProviderHealthService` to misclassify directory permission/trust errors as provider unavailability.
* Token expiry responses (`401`, `token_expired`) are saved as `UNKNOWN_ERROR` or `TEMPORARILY_UNAVAILABLE` rather than `AUTH_REQUIRED`, preventing the system from producing a truthful `NEEDS_HUMAN` decision requiring operator re-authentication.

## Proposed Solution
1. **Gated Expensive Probing:** Automatic periodic background scheduler ticks must NOT execute expensive inference probes (`probe_is_expensive = True`) unless there is actionable `READY` work waiting specifically on that provider's capacity, auth readiness has passed, and backoff/cooldown permits it.
2. **Accurate Auth Failure Classification:** Detect `HTTP 401`, `token_expired`, `Failed to refresh token`, and `Please log out and sign in again` errors in provider probe responses, classifying them as `AUTH_REQUIRED` with result class `AUTH_ERROR`. Provider status transitions to `AUTH_REQUIRED`, yielding a truthful `NEEDS_HUMAN` decision and halting repeated paid probes.
3. **CLI Probe Command Safety:** Ensure `CodexProviderAdapter.probe_availability()` includes `--skip-git-repo-check` (or executes in a trusted context) so directory trust issues never masquerade as provider capacity loss.
4. **Canonical Operator Recovery Procedure:** Document the exact production recovery protocol for re-authenticating the `minime` service user (`sudo -u minime -H codex login`) while keeping `minime-scheduler.service` safely stopped during credential updates.

## Scope & Non-Goals

### In Scope
* Probe gating in `ProviderHealthService` preventing un-gated expensive background probes without actionable `READY` work.
* Auth error classification mapping for Codex CLI/API output.
* Probe command flag updates (`--skip-git-repo-check`).
* Canonical operator recovery documentation for `minime` service user authentication.
* Unit and integration tests covering auth failure classification, probe gating, and admission invariants.

### Out of Scope / Non-Goals
* Dynamic provider routing or fallback to OpenRouter for fresh admissions.
* Automatic re-authentication or silent credential copying between OS users.
* Altering converged scheduler operational decisions (`RUN`, `DRAIN`, `WAIT`, `NEEDS_HUMAN`).
* Modifying production provider health rows or re-authenticating production host during candidate authoring.
