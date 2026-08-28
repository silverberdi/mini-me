# Tasks: Preserved Candidate Remediation Generations

## 1. Contract and Domain
- [ ] 1.1 Define immutable remediation execution contract domain model.
- [ ] 1.2 Define durable remediation request/status model.
- [ ] 1.3 Define remediation failure/stop codes.
- [ ] 1.4 Define deterministic remediation identity.

## 2. Persistence and Migration
- [ ] 2.1 Add persistence model/repository.
- [ ] 2.2 Add one migration extending current single head.
- [ ] 2.3 Respect revision identifier constraints.
- [ ] 2.4 Verify exactly one head after migration.
- [ ] 2.5 Verify offline PostgreSQL upgrade-to-head SQL.

## 3. Dedicated Remediation Service
- [ ] 3.1 Add dedicated candidate-remediation service/component.
- [ ] 3.2 Validate latest candidate authority fail-closed.
- [ ] 3.3 Validate run current generation/SHA binding.
- [ ] 3.4 Validate Job base/SHA binding.
- [ ] 3.5 Validate candidate ref and manifest.
- [ ] 3.6 Preserve `run.base_sha`.
- [ ] 3.7 Reject advanced base with `BASE_ADVANCED_REQUIRES_INTEGRATION`.

## 4. Immutable Contract
- [ ] 4.1 Parse and validate.
- [ ] 4.2 Canonicalize and SHA-256 hash.
- [ ] 4.3 Bind to exact source candidate.
- [ ] 4.4 Reject contradictory replacement.
- [ ] 4.5 Pass exact immutable contract/hash to implementer.

## 5. Managed Workspace
- [ ] 5.1 Create remediation branch/worktree from source SHA.
- [ ] 5.2 Use deterministic generation-aware naming.
- [ ] 5.3 Never mutate/reuse source candidate workspace.
- [ ] 5.4 Preserve dirty/failed workspaces.
- [ ] 5.5 Make creation/reconciliation idempotent/restart-safe.

## 6. Drift Prevention
- [ ] 6.1 Invoke implementer only after authority + contract persistence.
- [ ] 6.2 Provide authoritative path and source identity.
- [ ] 6.3 Prevent contract modification.
- [ ] 6.4 Compute changed paths vs source SHA.
- [ ] 6.5 Reject outside allowlist.
- [ ] 6.6 Reject protected paths.
- [ ] 6.7 Persist scope-violation evidence.
- [ ] 6.8 Treat required out-of-contract work as blocker.

## 7. Candidate Finalization
- [ ] 7.1 Measure progress vs source candidate.
- [ ] 7.2 No new generation on NO_PROGRESS.
- [ ] 7.3 mini me finalizes authoritative commit.
- [ ] 7.4 Generate new manifest.
- [ ] 7.5 Persist N+1 without mutating N.
- [ ] 7.6 Supersede N only after N+1 durable authority.
- [ ] 7.7 Align Job and run current bindings atomically; leave `run.base_sha` unchanged.

## 8. Checks and Preservation
- [ ] 8.1 Run every configured check.
- [ ] 8.2 Persist every result/diagnostic.
- [ ] 8.3 Preserve canonical DB env sanitization.
- [ ] 8.4 Preserve disposable DB fail-closed without short-circuiting later checks.
- [ ] 8.5 Bind results to exact SHA/generation.
- [ ] 8.6 Preserve failed N+1 as current and stop `REMEDIATION_CHECKS_FAILED`.
- [ ] 8.7 Never classify successful Git + failed checks as base conflict.

## 9. Idempotency and Restart
- [ ] 9.1 Identical authorization idempotent.
- [ ] 9.2 Prevent duplicate agent invocation after completion.
- [ ] 9.3 Prevent duplicate candidate generations.
- [ ] 9.4 Reconcile durable boundaries after restart.
- [ ] 9.5 Fail closed on contradictory state.
- [ ] 9.6 Preserve workspace if preservation cannot be proven.

## 10. Review/Audit Isolation
- [ ] 10.1 Prior generation review does not satisfy N+1.
- [ ] 10.2 Prior generation audit does not satisfy N+1.
- [ ] 10.3 Downstream gates bind current generation/SHA/base/manifest.

## 11. CLI / Orchestration
- [ ] 11.1 Add explicit remediation operation.
- [ ] 11.2 Require contract.
- [ ] 11.3 Delegate mechanics to remediation service.
- [ ] 11.4 Expose source identity, contract hash, remediation status/result.
- [ ] 11.5 Preserve `--continue-preserved-candidate`.

## 12. Real-Git E2E
- [ ] 12.1 Prove N -> remediation -> N+1 -> checks -> next gate.
- [ ] 12.2 Prove N immutable.
- [ ] 12.3 Prove `run.base_sha` remains historical.
- [ ] 12.4 Prove failed N+1 remains preserved/current.
- [ ] 12.5 Prove later remediation creates N+2 without mutating N/N+1.
- [ ] 12.6 Prove replay creates no duplicate generations.
- [ ] 12.7 Prove advanced base stops with integration-required code.
- [ ] 12.8 Prove scope violation preserves workspace and creates no generation.

## 13. Regression / Closure
- [ ] 13.1 Focused remediation tests.
- [ ] 13.2 Existing human-resolution real-Git tests.
- [ ] 13.3 Legacy candidate adoption tests.
- [ ] 13.4 Transition-key tests.
- [ ] 13.5 Candidate preservation/recovery tests.
- [ ] 13.6 Full SAFE pytest with DB vars unset.
- [ ] 13.7 Disposable PostgreSQL migration/integration acceptance.
- [ ] 13.8 Ruff.
- [ ] 13.9 `git diff --check`.
- [ ] 13.10 Exactly one Alembic head.
- [ ] 13.11 OpenSpec strict validation PASS.
- [ ] 13.12 Change 010 untouched.
- [ ] 13.13 Archived changes untouched.
