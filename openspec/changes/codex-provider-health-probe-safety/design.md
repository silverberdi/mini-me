# Design: Codex Provider Health Probe Safety

## Architectural Overview

The provider health subsystem evaluates CLI presence, authentication readiness, and inference capacity. For expensive providers like OpenAI Codex, availability probing executes real inference turns (`codex exec - --ephemeral`). This design specifies probe gating, failure classification, and execution environment safety.

```
+-------------------------------------------------------------------+
|                        Scheduler Loop                             |
+-------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|                  ProviderHealthService.check_and_probe            |
+-------------------------------------------------------------------+
                                  |
            +---------------------+---------------------+
            |                                           |
            v (cheap: agy, openrouter)                  v (expensive: codex)
+---------------------------------------+   +---------------------------------------+
| Check auth ready & execute probe      |   | 1. Is there actionable READY work     |
+---------------------------------------+   |    waiting on this provider?          |
                                            | 2. Check auth ready (login status)    |
                                            | 3. Reserve probe (cooldown/lock)      |
                                            | 4. Execute bounded codex exec probe   |
                                            |    with --skip-git-repo-check         |
                                            +---------------------------------------+
                                                        |
                                                        v
                                            +---------------------------------------+
                                            | Classify Outcome:                     |
                                            | - 401 / token_expired -> AUTH_REQUIRED|
                                            | - 0 -> AVAILABLE                      |
                                            | - non-zero -> TEMPORARILY_UNAVAILABLE |
                                            +---------------------------------------+
```

## Detailed Design Decisions

### 1. Actionable READY Work Gating for Expensive Probes

Automatic periodic background ticks MUST NOT execute expensive inference probes (`probe_is_expensive = True`) merely to monitor health.

`ProviderHealthService.check_and_probe_provider(provider)` evaluates probe eligibility according to:

```python
if expensive:
    # 1. Actionable READY work check
    has_ready_work = self._has_actionable_ready_work_for_provider(provider)
    if not has_ready_work:
        logger.debug(f"Skipping expensive probe for {provider}: no actionable READY work waiting.")
        return False
```

`_has_actionable_ready_work_for_provider(provider)` inspects the `WorkQueueItem` repository for any item where:
* `readiness_state == ReadinessState.READY` (or `admission_eligible == True`), AND
* The project's configured implementer or reviewer matches `provider`.

If no such actionable `READY` item exists, `check_and_probe_provider` skips executing `codex exec`, preventing periodic quota consumption during background idle ticks.

### 2. Failure Classification & `AUTH_REQUIRED` Handling

When `CodexProviderAdapter.probe_availability()` or `check_auth_ready()` executes, stdout and stderr are inspected for authentication failures:

* **Trigger Keywords / Statuses:**
  * `HTTP 401` / `401 Unauthorized`
  * `token_expired`
  * `Failed to refresh token`
  * `Please log out and sign in again`
  * `authentication required` / `not logged in` / `login required`

* **Classification & State Transitions:**
  * Result Class: `ProviderResultClass.AUTH_ERROR`
  * Provider Status: `ProviderHealthStatus.AUTH_REQUIRED`
  * Event Emitted: `PROVIDER_HEALTH_UPDATED` with payload `{"status": "auth_required", "reason": "TOKEN_EXPIRED"}`
  * Admission Decision: Evaluates to `AdmissionDecisionKind.NEEDS_HUMAN` (Rationale: `Provider 'codex' requires human re-authentication.`).
  * Quota Protection: `AUTH_REQUIRED` status halts repeated expensive background probes until re-authenticated.

### 3. Probe Execution Command Safety (`--skip-git-repo-check`)

`CodexProviderAdapter.probe_availability()` executes:

```python
cmd = [
    resolved,
    "exec",
    "-",
    "--ephemeral",
    "--skip-git-repo-check",
]
```

Including `--skip-git-repo-check` ensures that Codex CLI executes the probe cleanly regardless of working directory trust status, preventing untrusted repository checks from being misclassified as provider capacity or network failures.

### 4. Canonical Operator Recovery Procedure for `minime` Service Identity

When `codex` provider health transitions to `AUTH_REQUIRED`:

1. **Stop Scheduler:**  
   `sudo systemctl stop minime-scheduler.service`
2. **Execute Re-Authentication as Service User:**  
   `sudo -u minime -H /opt/minime/runtime/venv/bin/codex login`
3. **Verify Non-Inference Auth Readiness:**  
   `sudo -u minime -H /opt/minime/runtime/venv/bin/codex login status` (Confirm exit code 0 and valid status).
4. **Perform One Controlled Verification (Optional):**  
   `echo "probe" | sudo -u minime -H /opt/minime/runtime/venv/bin/codex exec - --ephemeral --skip-git-repo-check` (Confirm exit code 0).
5. **Restart Scheduler:**  
   `sudo systemctl start minime-scheduler.service`

### 5. Preserved Scheduler & Admission Invariants

All landed `scheduler-capacity-policy-convergence` invariants remain intact:
* Operational Decision Taxonomy: `RUN`, `DRAIN`, `WAIT`, `NEEDS_HUMAN`.
* `UNKNOWN` never `RUN`.
* `AUTH_REQUIRED` -> `NEEDS_HUMAN`.
* `DRAIN` continuation-only.
* No alternate implementer/reviewer pair search during fresh admission.
* `EVIDENCE_INSUFFICIENT` -> `NEEDS_HUMAN` (no automatic retries).
* No OpenRouter fresh-admission fallback.
