# Design

## Context

F9 is a future, disabled extension (see `proposal.md`). Existing project, provider, worktree, candidate-evidence, OpenSpec lifecycle, review, and fail-closed contracts are the authorities. The design must add one thin adapter boundary without making mini me an agent runtime or creating a second OpenSpec implementation.

## Goals / Non-Goals

**Goals:**

- Represent OpenCode as a configured CLI capability that is invocable only after explicit authorization.
- Reuse the existing project role/capability configuration, repository binding, managed worktree, candidate identity, evidence, provider-policy, and native OpenSpec contracts.
- Preserve implementer/reviewer separation, read-only independent review, and deterministic attribution of tool outcomes.
- Make unavailable CLI, provider failures, ambiguous output, and identity mismatches fail closed.

**Non-Goals:**

- Implementing OpenCode, any model provider, a shell, a queue, a scheduler, a router, or a new lifecycle engine.
- Replacing Codex/Antigravity/DeepSeek policy or selecting a provider automatically.
- Granting OpenCode merge, approval, ticket, deployment, scheduler, or production-data authority.
- Enabling F9 in the current disabled state or consuming quota during planning.

## Decisions

1. **One narrow CLI adapter contract.** The adapter accepts a role, project binding, candidate identity, worktree authorization, and operation; it returns structured invocation/outcome evidence. This is preferred over embedding OpenCode calls across orchestration stages because it keeps provider and lifecycle boundaries explicit.

2. **Existing authorities remain compositional.** Repository/worktree guards, candidate evidence, provider policy, and native OpenSpec workflows are called through their existing contracts. A new parallel guard or semantic verifier is not introduced because it would create competing authority.

3. **Capability configuration is explicit and scoped.** OpenCode is a capability/CLI entry in project configuration, disabled by default and bound to supported roles. It is not a hardcoded permanent provider or a global toggle; this preserves project-level configurability and operator authorization.

4. **Evidence is append-only by candidate identity.** The adapter records invocation identity, command/tool results, exit status, artifacts, and failure reason under the verified candidate. Results without a candidate identity remain diagnostic and cannot advance lifecycle state.

5. **Review remains read-only.** The adapter may start an independent-review session, but the worktree is read-only for that role and the reviewer cannot certify its own authored candidate. Merge and lifecycle decisions remain outside the adapter.

6. **Failure handling delegates to provider policy.** Quota, timeout, authentication, unavailable CLI, and ambiguous results produce a fail-closed outcome. Existing provider recovery/fallback policy decides whether and how work can resume; the adapter does not retry or spend independently.

### Alternatives considered

- **Embed OpenCode as a native model/provider implementation:** rejected because it would couple the core to one CLI and duplicate provider/runtime responsibilities.
- **Build a generic in-process shell/agent harness:** rejected because OpenCode already provides the requested host capabilities and this would violate the no-parallel-runtime boundary.
- **Treat OpenCode output as an implicit lifecycle transition:** rejected because official OpenSpec workflows, candidate evidence, and human authority must remain authoritative.

## Risks / Trade-offs

- **[Risk]** OpenCode or an API provider may be installed but expose different capabilities or output formats. → **Mitigation:** preflight the actual CLI/version/model capability and classify unsupported or ambiguous output as non-authoritative; keep F9 disabled until verified.
- **[Risk]** A CLI command could escape its intended worktree or access secrets. → **Mitigation:** require existing repository/worktree binding, allowed roots, credential policy, and role-specific tool restrictions before dispatch; fail closed on mismatch.
- **[Risk]** Provider retries could create unapproved cost or duplicate side effects. → **Mitigation:** delegate retry/fallback solely to existing provider policy and record side-effect-unknown outcomes before any continuation.
- **[Risk]** A reviewer could mutate or review its own candidate. → **Mitigation:** enforce immutable candidate identity, distinct role/author identity, read-only review execution, and no review authority over merge/lifecycle.

## Migration Plan

F9 remains planning-only until a later operator authorization. If authorized, first inventory existing project/provider/worktree/evidence contracts and install/verify OpenCode on the managed host; then add the smallest adapter/configuration integration, execute real E2E scenarios for execution and independent review, and verify failure/escape denials before enabling any project role. Rollback is disabling the capability and stopping future dispatches; do not delete candidate evidence or historical OpenSpec artifacts. No production migration, deployment, scheduler restart, or ticket closure is part of this Change.

## Open Questions

- The exact OpenCode version, host executable path, supported CLI invocation contract, and model/provider credential mapping must be selected during the authorized implementation preflight without changing the behavioral requirements above.
- The project-specific read-only enforcement mechanism for reviewer sessions must be confirmed against the managed worktree runtime before enabling `independent_review`.
