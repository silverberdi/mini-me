# Provider and Capacity Policy

## Primary agents by OpenSpec stage
Each project configures permitted Codex/Antigravity roles and preferences **per stage** (proposer, implementer, verifier, reviewer, closer). Both are coding agents using installed OpenSpec workflows, not fixed lifetime roles. A candidate's substantive implementer may **not** be its authoritative reviewer. Prefer existing subscription capacity with cost-aware reservations and safe checkpoint boundaries.

## DeepSeek Direct — authorized exception
- **Not a mandatory routine audit stage.** Allowed as optional explicitly authorized analysis/review/fallback only when both primaries cannot serve the required stage and its tool capabilities satisfy the request.
- Direct API configuration only; `DEEPSEEK_API_KEY` never goes to OpenRouter.
- Plain API inference does **not** provide coding-tool/skills/write capability. Never treat a text response as proof of native OpenSpec `apply` or `verify`.
- It does not modify the repo, approve PR/closure or bypass independent review/human gates.

## Qwen local
Optional advisory helper for mechanical tasks such as log triage, context compaction and summaries. It cannot satisfy implementation review, audit, budget or human gates merely because it is local.

## OpenRouter drain fallback
- Disabled/no-spend unless explicitly configured.
- Used only after both primary subscription agents are exhausted/unavailable for the required stage, with **explicit operator authorization** and budget for each fallback policy episode.
- Does not admit new READY work.
- May finish eligible in-flight substantive work.
- If OpenRouter performs implementation and review in the same candidate flow, the authoritative reviewer model must differ from the latest substantive implementer model.
- If no distinct allowed reviewer model is available, wait for capacity rather than self-review.
- No mandatory DeepSeek Direct layer. The authoritative review is an eligible distinct agent/model with verifiable evidence; if absent, wait.
## Antigravity Routine vs Premium Recovery Policy
- **Routine implementation**: Stage/provider selection is constrained by approved per-project policy and cost/capacity, but Antigravity is not globally banned from proposing, implementing or reviewing a distinct stage. Fixed project preferences are not permanent global roles.
- **Bounded Premium Recovery (`PREMIUM_RECOVERY_NON_CONVERGENCE`)**:
  Antigravity may be assigned as a bounded premium recovery executor only when an explicit canonical premium reason is satisfied:
  1. Material candidate progress already exists (`is_material_execution_started` is True / candidate SHA exists).
  2. The primary executor (Codex) exhibits non-convergence (repeated malformed results, failing checks, premature stops, or no progress where bounded retry/reassignment budgets are exhausted).
  3. Continuing with the primary executor is unlikely to converge.
  4. Antigravity is available.
- **Premium Recovery Constraints**:
  - **Strictly Bounded**: Maximum one premium recovery attempt for the same failure episode.
  - **Anti-Ping-Pong**: Cycling `Codex -> Antigravity -> Codex -> Antigravity` on the same unchanged failure is strictly prohibited.
  - **Lineage & Diagnostics**: The system persists recovery reason, originating provider, failure classification, candidate SHA before recovery, recovery provider, attempt identity, and outcome.
  - **Reviewer Independence**: If Antigravity performs substantive implementation or premium recovery on a candidate, Antigravity is strictly forbidden from performing authoritative review of that candidate. Reviewer role must be reassigned to Codex or an eligible distinct model.
  - **Recovery vs Quota**: Premium recovery is justified by non-convergence / recovery semantics, never merely by provider quota exhaustion. Routine quota exhaustion transitions to `WAITING_CAPACITY` or authorized OpenRouter drain.

## Failure taxonomy
Normalize at least: `success`, `transient_error`, `quota_limit`, `rate_limit`, `auth_error`, `timeout`, `malformed_output`, `cancelled`, `policy_denied`, `unsafe_binding`, `unknown_error`.

## Retry defaults
- transient/network: up to 3 attempts with bounded backoff.
- timeout: up to 2 attempts.
- malformed structured output: one repair retry, then escalate/block per policy.
- auth/config/security/repository mismatch: no blind retry.
- quota: wait/cooldown; never hammer in a retry loop.
- review correction loop: bounded attempts by **current candidate/generation/failure episode** with material-progress checks; exceeding limits yields a machine-operable blocked/wait/recovery diagnosis, not automatically a fake human decision.

Retry only operations known to be safe to repeat. GitHub/deployment side effects require idempotent lookup/reconciliation rather than blind re-execution.

## Capacity metadata
Persist provider capacity state, signal source, observed/reset/retry timestamps and confidence. Preflight before expensive agent stages, estimate conservatively only when grounded, reserve checkpoints, and never invent remaining tokens or reset times. Codex may expose preflight usage signals; adapters should consume them when reliably available. If reset is unknown, re-probe conservatively.
