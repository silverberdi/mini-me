# R01 native APPLY local validation

Captured 2026-10-13 during local implementation. No provider inference, DeepSeek call, GitHub mutation, deployment, scheduler action, N01 dispatch, or production write was performed.

## Installed workflow resolution

- Codex CLI reports `codex-cli 0.161.0`.
- OpenSpec CLI reports `1.9.0`.
- The authorized worktree-local workflow path is `.agents/skills/openspec-apply-change/SKILL.md`.
- The resolver requires the exact skill name and version metadata, rejects unsafe change slugs and symlink escapes, and binds dispatch/evidence to the SHA-256 of the skill file read from the authorized worktree.
- The configured Codex implementer invocation is observed in `config/minime.yaml` as `codex exec - --approve-for-me --ephemeral`; the runner adds the documented JSONL observation flag to `exec` and retains stdin transport.
- Workflow evidence is considered observed only when complete JSONL contains successful tool records for reading that exact skill path and running `openspec instructions apply --change <exact change>`. Raw tool output and raw JSONL are not persisted in the evidence summary.

## Local tests

- `tests/test_native_openspec_apply.py` plus `tests/test_execution_pipeline.py`: **20 passed**.
- The new pipeline regression proves an absent native skill stops with `NEEDS_HUMAN` before an attempt or CLI invocation.
- Adjacent suites (`test_continuation_pipeline_integration.py`, `test_worktree_and_runner.py`, `test_review_pipeline.py`, `test_mixed_authorship_review.py`, `test_deepseek_audit.py`, `test_orchestration_coordinator.py`, and `test_waiting_capacity.py`), together with the native APPLY and execution-pipeline tests: **118 passed, 2 failed**. Both failures are in pre-existing review/audit remediation tests that attempt to reuse a deleted worktree after a candidate exists; the existing recovery authority denies this with `candidate evidence exists; this no-candidate recovery path cannot be used`. No recovery guard was weakened. This remains an implementation/test blocker for R01 interruption/remediation acceptance.
- Ruff check passed for the changed implementation and test files after import sorting. New native APPLY module/tests pass Ruff format check.
- `openspec validate real-openspec-agent-execution --strict`: PASS.
- `openspec doctor`: PASS.
- `git diff --check`: PASS at capture time.

## Acceptance boundary

These deterministic tests prove local preflight and trace-parser behavior only. They do **not** prove that a real Codex process loaded the skill, completed APPLY, produced a valid candidate, or that review/PR delivery works. Those require the authorized disposable external fixture and real provider/resource E2E, which have not been run.

## Candidate-aware worktree reconciliation follow-up (2026-10-14)

The two previously failing review/audit-remediation tests exposed a lifecycle mismatch: `ExecutionPipelineService._preserve_and_cleanup_worktree()` removed a clean candidate worktree after each pipeline pass, marking ownership `DELETED`; the next authorized remediation then entered `_verify_deleted_worktree_recreation()`, which correctly rejects candidate-bearing recovery. The candidate-free authority was left unchanged.

- Active orchestrated candidates with matching `CREATED` ownership and a durable candidate manifest now retain the same physical worktree through review/remediation. If candidate evidence exists with contradictory/missing Run or manifest identity, the pipeline blocks before cleanup.
- `WorktreeManager.create_worktree()` routes candidate evidence before the candidate-free recovery selector. Candidate adoption requires a physically present non-symlink `CREATED` path, exact active Run/Job/project/change, one current frozen candidate, matching Run/Job SHA and generation, original base/ownership/branch/ref, registered worktree and repository binding/marker, candidate SHA at both HEAD and branch ref, base ancestry, clean state, recomputed manifest equality, one completed attempt bound to the manifest, and no unresolved external actions.
- Candidate evidence paired with missing/DELETED ownership, local modifications, snapshot-route ambiguity, or contradictory identity fails closed without recreating from main or removing local files. `_verify_deleted_worktree_recreation()` was not edited and still rejects candidates.
- Regression tests: both review remediation and audit remediation now pass, preserve the same `CREATED` candidate worktree, and prove dirty local progress remains present while adoption is refused, Run/Job SHA contradiction is refused, and a candidate made `DELETED` is not recreated.
- Nine affected suites including the N01 PostgreSQL/Git regression module: **148 passed, 1 warning** (the existing Starlette TestClient/httpx deprecation warning). A final post-format run of both remediation regressions, the full execution-pipeline and N01 PostgreSQL/Git modules, and native APPLY tests: **59 passed**. The N01 module used its isolated localhost test database; no production endpoint or state was accessed or mutated.
- Final static checks: Ruff check PASS; Ruff format check PASS; `openspec validate real-openspec-agent-execution --strict` PASS; `openspec doctor` PASS; `git diff --check` PASS.
- N01 production identity, Run/Job, history, OpenSpec files, worktree and ownership were not accessed or changed during this implementation turn. No scheduler/provider/DeepSeek/external GitHub/deployment action occurred.

These results close the two local candidate-remediation regressions only. They do not satisfy real Codex APPLY, disposable external fixture delivery, provider review, Draft PR, or deployed E2E tasks. R01 remains at 6/25 tasks complete; no additional task checkbox was marked complete based on these tests.
