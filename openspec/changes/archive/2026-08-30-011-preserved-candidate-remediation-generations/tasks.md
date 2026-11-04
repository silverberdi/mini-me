# Tasks: Preserved Candidate Remediation Generations

## 1. Contract and Domain
- [x] 1.1 Define immutable remediation execution contract domain model.
- [x] 1.2 Define durable remediation request/status model.
- [x] 1.3 Define remediation failure/stop codes.
- [x] 1.4 Define deterministic remediation identity.

## 2. Persistence and Migration
- [x] 2.1 Add persistence model/repository.
- [x] 2.2 Add one migration extending current single head.
- [x] 2.3 Respect revision identifier constraints.
- [x] 2.4 Verify exactly one head after migration.
- [ ] 2.5 Verify offline PostgreSQL upgrade-to-head SQL.

## 3. Dedicated Remediation Service
- [x] 3.1 Add dedicated candidate-remediation service/component.
- [x] 3.2 Validate latest candidate authority fail-closed.
- [x] 3.3 Validate run current generation/SHA binding.
- [x] 3.4 Validate Job base/SHA binding.
- [x] 3.5 Validate candidate ref and manifest.
- [x] 3.6 Preserve `run.base_sha`.
- [x] 3.7 Reject advanced base with `BASE_ADVANCED_REQUIRES_INTEGRATION`.

## 4. Immutable Contract
- [x] 4.1 Parse and validate.
- [x] 4.2 Canonicalize and SHA-256 hash.
- [x] 4.3 Bind to exact source candidate.
- [x] 4.4 Reject contradictory replacement.
- [x] 4.5 Pass exact immutable contract/hash to implementer.

## 5. Managed Workspace
- [x] 5.1 Create remediation branch/worktree from source SHA.
- [x] 5.2 Use deterministic generation-aware naming.
- [x] 5.3 Never mutate/reuse source candidate workspace.
- [x] 5.4 Preserve dirty/failed workspaces.
- [x] 5.5 Make creation/reconciliation idempotent/restart-safe.

## 6. Drift Prevention
- [x] 6.1 Invoke implementer only after authority + contract persistence.
- [x] 6.2 Provide authoritative path and source identity.
- [x] 6.3 Prevent contract modification.
- [x] 6.4 Compute changed paths vs source SHA.
- [x] 6.5 Reject outside allowlist.
- [x] 6.6 Reject protected paths.
- [x] 6.7 Persist scope-violation evidence.
- [x] 6.8 Treat required out-of-contract work as blocker.

## 7. Candidate Finalization
- [x] 7.1 Measure progress vs source candidate.
- [x] 7.2 No new generation on NO_PROGRESS.
- [x] 7.3 mini me finalizes authoritative commit.
- [x] 7.4 Generate new manifest.
- [x] 7.5 Persist N+1 without mutating N.
- [x] 7.6 Supersede N only after N+1 durable authority.
- [x] 7.7 Align Job and run current bindings atomically; leave `run.base_sha` unchanged.

## 8. Checks and Preservation
- [x] 8.1 Run every configured check.
- [x] 8.2 Persist every result/diagnostic.
- [x] 8.3 Preserve canonical DB env sanitization.
- [x] 8.4 Preserve disposable DB fail-closed without short-circuiting later checks.
- [x] 8.5 Bind results to exact SHA/generation.
- [x] 8.6 Preserve failed N+1 as current and stop `REMEDIATION_CHECKS_FAILED`.
- [x] 8.7 Never classify successful Git + failed checks as base conflict.

## 9. Idempotency and Restart
- [x] 9.1 Identical authorization idempotent.
- [x] 9.2 Prevent duplicate agent invocation after completion.
- [x] 9.3 Prevent duplicate candidate generations.
- [x] 9.4 Reconcile durable boundaries after restart.
- [x] 9.5 Fail closed on contradictory state.
- [x] 9.6 Preserve workspace if preservation cannot be proven.

## 10. Review/Audit Isolation
- [x] 10.1 Prior generation review does not satisfy N+1.
- [x] 10.2 Prior generation audit does not satisfy N+1.
- [x] 10.3 Downstream gates bind current generation/SHA/base/manifest.

## 11. CLI / Orchestration
- [x] 11.1 Add explicit remediation operation.
- [x] 11.2 Require contract.
- [x] 11.3 Delegate mechanics to remediation service.
- [x] 11.4 Expose source identity, contract hash, remediation status/result.
- [x] 11.5 Preserve `--continue-preserved-candidate`.

## 12. Real-Git E2E
- [x] 12.1 Prove N -> remediation -> N+1 -> checks -> next gate.
- [x] 12.2 Prove N immutable.
- [x] 12.3 Prove `run.base_sha` remains historical.
- [x] 12.4 Prove failed N+1 remains preserved/current.
- [x] 12.5 Prove later remediation creates N+2 without mutating N/N+1.
- [x] 12.6 Prove replay creates no duplicate generations.
- [ ] 12.7 Prove advanced base stops with integration-required code.
- [x] 12.8 Prove scope violation preserves workspace and creates no generation.

## 13. Regression / Closure
- [x] 13.1 Focused remediation tests.
- [ ] 13.2 Existing human-resolution real-Git tests.
- [ ] 13.3 Legacy candidate adoption tests.
- [ ] 13.4 Transition-key tests.
- [x] 13.5 Candidate preservation/recovery tests.
- [ ] 13.6 Full SAFE pytest with DB vars unset.
- [ ] 13.7 Disposable PostgreSQL migration/integration acceptance.
- [x] 13.8 Ruff.
- [ ] 13.9 `git diff --check`.
- [x] 13.10 Exactly one Alembic head.
- [x] 13.11 OpenSpec strict validation PASS.
- [x] 13.12 Change 010 untouched.
- [x] 13.13 Archived changes untouched.

### Issue #268 evidence audit — unresolved items

> Tareas 2.5, 12.7, 13.2, 13.3, 13.4, 13.6, 13.7 y 13.9 siguen abiertas: faltan, respectivamente, salida de migración offline, E2E real de base avanzada, evidencia específica de human-resolution/adopción/transition-key, contexto DB unset, aceptación PostgreSQL desechable y resultado de diff-check. Detalle y fuentes en [auditoría #268](../../../../docs/evidence/issue-268_archive-validation-audit_2026-11-04.md).
