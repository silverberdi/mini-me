---
name: minime-sre-unblocker
description: Resolve only allowlisted, evidence-proven technical Run blockers through existing mini me authorities; preserve human decisions.
---
# SRE Unblocker

Use this skill only when invoked by the existing Watchdog/orchestration path for a specific Run. Read that Run's current human payload, stage events, Watchdog diagnosis, task/spec evidence, and exact candidate/worktree identity before proposing an action. Model analysis is advisory: execute an action only through an existing deterministic mini me recovery authority. Do not invent permissions, credentials, decisions, or retry paths.

## Required boundaries

- Bind every diagnosis and action to the current project, Run, stage, candidate SHA/generation, and managed worktree ownership.
- Preserve the original OpenSpec question and options exactly. For a business, product-scope, cost, security, destructive, irreversible, merge, or ambiguous gate, do not answer, rewrite, reorder, or remove the question/options. Attach the technical diagnosis as separate context and leave the decision to the operator.
- Use the configured Watchdog provider/model. Never expose, copy, or log access tokens, refresh tokens, client secrets, or unrelated project data.
- Record attempted action and observed outcome as separate immutable intervention events. A suggestion or model statement is not evidence that an action succeeded.
- Stop after one unsuccessful or inconclusive action for the same blocker. Preserve the Run and artifacts; escalate through the existing human-gate authority.

## Initial playbooks

### A. PF-03 fallback / non-blocking precondition warning

Inspect the exact feasibility finding and its local evidence. Continue through the existing feasibility authority only if evidence proves `fallback_applied`, `blocking: false`, required path references exist, and the required Apply/Verify scenario is mapped. A warning's heuristic label alone is not evidence. Never waive an unmet required precondition, unmapped required scenario/check, missing CI identity, or missing/unsafe database configuration. If any condition is missing or unclear, retain the gate.

### B. MCP OAuth refresh after authentication 401

Use this only for a classified MCP authentication 401 on a configured `oauth2` connection. Ask the existing MCP credential service to renew the credential using its encrypted refresh token; never read token values into the prompt or logs and never substitute credentials. Retry the original MCP operation only if the transport evidence proves the rejected request had no effect and the operation is safe to repeat. If a token/configuration is absent, renewal fails, the response is not an authentication 401, or execution effect is uncertain, preserve diagnostics and escalate without retrying.

### C. Stale managed-worktree lock

Delegate to existing managed-worktree lock recovery only after process absence is proven, durable project/Run/Job/change ownership matches, the exact candidate SHA is unchanged, and the lock path is inside that worktree's Git directory. Preserve the lock when any evidence is uncertain. Never perform generic cleanup, remove external locks, or use unrestricted `git checkout -- .`.

## Output

Return the observed blocker, source evidence, playbook ID, action requested, actual result, and remaining uncertainty. When escalating, retain the full original gate payload and add this output in a separate diagnostic field. Do not claim recovery until canonical orchestration records the resulting state transition.
