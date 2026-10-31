# Tasks

## 1. Authorization and repository/provider inventory

- [x] 1.1 Confirm a later explicit operator authorization for F9 implementation and record the project, roles, provider policy, base SHA, and managed worktree; verify that the disabled precondition prevents any OpenCode or model invocation.
- [x] 1.2 Inventory existing project capability configuration, repository/worktree binding, candidate identity/evidence, provider-policy, review-independence, and native OpenSpec dispatch contracts; verify the inventory identifies current writers, consumers, tests, and no parallel harness.
- [x] 1.3 Complete the F9 Removal Ledger with `NONE` or evidence-backed REMOVE/MIGRATE/RETAIN-WITH-REASON entries; verify every retained historical artifact has an owner and no obsolete runtime entrypoint is silently preserved.

## 2. Scoped OpenCode capability contract

- [x] 2.1 Add the smallest project-scoped OpenCode CLI capability configuration, disabled by default and limited to explicitly authorized `execution` and `independent_review` roles; verify unauthorized project-role combinations are refused before dispatch.
- [x] 2.2 Implement the adapter boundary using existing repository/worktree and candidate-identity authorities; verify a valid execution request starts only in the exact managed worktree and a binding mismatch causes zero filesystem mutation.
- [x] 2.3 Reuse the installed native OpenSpec workflows for `explore`, `propose`, `apply`, and `verify`; verify the adapter contains no prompt substitute, artifact generator, semantic verifier, queue, scheduler, shell, sync, or archive implementation.

## 3. Role, tool, and provider safety

- [x] 3.1 Enforce implementer versus independent-review role boundaries, including read-only review and distinct reviewer identity; verify the reviewer cannot mutate, approve its own candidate, merge, close a ticket, or transition lifecycle state.
- [x] 3.2 Validate actual OpenCode executable/version and configured model/API capability at preflight; verify unavailable CLI, unsupported capability, missing credential, and ambiguous output fail closed without claiming success.
- [x] 3.3 Delegate quota, timeout, authentication, and provider fallback behavior to the existing provider policy; verify OpenRouter/API failure preserves failure evidence, avoids an unapproved retry or spend, and returns a fail-closed outcome.

## 4. Evidence and real integration verification

- [x] 4.1 Record CLI/provider identity, role, worktree, candidate SHA, operation, tool results, artifacts, exit status, and failure reason under the immutable candidate evidence contract; verify unknown-candidate results cannot advance lifecycle state.
- [x] 4.2 Execute real end-to-end implementer and independent-review flows against an authorized isolated worktree with a configured API provider; verify observable invocation, file/tool effects, native OpenSpec result, and candidate evidence on the exact SHA.
- [x] 4.3 Execute negative E2E cases for disabled F9, worktree escape, reviewer mutation, provider quota/timeout, malformed output, deployment-like command, and remote closure request; verify each case is denied or stopped without forbidden side effects.
- [x] 4.4 Re-run unit, integration, lint, security, and relevant project checks after any retirement; verify no duplicate callers/writers, no fallback to an obsolete harness, and no scheduler, deployment, or ticket mutation was introduced.

## 5. Verify and controlled enablement

- [x] 5.1 Run the official OpenSpec verify workflow for the candidate and reconcile every discrepancy through the native workflow; verify all F9 scenarios map to observable evidence and the candidate SHA is immutable.
- [x] 5.2 Enable the capability only for the explicitly authorized project-role scope after successful E2E and independent review evidence; verify all other projects/roles remain disabled and rollback is possible by disabling the capability without deleting history.
