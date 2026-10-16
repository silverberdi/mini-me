# Provider and Capacity Policy

## Primary agents and stage profiles
Codex and Antigravity are the primary planning/execution providers. Each project configures provider, model, and effort independently by stage through existing configuration and adapter/authority paths; either primary may plan or execute a compatible stage and may take over from the other through a durable, fenced, idempotent handoff. No static profile alone proves availability. A substantive author may **not** authoritatively review the same candidate.

Before a stage is admitted, validate that the exact installed CLI/version supports the configured model, effort value, invocation syntax, and requested native workflow/role. A missing or unrecognized capability is incompatible, not permission to fall back to a guessed default. The complexity/risk floor comes from existing project policy, durable change requirements, or deterministic criteria; local-AI labels are advisory only. Select the least-cost configured profile that meets that floor and the tool requirements using a verified cost basis. Premium models and maximum effort are not defaults. Escalation requires objective evidence (for example, a measured failure class or deterministic complexity/risk threshold), a recorded reason, and a finite per-stage limit applied under the owner's configured spending policy. A valid account spending policy permits ordinary autonomous calls without per-call human approval; optional limits may further bound spend. R01 implements only the static per-stage profile and validation required by its assigned flow; adaptive optimization, benchmarking, and automatic profile learning are deferred.

### R01 stage responsibilities
- PLAN, APPLY, implementation TEST, and VERIFY/E2E: select Codex or Antigravity using the validated per-stage profile, exact CLI/workflow/model/effort capability, current capacity, and applicable spending policy. Read-only verification that mutates tracked candidate content becomes substantive authorship and requires a new candidate and independence evaluation.
- CONTRACT REVIEW: DeepSeek Direct reviews the exact OpenSpec contract read-only.
- Code REVIEW: DeepSeek Direct independently reviews the exact frozen candidate read-only, distinct from CONTRACT REVIEW.
- DeepSeek review stages never authorize APPLY, product decisions, or merge. If a required review is not eligible, preserve and wait; do not substitute an executor or OpenRouter.
- OpenRouter is not a primary stage provider or reviewer; it may rescue only previously started work when both Codex and Antigravity are blocked by quota, under its own verified capacity and applicable owner spending policy.

Every stage records the selected provider, protected account identity, model, effort, workflow/capability evidence, stage policy, capacity observation, billing origin, applicable spending-policy reference, provider-reported usage, and verified cost basis when available. Cost ordering is explicit in existing policy metadata; unknown cost is never treated as zero or as proof that a profile is least-cost. Reservations/per-operation bounds apply only where provider semantics or configured policy require them. Local AI helpers are optional and non-blocking; their output cannot authorize a stage or replace deterministic evidence.

## DeepSeek Direct — independent review authority
- DeepSeek Direct is the read-only independent reviewer for CONTRACT REVIEW and final code REVIEW; these are separate stages and evidence types. It does not plan, implement, or rescue work.
- A paid call requires exact review capability/model compatibility, verified account identity, current capacity/balance evidence, an applicable owner-approved spending policy for that account, and sufficient bounded input. Ordinary calls do not require new per-call human approval or a mandatory maximum. If capability, identity, capacity, or the applicable policy is missing or restrictive, preserve and wait; do not substitute another reviewer. Record provider-reported usage durably and idempotently.
- Direct API/account only; `DEEPSEEK_API_KEY` never goes to OpenRouter. DeepSeek review cannot authorize APPLY, product policy, merge, closure, or deployment.
- Plain API inference does **not** provide coding-tool/skills/write capability. Never treat a text response as proof of native OpenSpec `apply` or `verify`.

## Qwen local
Optional and non-blocking for preliminary complexity classification, context preparation/reduction, extraction, labeling, and other auxiliary tasks. It must not diagnose failures, implement authoritatively, review security, or make binding decisions. Its absence or failure never stops the pipeline, and it cannot satisfy review, audit, budget, or human gates merely because it is local. A future independent progress watchdog is outside R01; do not impose a fixed total inference timeout through this policy.

## OpenRouter drain fallback
- Disabled/no-spend unless explicitly configured.
- Used only for previously started work that must be completed when both primary providers are blocked by quota, with its own capacity evidence and an applicable owner-approved OpenRouter spending policy. No per-call approval is required when that policy already authorizes the operation.
- Does not admit new READY work.
- May finish eligible in-flight substantive work.
- OpenRouter is never a reviewer and cannot satisfy CONTRACT REVIEW or code REVIEW. DeepSeek Direct performs those stages under separate candidate/contract-bound review authority; if it is unavailable, wait.
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
  - **Reviewer Independence**: If Antigravity performs substantive implementation or premium recovery on a candidate, it cannot perform authoritative review of that candidate; DeepSeek Direct remains the independent reviewer.
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
