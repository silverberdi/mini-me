# Provider and Capacity Policy

## Normal primary pairing
Each project configures exactly one primary implementer and the complementary reviewer:
- Codex implements → Antigravity reviews.
- Antigravity implements → Codex reviews.

## DeepSeek Direct
- Role: independent read-only auditor.
- Direct API configuration only.
- `DEEPSEEK_API_KEY` must never be exposed to OpenRouter.
- Auditor reports findings/risk; it does not modify the repo or approve closure.

## Qwen local
Optional advisory helper for mechanical tasks such as log triage, context compaction and summaries. It cannot satisfy implementation review, audit, budget or human gates merely because it is local.

## OpenRouter drain fallback
- Disabled/no-spend unless explicitly configured.
- Used only when both primary subscription providers are exhausted/unavailable under the configured capacity policy.
- Does not admit new READY work.
- May finish eligible in-flight substantive work.
- If OpenRouter performs implementation and review in the same candidate flow, the authoritative reviewer model must differ from the latest substantive implementer model.
- If no distinct allowed reviewer model is available, wait for capacity rather than self-review.
- DeepSeek Direct remains the independent audit layer.

## Failure taxonomy
Normalize at least: `success`, `transient_error`, `quota_limit`, `rate_limit`, `auth_error`, `timeout`, `malformed_output`, `cancelled`, `policy_denied`, `unsafe_binding`, `unknown_error`.

## Retry defaults
- transient/network: up to 3 attempts with bounded backoff.
- timeout: up to 2 attempts.
- malformed structured output: one repair retry, then escalate/block per policy.
- auth/config/security/repository mismatch: no blind retry.
- quota: wait/cooldown; never hammer in a retry loop.
- review correction loop: max 2 rounds by default, then human escalation.

Retry only operations known to be safe to repeat. GitHub/deployment side effects require idempotent lookup/reconciliation rather than blind re-execution.

## Capacity metadata
Persist provider capacity state, signal source, observed/reset/retry timestamps and confidence. Codex may expose preflight usage signals; adapters should consume them when reliably available. If reset is unknown, re-probe conservatively.
