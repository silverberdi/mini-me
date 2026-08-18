# System Acceptance

## Golden functional path
Registered project → valid GitHub/OpenSpec binding → READY → isolated implementation → checks → complementary review → bounded correction → final checks → DeepSeek audit → UI preview/guided validation when required → human approval → draft PR ready → human merge → production deployment/verification → OpenSpec/GitHub closure → DONE.

## Required fault injection over MVP evolution
- provider non-zero exit/hang/timeout/quota/auth/malformed output;
- both primary capacities exhausted while active and READY work coexist;
- drain fallback denied by budget;
- attempted same-model fallback self-review;
- daemon kill during execution and between external side effect/state commit;
- existing/colliding worktree;
- repository remote mismatch;
- OpenSpec/Issue/project binding mismatch;
- deterministic check fail/timeout;
- preview references unsafe production config;
- candidate changes after human validation;
- production deployment failure;
- GitHub synchronization outage.

## Security acceptance
- no real secrets committed;
- DeepSeek credential never appears in OpenRouter configuration/request evidence;
- project external-provider allowlists enforced server-side;
- paid fallback deny/no-spend unless explicitly enabled;
- no autonomous merge;
- preview cannot silently use production DB/data endpoints.

## UX acceptance
Without opening raw logs, the human can understand what was requested, exact candidate identity, what changed, checks, reviewer, audit, preview status/scenarios, blocking findings and the effect of each available action.
