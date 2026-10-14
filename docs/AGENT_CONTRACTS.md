# Agent Role Contracts

## OpenSpec proposer / updater / implementer / verifier (Codex or Antigravity)
Receives authoritative Business Intent, accepted backlog ficha, active OpenSpec artifacts, exact workspace, project policy, tools/skills/hooks/harnesses, deterministic checks and prior findings. The **agent runs installed native OpenSpec workflows** (tool-specific propose/update/continue/apply/verify/sync/archive); the mini me daemon never recreates their semantic work. The agent must stay in scope, modify only assigned worktree, preserve unrelated code and return tool-invocation evidence and artifact/candidate/check identities. Material ambiguities are escalated before editing.

## Complementary reviewer (Antigravity or Codex)
Starts read-only. Receives same OpenSpec change, candidate diff and check evidence. Evaluates spec compliance, correctness, regression risk, tests, security and maintainability. It does not silently become implementer.

Normalized review shape is defined in `schemas/reviewer-result.schema.json`.

## DeepSeek Direct optional authorized analyst or conditional reviewer
DeepSeek Direct is an optional, paid, read-only API capability and is never a mandatory audit stage. It may be used as an analyst only under the applicable policy or explicit operator authorization; it is never proxied through OpenRouter. Analyst output uses `schemas/audit-result.schema.json` and cannot satisfy an independent review gate.

R01 additionally permits DeepSeek Direct as an authoritative read-only reviewer **only** when no eligible primary reviewer can serve the stage and a separate reviewer contract is implemented and verified for the exact candidate. Before invocation, the system must verify complete candidate-bound input, compatible review capability, reviewer identity distinct from every surviving substantive author, a structured response validated deterministically against the candidate/repository/base/head/generation/manifest, and explicit per-stage provider and budget authorization. This is a distinct review result under `schemas/reviewer-result.schema.json`; audit records or audit responses must never be converted into review evidence. Missing, stale, incomplete, ambiguous, unauthorized, or incompatible evidence fails closed and preserves the candidate in a waiting/blocked state. A qualifying review satisfies only the review gate and never authorizes merge, closure, or deployment; human merge remains mandatory.

## OpenRouter authorized fallback executor
May finish eligible in-flight work only after both primaries cannot serve the stage, explicit operator authorization, budget allowance, and proof the runner can actually invoke tools/workflows and write within the sandbox. API text generation alone is not OpenSpec implementation. It may not cause admission of a new READY change.

## OpenRouter drain reviewer
May authoritatively review in DRAIN only when its model identity differs from the latest substantive implementer model for the candidate. If distinct review capacity is unavailable, wait rather than self-review.

## Qwen local helper
Advisory/mechanical only. Cannot satisfy review, audit, security, budget or human gates.

## Delivery evidence
No agent may self-certify E2E or deploy success. The harness verifies real OpenSpec workflow usage, diff/tests/review/candidate PR and behavior postdeploy, with actor/model/tool/version/skill hashes. Unit/integration PASS is not product completion.

## Human
Durable authority for final approval, UI validation judgment, merge, product/spec ambiguity, sensitive findings, policy overrides, budget increases and rollback authorization.
