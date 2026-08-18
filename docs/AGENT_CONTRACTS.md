# Agent Role Contracts

## Implementer (Codex or Antigravity)
Receives active OpenSpec artifacts, exact workspace, project policy, deterministic checks and prior findings when correcting. Must stay in scope, modify only the assigned worktree, run relevant checks, preserve unrelated code and return a normalized handoff with changed files/tests/questions/evidence. Behavior-changing ambiguity is escalated, not guessed.

## Complementary reviewer (Antigravity or Codex)
Starts read-only. Receives same OpenSpec change, candidate diff and check evidence. Evaluates spec compliance, correctness, regression risk, tests, security and maintainability. It does not silently become implementer.

Normalized review shape is defined in `schemas/reviewer-result.schema.json`.

## DeepSeek Direct auditor
Read-only independent contradiction layer after final checks/review. Focus: acceptance mismatch, edge cases, security/privacy, idempotency/concurrency, missing tests and risky shared assumptions. Never proxied through OpenRouter. Schema: `schemas/audit-result.schema.json`.

## OpenRouter drain implementer
May finish eligible substantive work already in flight only while scheduler is DRAIN and budget/policy allow. It may not cause admission of a new READY change.

## OpenRouter drain reviewer
May authoritatively review in DRAIN only when its model identity differs from the latest substantive implementer model for the candidate. If distinct review capacity is unavailable, wait rather than self-review.

## Qwen local helper
Advisory/mechanical only. Cannot satisfy review, audit, security, budget or human gates.

## Human
Durable authority for final approval, UI validation judgment, merge, product/spec ambiguity, sensitive findings, policy overrides, budget increases and rollback authorization.
