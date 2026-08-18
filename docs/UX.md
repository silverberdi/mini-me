# UX Contract

## Principle
The primary experience is supervision, not agent chat. If no human decision is needed, mini me should avoid interrupting the owner.

## Human inbox classes
- `REVIEW`: final evidence review when no UI validation is required.
- `VALIDATE_UI`: runnable preview with guided scenarios.
- `QUESTION`: ambiguity that changes behavior/scope/architecture/security/cost.
- `BLOCKED`: cannot continue safely.
- `BUDGET`: paid fallback authorization or policy limit decision.
- `ROLLBACK`: production recovery decision.

## Review detail before raw logs
Show requested behavior, candidate identity, implementer, reviewer verdict, checks, audit risk/findings, files/diff size, deployment/preview status, required human action and consequences.

## UI validation
Show preview URL, candidate SHA/image digest, scenario, preconditions, numbered steps and expected outcome. Support PASS / FAIL / SKIP-with-reason / NOTE. Do not allow final approval while mandatory scenarios are unresolved.

## Failure UX
Every operational error should answer:
1. What failed?
2. Is useful work preserved?
3. Will mini me retry automatically?
4. When/under what condition?
5. Does the human need to act?

Status must never depend on color alone.
