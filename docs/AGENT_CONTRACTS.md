# Agent Role Contracts

## OpenSpec proposer / updater / implementer / verifier (Codex or Antigravity)
Receives authoritative Business Intent, accepted backlog ficha, active OpenSpec artifacts, exact workspace, project policy, tools/skills/hooks/harnesses, deterministic checks and prior findings. The **agent runs installed native OpenSpec workflows** (tool-specific propose/update/continue/apply/verify/sync/archive); the mini me daemon never recreates their semantic work. The agent must stay in scope, modify only assigned worktree, preserve unrelated code and return tool-invocation evidence and artifact/candidate/check identities. Material ambiguities are escalated before editing.

For R01, stage assignments are: Codex PLAN; DeepSeek Direct preferred for CONTRACT REVIEW only with compatible read-only capability, fresh capacity, and explicit provider/stage/budget authorization, otherwise AGY; AGY APPLY and implementation TEST; Codex VERIFY/E2E; final REVIEW follows candidate-bound independence and the existing eligible-reviewer policy. Each stage's provider, model, and effort is configured independently and validated against the exact installed CLI/version and workflow. Use the least-cost profile that meets documented stage complexity/risk; premium models/max effort are not defaults. An escalation requires objective evidence, a recorded justification, a finite limit, and explicit budget authority. R01 does not build dynamic model optimization.

## Complementary reviewer (Antigravity or Codex)
Starts read-only. Receives same OpenSpec change, candidate diff and check evidence. Evaluates spec compliance, correctness, regression risk, tests, security and maintainability. It does not silently become implementer.

Normalized review shape is defined in `schemas/reviewer-result.schema.json`.

## DeepSeek Direct optional authorized analyst or conditional reviewer
DeepSeek Direct is an optional, paid, read-only API capability and is never a mandatory audit stage. It may be used as an analyst only under the applicable policy or explicit operator authorization; it is never proxied through OpenRouter. Analyst output uses `schemas/audit-result.schema.json` and cannot satisfy an independent review gate.

For R01 CONTRACT REVIEW only, DeepSeek Direct is preferred over AGY when a compatible read-only contract-review profile, fresh capacity, and explicit provider/stage/budget authorization are all proven. The review is limited to OpenSpec contract consistency and risks; it cannot authorize APPLY, make product decisions, satisfy final code review, or approve merge. If DeepSeek is ineligible, AGY is the alternative; if neither is eligible, preserve the work and wait without inference.

The separate final-code-review exception remains governed by the existing rule: DeepSeek may act as authoritative reviewer only when no eligible primary reviewer can serve and a distinct candidate-bound review contract is implemented and verified. Before invocation, verify complete candidate-bound input, compatible review capability, reviewer identity distinct from every surviving substantive author, structured response validated deterministically against candidate/repository/base/head/generation/manifest, and explicit per-stage provider and budget authorization. This distinct review result uses `schemas/reviewer-result.schema.json`; audit records or audit responses must never be converted into review evidence. Missing, stale, incomplete, ambiguous, unauthorized, or incompatible evidence fails closed and preserves the candidate in a waiting/blocked state. Any qualifying final review satisfies only the review gate and never authorizes merge, closure, or deployment; human merge remains mandatory.

## OpenRouter authorized fallback executor
May finish eligible in-flight work only after both primaries cannot serve the stage, explicit operator authorization, budget allowance, and proof the runner can actually invoke tools/workflows and write within the sandbox. API text generation alone is not OpenSpec implementation. It may not cause admission of a new READY change.

## OpenRouter drain reviewer
May authoritatively review in DRAIN only when its model identity differs from the latest substantive implementer model for the candidate. If distinct review capacity is unavailable, wait rather than self-review.

## Qwen local helper
Optional, non-blocking assistance only for preliminary complexity classification, context preparation/reduction, extraction, labeling, and other auxiliary work. It must not diagnose failures, implement authoritatively, review security, or make binding decisions. Its unavailability or failure cannot stop the pipeline and it cannot satisfy review, audit, security, budget, or human gates.

## Delivery evidence
No agent may self-certify E2E or deploy success. The harness verifies real OpenSpec workflow usage, diff/tests/review/candidate PR and behavior postdeploy, with actor/model/tool/version/skill hashes. Unit/integration PASS is not product completion.

## Human
Durable authority for final approval, UI validation judgment, merge, product/spec ambiguity, sensitive findings, policy overrides, budget increases and rollback authorization.
