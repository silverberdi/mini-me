## 1. Preserve validated checkpoint through continuation

- [x] 1.1 Route Apply exhaustion continuation directly to Apply without dispatching or persisting a no-op native Update.
- [x] 1.2 Reuse only the prior strictly validated disposition checkpoint matching the same Run, Change, branch, worktree, generation, and candidate SHA.

## 2. Verify continuation and regression behavior

- [x] 2.1 Add focused tests for continuation-only retry preserving the checkpoint and unrelated regression still failing closed.
- [x] 2.2 Extend PostgreSQL-backed E2E for validated reclassification → partial Apply → continuation-only response → Apply; run OpenSpec Verify.
