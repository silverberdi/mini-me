# Provider and Capacity Policy

## Primary agents by OpenSpec stage
Each project configures provider, model, and effort independently for PLAN, CONTRACT REVIEW, APPLY, TEST, VERIFY/E2E, and final REVIEW. These are initial stage profiles, not a second scheduler or a dynamic optimizer. The existing project configuration, provider-adapter registry, capacity authorities, and budget controls remain the source and enforcement path. Both Codex and Antigravity can serve different compatible stages; neither is a permanent lifetime role. A candidate's substantive implementer may **not** be its authoritative final reviewer.

Before a stage is admitted, validate that the exact installed CLI/version supports the configured model, effort value, invocation syntax, and requested native workflow/role. A missing or unrecognized capability is incompatible, not permission to fall back to a guessed default. The complexity/risk floor comes from existing project policy, durable change requirements, or deterministic criteria; local-AI labels are advisory only. Select the least-cost configured profile that meets that floor and the tool requirements using a verified cost basis. Premium models and maximum effort are not defaults. Escalation requires objective evidence (for example, a measured failure class or deterministic complexity/risk threshold), a recorded reason, a finite per-stage limit, and explicit budget authorization. R01 implements only the static per-stage profile and validation required by its assigned flow; adaptive optimization, benchmarking, and automatic profile learning are deferred.

### R01 initial stage assignment
- PLAN: Codex.
- CONTRACT REVIEW: DeepSeek Direct preferred only when read-only contract-review capability, compatible model, fresh capacity, and explicit provider/stage/budget authorization all pass; otherwise use the configured AGY alternative. If neither is eligible, wait without consuming inference.
- APPLY and implementation TEST: Antigravity.
- VERIFY/E2E: Codex, read-only against the frozen candidate; if any tracked candidate content changes, it is treated as substantive authorship and requires a new candidate plus refreshed independence evaluation.
- Final REVIEW: the existing independent-review policy, resolved from actual surviving authorship, configured eligible reviewers, verified capabilities, and capacity. The CONTRACT REVIEW preference does not alter final code-review fallback policy. If no independent reviewer is eligible, wait.

Every stage records the selected provider, model identity, effort, capability/version evidence, policy profile, capacity observation, budget authorization, verified cost basis/ranking, and escalation rationale when applicable. Cost ordering is explicit in existing policy/budget metadata; unknown cost is never treated as zero or as proof that a profile is least-cost. Local AI helpers are optional and non-blocking; their output cannot authorize a stage or replace deterministic evidence.

## DeepSeek Direct — authorized exception
- **Never an implicitly required paid stage.** For R01 CONTRACT REVIEW only, DeepSeek Direct is the preferred read-only reviewer when the exact configured model is compatible, capacity is freshly proven, and explicit provider/stage/budget authorization is present. If any condition is missing or uncertain, use the configured AGY alternative; if AGY is also ineligible, wait. This stage-specific preference is not the final code-review policy and does not make a paid call mandatory.
- Other DeepSeek analysis or final-review/fallback use remains optional and subject to its existing policy, including explicit authorization and any required primary unavailability.
- Direct API configuration only; `DEEPSEEK_API_KEY` never goes to OpenRouter.
- Plain API inference does **not** provide coding-tool/skills/write capability. Never treat a text response as proof of native OpenSpec `apply` or `verify`.
- CONTRACT REVIEW is strictly read-only and can only return structured contract findings. It cannot authorize APPLY, decide product policy, satisfy final code review, approve a PR, or bypass human merge/closure gates.

## Qwen local
Optional and non-blocking for preliminary complexity classification, context preparation/reduction, extraction, labeling, and other auxiliary tasks. It must not diagnose failures, implement authoritatively, review security, or make binding decisions. Its absence or failure never stops the pipeline, and it cannot satisfy review, audit, budget, or human gates merely because it is local.

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
